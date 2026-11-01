# ============================================================
# YEPAR RESTAURANT — backend/servicios/despacho.py
# Delivery: de una cuenta a una orden de entrega en Yepar Go, con seguimiento.
#
# Analogía: el cajero llena el "talón de encargo" (a quién y adónde) y el
# sistema llama a la empresa de reparto. Si la línea está ocupada, el talón
# queda en la bandeja "pendiente" y se vuelve a llamar solo, sin pedir dos motoristas
# cuando ya se había pedido uno... salvo que la llamada se cortara justo al contestar
# (Yepar Go aún no tiene clave de idempotencia): por eso cada orden lleva en sus notas
# la referencia "YRS-D<n>" para encontrarla a mano si algún día se duplica.
# Los servicios no hacen commit.
# ============================================================

from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import Despacho, EstadoDespacho, EstadoPedido, IntegracionDespacho, LineaPedido
from servicios.despacho_yepargo import ConectorYeparGo, ErrorDespacho
from servicios.facturacion.secretos import cifrar, descifrar
from servicios.pedidos import cargar_pedido

ESTADOS_FINALES_GO = ("delivered", "failed", "cancelled")


def _conector(integ: IntegracionDespacho) -> ConectorYeparGo:
    try:
        return ConectorYeparGo(descifrar(integ.api_key_cifrada))
    except ErrorNegocio:
        raise ErrorNegocio("No se pudo leer la API Key de Yepar Go (cambió la SECRET_KEY): vuelve a conectarla.")


# ── Conexión ─────────────────────────────────────────────────
def conectar(db: Session, *, empresa_id: int, api_key: str, direccion_retiro: Optional[str] = None,
             centro_retiro_id: Optional[str] = None) -> IntegracionDespacho:
    """Guarda (cifrada) la API Key DESPUÉS de comprobar que Yepar Go la acepta y que el centro de retiro existe."""
    api_key = (api_key or "").strip()
    if not api_key:
        raise ErrorNegocio("Falta la API Key de Yepar Go.")
    try:
        centros = ConectorYeparGo(api_key).centros_de_retiro()
    except ErrorDespacho as e:
        raise ErrorNegocio(f"No se pudo validar la API Key: {e.detalle}")
    if centro_retiro_id and centro_retiro_id not in {c.get("id") for c in centros}:
        raise ErrorNegocio("Ese centro de retiro no existe en tu cuenta de Yepar Go.")
    integ = db.get(IntegracionDespacho, empresa_id)
    if integ is None:
        integ = IntegracionDespacho(empresa_id=empresa_id, api_key_cifrada=cifrar(api_key))
        db.add(integ)
    integ.api_key_cifrada, integ.activo = cifrar(api_key), True
    integ.direccion_retiro = (direccion_retiro or "").strip() or None
    integ.centro_retiro_id = centro_retiro_id or None
    db.flush()
    return integ


def desconectar(db: Session, *, empresa_id: int) -> None:
    integ = db.get(IntegracionDespacho, empresa_id)
    if integ is None:
        raise ErrorNoEncontrado("Este restaurante no tiene Yepar Go conectado.")
    integ.activo = False
    db.flush()


def integracion_activa(db: Session, empresa_id: int) -> IntegracionDespacho:
    integ = db.get(IntegracionDespacho, empresa_id)
    if integ is None or not integ.activo:
        raise ErrorNoEncontrado("Este restaurante no tiene Yepar Go conectado: el administrador debe conectarlo.")
    return integ


def api_key_final(integ: IntegracionDespacho) -> str:
    return "••••" + descifrar(integ.api_key_cifrada)[-4:]


def centros_de_retiro(db: Session, empresa_id: int) -> list[dict]:
    try:
        return _conector(integracion_activa(db, empresa_id)).centros_de_retiro()
    except ErrorDespacho as e:
        raise ErrorNegocio(e.detalle)


# ── Despachos ────────────────────────────────────────────────
def _resumen_del_pedido(db: Session, pedido) -> str:
    cantidades: dict[str, int] = {}
    for l in db.query(LineaPedido).filter_by(pedido_id=pedido.id).order_by(LineaPedido.id).all():
        if l.estado.value != "cancelada":
            cantidades[l.item.nombre] = cantidades.get(l.item.nombre, 0) + l.cantidad     # 2 hamburguesas, no 1+1
    return ", ".join(f"{n}× {nombre}" for nombre, n in cantidades.items())[:300]


def _payload(db: Session, d: Despacho, integ: IntegracionDespacho, pedido) -> dict:
    notas = f"YRS-D{d.id} · Pedido {pedido.id[:8]}" + (f" · {d.notas}" if d.notas else "")
    datos = {
        "recipientName": d.destinatario, "recipientPhone": d.telefono, "recipientEmail": d.email,
        "deliveryAddress": d.direccion, "deliveryCity": d.ciudad, "deliveryRegion": d.region,
        "deliveryLat": float(d.latitud) if d.latitud is not None else None,
        "deliveryLng": float(d.longitud) if d.longitud is not None else None,
        "pickupAddress": integ.direccion_retiro, "pickupCenterId": integ.centro_retiro_id,
        "packageDescription": _resumen_del_pedido(db, pedido) or None, "notes": notas,
    }
    return {k: v for k, v in datos.items() if v not in (None, "")}


def _intentar(db: Session, d: Despacho, integ: IntegracionDespacho, pedido) -> Despacho:
    d.intentos += 1
    try:
        orden = _conector(integ).crear_orden(_payload(db, d, integ, pedido))
    except ErrorDespacho as e:
        d.estado = EstadoDespacho.pendiente if e.reintentable else EstadoDespacho.rechazado
        d.ultimo_error = e.detalle
    else:
        d.estado, d.ultimo_error = EstadoDespacho.creado, None
        d.go_orden_id, d.go_numero = orden.get("id"), orden.get("orderNumber")
        d.estado_go, d.seguimiento_url = orden.get("status"), orden.get("trackingUrl")
    db.flush()
    return d


def crear_despacho(db: Session, *, empresa_id: int, usuario_id: int, pedido_id: str, destinatario: str, direccion: str,
                   telefono: Optional[str] = None, email: Optional[str] = None, ciudad: Optional[str] = None,
                   region: Optional[str] = None, latitud=None, longitud=None, notas: Optional[str] = None) -> Despacho:
    """
    Pide el reparto de una cuenta. Repetirlo es seguro: si ya se creó devuelve el mismo despacho; si
    quedó pendiente o rechazado, corrige los datos y lo vuelve a intentar.
    """
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    if pedido.estado == EstadoPedido.anulado:
        raise ErrorNegocio("La cuenta está anulada: no se despacha.")
    destinatario, direccion = (destinatario or "").strip(), (direccion or "").strip()
    if len(destinatario) < 2 or not direccion:
        raise ErrorNegocio("Indica el nombre del cliente y la dirección de entrega.")
    integ = integracion_activa(db, empresa_id)
    d = db.query(Despacho).filter_by(pedido_id=pedido.id).one_or_none()
    if d is not None and d.estado == EstadoDespacho.creado:
        return d
    if d is None:
        d = Despacho(empresa_id=empresa_id, sucursal_id=pedido.sucursal_id, pedido_id=pedido.id, creado_por_id=usuario_id,
                     estado=EstadoDespacho.pendiente, intentos=0, destinatario=destinatario, direccion=direccion)
        db.add(d)
    d.destinatario, d.direccion = destinatario, direccion
    d.telefono, d.email, d.ciudad, d.region = telefono or None, email or None, ciudad or None, region or None
    d.latitud, d.longitud, d.notas = latitud, longitud, notas or None
    db.flush()                                      # necesita su id para la referencia YRS-D<n>
    return _intentar(db, d, integ, pedido)


def despacho_de_pedido(db: Session, *, empresa_id: int, pedido_id: str) -> Despacho:
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    d = db.query(Despacho).filter_by(pedido_id=pedido.id).one_or_none()
    if d is None:
        raise ErrorNoEncontrado("Esta cuenta no tiene despacho.")
    return d


def listar(db: Session, *, empresa_id: int, estado: Optional[EstadoDespacho] = None,
           solo_en_curso: bool = False) -> list[Despacho]:
    q = db.query(Despacho).filter_by(empresa_id=empresa_id)
    if estado is not None:
        q = q.filter(Despacho.estado == estado)
    if solo_en_curso:
        q = q.filter(Despacho.estado == EstadoDespacho.creado, Despacho.estado_go.notin_(ESTADOS_FINALES_GO))
    return q.order_by(Despacho.id.desc()).all()


def reintentar_pendientes(db: Session, *, empresa_id: int) -> list[Despacho]:
    """Vuelve a pedir los despachos que Yepar Go no alcanzó a confirmar."""
    integ = integracion_activa(db, empresa_id)
    pendientes = db.query(Despacho).filter_by(empresa_id=empresa_id, estado=EstadoDespacho.pendiente).all()
    return [_intentar(db, d, integ, cargar_pedido(db, empresa_id, d.pedido_id)) for d in pendientes]


def actualizar_estado(db: Session, *, empresa_id: int, despacho_id: Optional[int] = None) -> list[Despacho]:
    """Consulta a Yepar Go cómo va la entrega (uno, o todos los que siguen en curso)."""
    integ = integracion_activa(db, empresa_id)
    if despacho_id is not None:
        d = db.get(Despacho, despacho_id)
        if d is None or d.empresa_id != empresa_id:
            raise ErrorNoEncontrado(f"El despacho {despacho_id} no existe.")
        if d.estado != EstadoDespacho.creado:
            raise ErrorNegocio("Ese despacho aún no está creado en Yepar Go.")
        objetivos = [d]
    else:
        objetivos = listar(db, empresa_id=empresa_id, solo_en_curso=True)
    conector = _conector(integ)
    for d in objetivos:
        try:
            orden = conector.obtener_orden(d.go_orden_id)
        except ErrorDespacho as e:
            if despacho_id is not None:
                raise ErrorNegocio(e.detalle)
            d.ultimo_error = e.detalle                  # en la actualización masiva uno caído no frena a los demás
            continue
        d.estado_go = orden.get("status", d.estado_go)
        d.seguimiento_url = orden.get("trackingUrl") or d.seguimiento_url
        d.ultimo_error = None
    db.flush()
    return objetivos
