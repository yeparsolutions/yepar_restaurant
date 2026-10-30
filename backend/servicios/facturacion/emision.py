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
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import (DocumentoTributario, Empresa, EstadoDocumento, EstadoLinea, EstadoPedido,
                    IntegracionFacturacion, MedioPago, Pago, Pedido, ProveedorFacturacion, TipoDocumento)
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
        if faltan == ["rut"] and datos.get("cedula"):
            faltan = []                         # Venezuela: se puede facturar a una persona con su cédula
        if faltan:
            raise ErrorNegocio("La factura necesita los datos del receptor: " + ", ".join(faltan) + ".")
        return datos
    return datos if datos.get("nombre") else {**datos, "nombre": "Consumidor Final"}


# ── Emisión ──────────────────────────────────────────────────
def _documento_de_venta(db: Session, pedido_id: str) -> Optional[DocumentoTributario]:
    """La boleta/factura de la cuenta (las notas de crédito no cuentan)."""
    return (db.query(DocumentoTributario).filter_by(pedido_id=pedido_id)
            .filter(DocumentoTributario.tipo != TipoDocumento.nota_credito).one_or_none())


def _forma_de_pago(db: Session, pedido: Pedido) -> Optional[str]:
    """Solo si toda la cuenta se pagó con UN medio sin ambigüedad (la tarjeta no distingue crédito/débito)."""
    medios = {m for (m,) in db.query(Pago.medio).filter_by(pedido_id=pedido.id).distinct()}
    if len(medios) == 1:
        return {MedioPago.efectivo: "efectivo", MedioPago.transferencia: "transferencia"}.get(next(iter(medios)))
    return None


def _referencia_de(db: Session, doc: DocumentoTributario) -> Optional[dict]:
    """Solo la nota de crédito: apunta al documento que anula (con la fecha en hora del restaurante)."""
    if doc.tipo != TipoDocumento.nota_credito:
        return None
    origen = db.get(DocumentoTributario, doc.documento_origen_id)
    emitido = origen.emitido_en if origen.emitido_en.tzinfo else origen.emitido_en.replace(tzinfo=timezone.utc)
    zona = ZoneInfo("America/Caracas" if origen.proveedor == ProveedorFacturacion.yeparfactura else "America/Santiago")
    return {"tipo": origen.tipo.value, "folio": origen.folio, "fecha": emitido.astimezone(zona).date().isoformat(),
            "motivo": doc.motivo}


def _intentar(db: Session, doc: DocumentoTributario, pedido: Pedido, integ: IntegracionFacturacion) -> DocumentoTributario:
    """Un intento contra el facturador. Deja el documento emitido, pendiente (reintentable) o rechazado."""
    solicitud = SolicitudEmision(
        tipo=doc.tipo.value, receptor=doc.receptor, items=_items_del_pedido(pedido), idempotency_key=doc.idempotency_key,
        referencia_externa=pedido.id, moneda=doc.moneda, forma_pago=_forma_de_pago(db, pedido),
        referencia=_referencia_de(db, doc))
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
        doc.moneda_montos, doc.tasa_cambio, doc.total_divisa = r.moneda_montos, r.tasa_cambio, r.total_divisa
        if doc.tipo == TipoDocumento.nota_credito:          # la nota emitida deja el original anulado
            db.get(DocumentoTributario, doc.documento_origen_id).estado = EstadoDocumento.anulado
    db.flush()
    return doc


def emitir_documento(db: Session, *, empresa_id: int, usuario_id: int, pedido_id: str, tipo: TipoDocumento,
                     receptor: Optional[dict] = None) -> DocumentoTributario:
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

    doc = _documento_de_venta(db, pedido.id)
    if doc is not None and doc.estado in (EstadoDocumento.emitido, EstadoDocumento.anulado):
        return doc
    datos_receptor = _receptor(tipo, receptor if receptor is not None else (doc.receptor if doc else None))
    if doc is None:
        doc = DocumentoTributario(
            empresa_id=empresa_id, sucursal_id=pedido.sucursal_id, pedido_id=pedido.id, proveedor=integ.proveedor,
            tipo=tipo, idempotency_key=f"yrs-{pedido.id}", emitido_por_id=usuario_id)
        db.add(doc)
    doc.proveedor, doc.tipo, doc.receptor = integ.proveedor, tipo, datos_receptor
    doc.moneda = empresa.moneda
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
    doc = _documento_de_venta(db, pedido.id)
    if doc is None:
        raise ErrorNoEncontrado("Esta cuenta aún no tiene documento tributario.")
    return doc


def listar_documentos(db: Session, *, empresa_id: int, estado: Optional[EstadoDocumento] = None,
                      limite: int = 100) -> list:
    consulta = db.query(DocumentoTributario).filter_by(empresa_id=empresa_id)
    if estado is not None:
        consulta = consulta.filter_by(estado=estado)
    return consulta.order_by(DocumentoTributario.id.desc()).limit(limite).all()


# ── Emisión automática al cobrar ─────────────────────────────
def configurar(db: Session, *, empresa_id: int, emision_automatica: Optional[bool] = None,
               tipo_automatico: Optional[TipoDocumento] = None) -> IntegracionFacturacion:
    integ = integracion_activa(db, empresa_id)
    tipo = tipo_automatico or integ.tipo_automatico
    activar = integ.emision_automatica if emision_automatica is None else emision_automatica
    if activar and integ.proveedor == ProveedorFacturacion.yeparfactura:
        raise ErrorNegocio("En Venezuela la factura necesita los datos del cliente (RIF o cédula): se emite desde la caja.")
    if activar and tipo != TipoDocumento.boleta:
        raise ErrorNegocio("Solo la boleta (consumidor final) se puede emitir sola; la factura necesita los datos del cliente.")
    integ.emision_automatica, integ.tipo_automatico = activar, tipo
    db.flush()
    return integ


def emitir_automatico(db: Session, *, empresa_id: int, usuario_id: int, pedido_id: str) -> Optional[DocumentoTributario]:
    """
    La llama el cobro cuando la mesa queda pagada. NUNCA bloquea ni falla el cobro: si no corresponde
    o algo no cuadra devuelve None; si el facturador no responde, el documento queda pendiente.
    """
    integ = db.get(IntegracionFacturacion, empresa_id)
    if integ is None or not integ.activo or not integ.emision_automatica:
        return None
    try:
        return emitir_documento(db, empresa_id=empresa_id, usuario_id=usuario_id, pedido_id=pedido_id,
                                tipo=integ.tipo_automatico)
    except ErrorNegocio:
        return None


# ── Nota de crédito: anular un documento emitido ─────────────
def anular_documento(db: Session, *, empresa_id: int, usuario_id: int, documento_id: int, motivo: str) -> DocumentoTributario:
    """
    Anula por completo una boleta/factura ya emitida con una nota de crédito que apunta a ella.
    Seguro de repetir: si la nota ya existe (emitida o pendiente) se devuelve / se reintenta, sin duplicar.
    Ojo: esto es solo el papel tributario; devolver el dinero al cliente es aparte.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErrorNegocio("Indica el motivo de la anulación.")
    integ = integracion_activa(db, empresa_id)
    origen = db.get(DocumentoTributario, documento_id)
    if origen is None or origen.empresa_id != empresa_id:
        raise ErrorNoEncontrado("El documento no existe.")
    if origen.tipo == TipoDocumento.nota_credito:
        raise ErrorNegocio("Una nota de crédito no se anula.")
    if origen.proveedor != integ.proveedor:
        raise ErrorNegocio("El documento se emitió con otro facturador: cambia a ese facturador para anularlo.")
    if origen.estado not in (EstadoDocumento.emitido, EstadoDocumento.anulado):
        raise ErrorNegocio("Solo se anula un documento ya emitido.")

    clave = f"yrs-nc-{origen.id}"
    nota = db.query(DocumentoTributario).filter_by(empresa_id=empresa_id, idempotency_key=clave).one_or_none()
    if nota is not None and nota.estado in (EstadoDocumento.emitido, EstadoDocumento.anulado):
        return nota
    if nota is None:
        nota = DocumentoTributario(
            empresa_id=empresa_id, sucursal_id=origen.sucursal_id, pedido_id=origen.pedido_id, proveedor=origen.proveedor,
            tipo=TipoDocumento.nota_credito, idempotency_key=clave, receptor=origen.receptor, moneda=origen.moneda,
            documento_origen_id=origen.id, emitido_por_id=usuario_id)
        db.add(nota)
    nota.motivo = motivo[:200]
    db.flush()
    return _intentar(db, nota, cargar_pedido(db, empresa_id, origen.pedido_id), integ)
