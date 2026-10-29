# ============================================================
# YEPAR RESTAURANT — backend/servicios/cocina.py
# Lo que hace cocina y barra con las comandas: empezar, marcar listo,
# entregar, ver la pantalla de comandas y el botón "se acabó".
#
# Analogía: la ventanilla de la cocina. Las comandas llegan colgadas
# (enviada), el cocinero las toma (en preparación), toca la campanita
# (lista: se enciende la mesa y vibra la tablet del mesero) y el mesero
# retira el plato (entregada). Al tocar la campanita los ingredientes
# salen de verdad de la bodega.
#
# Se marca POR PLATO, no por mesa completa. Cocina y barra ven solo lo
# suyo (el barman es un cocinero con estación 'barra').
# Los servicios no hacen commit (lo decide quien llama).
# ============================================================

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import (EstacionCocina, EstadoLinea, EstadoPedido, Extra, Item, LineaPedido, Pedido,
                    RecetaLinea, RolUsuario, Usuario)
from servicios.pedidos import cargar_linea
from servicios.reservas import consumir_reserva
from servicios.stock import cargar_item, obtener_stock, validar_sucursal

ROLES_DE_COCINA = (RolUsuario.cocinero, RolUsuario.administrador)
_PEDIDOS_VIVOS = (EstadoPedido.abierto, EstadoPedido.cuenta_pedida)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ResultadoListo:
    linea: LineaPedido
    sin_stock: list = field(default_factory=list)    # ingredientes que quedaron en negativo (alerta al admin)


@dataclass
class ComandaLinea:
    """Una línea tal como la ve la pantalla de cocina/barra."""
    linea_id: str
    pedido_id: str
    mesa: str
    mesero_id: Optional[int]
    plato: str
    cantidad: int
    estado: EstadoLinea
    comensal: Optional[int]
    nota: Optional[str]
    sin: list                         # ["Cebolla"]  → "SIN cebolla"
    extras: list                      # ["Extra tocineta"]
    enviada_en: Optional[datetime]
    receta_id: Optional[int] = None   # para que el cocinero abra la receta desde la comanda


@dataclass
class Retiro:
    """Un plato listo esperando que el mesero lo retire."""
    linea_id: str
    pedido_id: str
    mesa: str
    plato: str
    cantidad: int
    estacion: str
    lista_en: Optional[datetime]


# ------------------------------------------------------------
# Quién puede
# ------------------------------------------------------------
def _cargar_cocinero(db: Session, empresa_id: int, usuario_id: int, linea: LineaPedido) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or usuario.empresa_id != empresa_id or not usuario.activo:
        raise ErrorNoEncontrado("El usuario no existe.")
    roles = {r.rol for r in usuario.roles}
    if not roles & set(ROLES_DE_COCINA):
        raise ErrorNegocio(f"'{usuario.nombre}' no trabaja en cocina ni en barra.")
    es_admin = RolUsuario.administrador in roles
    if not es_admin and usuario.estacion is not None and usuario.estacion.value != linea.estacion:
        raise ErrorNegocio(f"Este plato es de la {linea.estacion}: '{usuario.nombre}' atiende la "
                           f"{usuario.estacion.value}.")
    return usuario


def _exigir_pedido_vivo(linea: LineaPedido):
    if linea.pedido.estado not in _PEDIDOS_VIVOS:
        raise ErrorNegocio(f"El pedido está '{linea.pedido.estado.value}': ya no admite este cambio.")


# ------------------------------------------------------------
# Cambios de estado
# ------------------------------------------------------------
def iniciar_preparacion(db: Session, *, empresa_id: int, linea_id: str, usuario_id: int) -> LineaPedido:
    """El cocinero toma la comanda: enviada → en preparación."""
    linea = cargar_linea(db, empresa_id, linea_id)
    _cargar_cocinero(db, empresa_id, usuario_id, linea)
    _exigir_pedido_vivo(linea)
    if linea.estado != EstadoLinea.enviada:
        raise ErrorNegocio(f"El plato está '{linea.estado.value}': solo se empieza uno recién enviado.")
    linea.estado = EstadoLinea.en_preparacion
    linea.preparacion_en = _ahora()
    db.flush()
    return linea


def marcar_lista(db: Session, *, empresa_id: int, linea_id: str, usuario_id: int) -> ResultadoListo:
    """
    La campanita: el plato está listo. Los ingredientes reservados salen de la
    bodega (consumo por venta) y la mesa se enciende para el mesero.
    Se puede marcar directo desde 'enviada' (un plato que sale al tiro).
    """
    linea = cargar_linea(db, empresa_id, linea_id)
    _cargar_cocinero(db, empresa_id, usuario_id, linea)
    _exigir_pedido_vivo(linea)
    if linea.estado not in (EstadoLinea.enviada, EstadoLinea.en_preparacion):
        raise ErrorNegocio(f"El plato está '{linea.estado.value}': no se puede marcar como listo.")

    consumidas = consumir_reserva(db, empresa_id=empresa_id, referencia_id=linea.id, usuario_id=usuario_id)
    sin_stock = []
    for reserva in consumidas:
        stock = obtener_stock(db, empresa_id, reserva.item_id, reserva.sucursal_id)
        if stock.cantidad_fisica < 0:
            sin_stock.append(stock.item.nombre)
    linea.estado = EstadoLinea.lista
    linea.lista_en = _ahora()
    db.flush()
    return ResultadoListo(linea=linea, sin_stock=sin_stock)


def marcar_entregada(db: Session, *, empresa_id: int, linea_id: str) -> LineaPedido:
    """El mesero retiró el plato y lo llevó a la mesa: lista → entregada."""
    linea = cargar_linea(db, empresa_id, linea_id)
    _exigir_pedido_vivo(linea)
    if linea.estado != EstadoLinea.lista:
        raise ErrorNegocio(f"El plato está '{linea.estado.value}': solo se entrega uno que ya está listo.")
    linea.estado = EstadoLinea.entregada
    linea.entregada_en = _ahora()
    db.flush()
    return linea


# ------------------------------------------------------------
# Pantallas
# ------------------------------------------------------------
def comandas_pendientes(db: Session, *, empresa_id: int, sucursal_id: int,
                        estacion: Optional[EstacionCocina] = None) -> list:
    """
    La pantalla de comandas: lo enviado y lo que se está preparando, lo más
    antiguo primero. Con `estacion` cada pantalla ve solo lo suyo.
    """
    validar_sucursal(db, empresa_id, sucursal_id)
    consulta = (db.query(LineaPedido).join(Pedido, LineaPedido.pedido_id == Pedido.id)
                .filter(LineaPedido.empresa_id == empresa_id, Pedido.sucursal_id == sucursal_id,
                        Pedido.estado.in_(_PEDIDOS_VIVOS),
                        LineaPedido.estado.in_((EstadoLinea.enviada, EstadoLinea.en_preparacion))))
    if estacion is not None:
        consulta = consulta.filter(LineaPedido.estacion == estacion.value)
    lineas = consulta.order_by(LineaPedido.enviada_en, LineaPedido.id).all()
    return [
        ComandaLinea(
            linea_id=l.id, pedido_id=l.pedido_id, mesa=l.pedido.mesa.nombre if l.pedido.mesa else "Mostrador",
            mesero_id=l.pedido.mesero_id, plato=l.item.nombre, cantidad=l.cantidad, estado=l.estado,
            comensal=l.comensal, nota=l.nota,
            sin=[db.get(Item, q.ingrediente_id).nombre for q in l.quitados],
            extras=[_nombre_extra(db, e.extra_id) for e in l.extras],
            enviada_en=l.enviada_en, receta_id=l.item.receta.id if l.item.receta else None)
        for l in lineas
    ]


def _nombre_extra(db: Session, extra_id: int) -> str:
    return db.get(Extra, extra_id).nombre


def retiros_pendientes(db: Session, *, empresa_id: int, sucursal_id: int,
                       mesero_id: Optional[int] = None) -> list:
    """Platos listos esperando retiro (la mesa encendida). Con `mesero_id`, solo los de sus mesas."""
    validar_sucursal(db, empresa_id, sucursal_id)
    consulta = (db.query(LineaPedido).join(Pedido, LineaPedido.pedido_id == Pedido.id)
                .filter(LineaPedido.empresa_id == empresa_id, Pedido.sucursal_id == sucursal_id,
                        Pedido.estado.in_(_PEDIDOS_VIVOS), LineaPedido.estado == EstadoLinea.lista))
    if mesero_id is not None:
        consulta = consulta.filter(Pedido.mesero_id == mesero_id)
    return [
        Retiro(linea_id=l.id, pedido_id=l.pedido_id, mesa=l.pedido.mesa.nombre if l.pedido.mesa else "Mostrador",
               plato=l.item.nombre, cantidad=l.cantidad, estacion=l.estacion, lista_en=l.lista_en)
        for l in consulta.order_by(LineaPedido.lista_en, LineaPedido.id).all()
    ]


# ------------------------------------------------------------
# Botón "se acabó"
# ------------------------------------------------------------
def marcar_agotado(db: Session, *, empresa_id: int, item_id: int, usuario_id: int) -> list:
    """
    El cocinero avisa que se acabó un ingrediente (o una bebida) aunque el sistema
    crea que hay. Devuelve los nombres de los platos que quedan agotados para el
    mesero por usarlo.
    """
    item = cargar_item(db, empresa_id, item_id)
    _cargar_personal_cocina(db, empresa_id, usuario_id)
    item.agotado_manual = True
    db.flush()
    nombres = {item.nombre} if item.es_vendible else set()
    nombres |= ({
        rl.receta.item.nombre
        for rl in db.query(RecetaLinea).filter_by(ingrediente_id=item.id).all()
        if rl.receta.item.empresa_id == empresa_id and rl.receta.item.es_vendible and rl.receta.item.activo
    })
    return sorted(nombres)


def reponer_agotado(db: Session, *, empresa_id: int, item_id: int, usuario_id: int) -> Item:
    """Quita la marca 'se acabó' (llegó mercadería o fue un error)."""
    item = cargar_item(db, empresa_id, item_id)
    _cargar_personal_cocina(db, empresa_id, usuario_id)
    item.agotado_manual = False
    db.flush()
    return item


def _cargar_personal_cocina(db: Session, empresa_id: int, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or usuario.empresa_id != empresa_id or not usuario.activo:
        raise ErrorNoEncontrado("El usuario no existe.")
    if not any(r.rol in ROLES_DE_COCINA for r in usuario.roles):
        raise ErrorNegocio(f"'{usuario.nombre}' no trabaja en cocina ni en barra.")
    return usuario
