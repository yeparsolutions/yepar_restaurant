# ============================================================
# YEPAR RESTAURANT — backend/servicios/facturacion/emision.py
# Conectar el facturador del restaurante y emitir boletas/facturas de
# las cuentas pagadas, con reintentos que nunca duplican el folio.
#
# Analogía: el cajero le pasa la cuenta pagada al notario. Si el teléfono
# se corta a mitad de la llamada, el papel queda "en trámite": al volver la
# línea se repite el encargo con el MISMO número de trámite (la clave de
# idempotencia) y el notario devuelve el mismo folio en vez de timbrar otro.
#
# Regla de impuestos: se factura lo vendido menos el descuento. La PROPINA
# no se factura (es voluntaria y no es venta del restaurante).
# ============================================================

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import (DocumentoTributario, Empresa, EstadoDocumento, EstadoLinea, EstadoPedido,
                    IntegracionFacturacion, Pedido, ProveedorFacturacion, TipoDocumento)
from servicios.facturacion import base
from servicios.facturacion.base import ErrorFacturador, SolicitudEmision
from servicios.facturacion.secretos import cifrar, descifrar
from servicios.facturacion.yepardte import ConectorYeparDTE
from servicios.facturacion.yeparfactura import ConectorYeparFactura
from servicios.pedidos import cargar_pedido

CENTAVO = Decimal("0.01")
PAIS_DEL_PROVEEDOR = {ProveedorFacturacion.yepardte: "CL", ProveedorFacturacion.yeparfactura: "VE"}
_CONECTORES = {ProveedorFacturacion.yepardte: ConectorYeparDTE, ProveedorFacturacion.yeparfactura: ConectorYeparFactura}


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _cargar_empresa(db: Session, empresa_id: int) -> Empresa:
    empresa = db.get(Empresa, empresa_id)
    if empresa is None:
        raise ErrorNoEncontrado("La empresa no existe.")
    return empresa


# ── Conexión con el facturador ───────────────────────────────
def conectar(db: Session, *, empresa_id: int, proveedor: ProveedorFacturacion, api_key: str) -> IntegracionFacturacion:
    """Guarda (cifrada) la API Key del restaurante DESPUÉS de comprobar que el facturador la acepta."""
    api_key = (api_key or "").strip()
    if not api_key:
        raise ErrorNegocio("Falta la API Key del facturador.")
    empresa = _cargar_empresa(db, empresa_id)
    pais = PAIS_DEL_PROVEEDOR[proveedor]
    if empresa.pais != pais:
        raise ErrorNegocio(f"{proveedor.value} factura para {pais}, y este restaurante está configurado en {empresa.pais}.")
    try:
        _CONECTORES[proveedor](api_key).ping()
    except ErrorFacturador as e:
        raise ErrorNegocio(f"No se pudo validar la API Key: {e.detalle}")
    integ = db.get(IntegracionFacturacion, empresa_id)
    if integ is None:
        integ = IntegracionFacturacion(empresa_id=empresa_id, proveedor=proveedor, api_key_cifrada=cifrar(api_key))
        db.add(integ)
    else:
        integ.proveedor, integ.api_key_cifrada, integ.activo = proveedor, cifrar(api_key), True
    db.flush()
    return integ


def desconectar(db: Session, *, empresa_id: int) -> None:
    integ = db.get(IntegracionFacturacion, empresa_id)
    if integ is None:
        raise ErrorNoEncontrado("Este restaurante no tiene un facturador conectado.")
    integ.activo = False
    db.flush()


def integracion_activa(db: Session, empresa_id: int) -> IntegracionFacturacion:
    integ = db.get(IntegracionFacturacion, empresa_id)
    if integ is None or not integ.activo:
        raise ErrorNegocio("Este restaurante no tiene un facturador conectado: conéctalo en Configuración.")
    return integ


def api_key_final(integ: IntegracionFacturacion) -> str:
    """Solo los últimos 4 caracteres: lo bastante para reconocerla, nada para usarla."""
    return "••••" + descifrar(integ.api_key_cifrada)[-4:]


# ── Armado del documento ─────────────────────────────────────
def _items_del_pedido(pedido: Pedido) -> list:
    """Una línea de documento por plato (con sus extras en el precio) y el descuento repartido proporcionalmente."""
    lineas = [l for l in pedido.lineas if l.estado != EstadoLinea.cancelada]
    if not lineas:
        raise ErrorNegocio("La cuenta no tiene platos que facturar.")
    items = []
    for l in lineas:
        unitario = l.precio_unitario + sum((e.precio for e in l.extras), Decimal("0"))
        items.append({"nombre": l.item.nombre, "cantidad": l.cantidad, "precio_unitario": unitario.quantize(CENTAVO),
                      "descuento": Decimal("0.00"), "_total": l.total})
    subtotal = sum((i["_total"] for i in items), Decimal("0"))
    restante = pedido.descuento
    for i, item in enumerate(items):
        parte = restante if i == len(items) - 1 else (pedido.descuento * item["_total"] / subtotal).quantize(CENTAVO)
        item["descuento"] = parte
        restante -= parte
    for item in items:
        del item["_total"]
    return items


def _receptor(tipo: TipoDocumento, datos: Optional[dict]) -> dict:
    datos = {k: (v or "").strip() for k, v in (datos or {}).items() if v is not None}
    if tipo == TipoDocumento.factura:
        faltan = [c for c in ("rut", "nombre") if not datos.get(c)]
        if faltan:
            raise ErrorNegocio("La factura necesita los datos del receptor: " + ", ".join(faltan) + ".")
        return datos
    return datos if datos.get("nombre") else {**datos, "nombre": "Consumidor Final"}


# ── Emisión ──────────────────────────────────────────────────
def _intentar(db: Session, doc: DocumentoTributario, pedido: Pedido, integ: IntegracionFacturacion) -> DocumentoTributario:
    """Un intento contra el facturador. Deja el documento emitido, pendiente (reintentable) o rechazado."""
    solicitud = SolicitudEmision(
        tipo=doc.tipo.value, receptor=doc.receptor, items=_items_del_pedido(pedido), idempotency_key=doc.idempotency_key,
        referencia_externa=pedido.id, moneda=doc.moneda, tasa_cambio=doc.tasa_cambio)
    doc.intentos += 1
    try:
        r = _CONECTORES[integ.proveedor](descifrar(integ.api_key_cifrada)).emitir(solicitud)
    except ErrorFacturador as e:
        doc.estado = EstadoDocumento.pendiente if e.reintentable else EstadoDocumento.rechazado
        doc.ultimo_error = e.detalle[:500]
    else:
        doc.estado, doc.ultimo_error = EstadoDocumento.emitido, None
        doc.folio, doc.neto, doc.iva, doc.total = r.folio, r.neto, r.iva, r.total
        doc.pdf_url, doc.track_id, doc.emitido_en = r.pdf_url, r.track_id, _ahora()
    db.flush()
    return doc


def emitir_documento(db: Session, *, empresa_id: int, usuario_id: int, pedido_id: str, tipo: TipoDocumento,
                     receptor: Optional[dict] = None, tasa_cambio=None) -> DocumentoTributario:
    """
    Emite la boleta/factura de una cuenta ya pagada. Es seguro repetirlo:
      - ya emitido  → devuelve el mismo documento (no vuelve a llamar al facturador).
      - pendiente o rechazado → reintenta (con los datos corregidos si vienen).
    Si el facturador no responde, el documento queda `pendiente` (la venta NO se bloquea).
    """
    integ = integracion_activa(db, empresa_id)
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    if pedido.estado != EstadoPedido.cerrado:
        raise ErrorNegocio("Solo se factura una cuenta ya pagada.")
    if integ.proveedor == ProveedorFacturacion.yeparfactura and tipo != TipoDocumento.factura:
        raise ErrorNegocio("En Venezuela solo se emite factura (no existe boleta).")
    empresa = _cargar_empresa(db, empresa_id)
    tasa = None if tasa_cambio is None else Decimal(str(tasa_cambio))
    if integ.proveedor == ProveedorFacturacion.yeparfactura and (tasa is None or tasa <= 0):
        raise ErrorNegocio("Indica la tasa de cambio del día: la factura venezolana muestra ambos montos.")

    doc = db.query(DocumentoTributario).filter_by(pedido_id=pedido.id).one_or_none()
    if doc is not None and doc.estado == EstadoDocumento.emitido:
        return doc
    datos_receptor = _receptor(tipo, receptor if receptor is not None else (doc.receptor if doc else None))
    if doc is None:
        doc = DocumentoTributario(
            empresa_id=empresa_id, sucursal_id=pedido.sucursal_id, pedido_id=pedido.id, proveedor=integ.proveedor,
            tipo=tipo, idempotency_key=f"yrs-{pedido.id}", emitido_por_id=usuario_id)
        db.add(doc)
    doc.proveedor, doc.tipo, doc.receptor = integ.proveedor, tipo, datos_receptor
    doc.moneda, doc.tasa_cambio = empresa.moneda, tasa
    db.flush()
    return _intentar(db, doc, pedido, integ)


def reintentar_pendientes(db: Session, *, empresa_id: int) -> list:
    """Reintenta todos los documentos que quedaron pendientes (por ejemplo, al volver la conexión)."""
    integ = integracion_activa(db, empresa_id)
    pendientes = (db.query(DocumentoTributario).filter_by(empresa_id=empresa_id, estado=EstadoDocumento.pendiente)
                  .order_by(DocumentoTributario.id).all())
    return [_intentar(db, d, cargar_pedido(db, empresa_id, d.pedido_id), integ) for d in pendientes]


# ── Consultas ────────────────────────────────────────────────
def documento_de_pedido(db: Session, *, empresa_id: int, pedido_id: str) -> DocumentoTributario:
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    doc = db.query(DocumentoTributario).filter_by(pedido_id=pedido.id).one_or_none()
    if doc is None:
        raise ErrorNoEncontrado("Esta cuenta aún no tiene documento tributario.")
    return doc


def listar_documentos(db: Session, *, empresa_id: int, estado: Optional[EstadoDocumento] = None,
                      limite: int = 100) -> list:
    consulta = db.query(DocumentoTributario).filter_by(empresa_id=empresa_id)
    if estado is not None:
        consulta = consulta.filter_by(estado=estado)
    return consulta.order_by(DocumentoTributario.id.desc()).limit(limite).all()
