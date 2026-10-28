# ============================================================
# YEPAR RESTAURANT — backend/servicios/reservas.py
# Reservar, consumir, liberar o mermar el stock de un pedido.
#
# Analogía: la comanda pega una etiqueta "RESERVADO" en cada
# ingrediente que usará el plato.
#   - Al ENVIAR a cocina: se pega la etiqueta (sube la reserva).
#   - Al marcar LISTO:    se retira la etiqueta y el ingrediente se
#                         descuenta de verdad del stock físico.
#   - Si se CANCELA antes de cocinar: solo se retira la etiqueta.
#   - Si se cancela YA EN PREPARACIÓN: el ingrediente se perdió, se
#                         descuenta y queda anotado como merma.
#
# Qué se descuenta: los ingredientes DIRECTOS de la receta del plato.
# Si el plato usa un componente (salsa de ajo) se descuenta la salsa,
# no la mayonesa con que se hizo: eso ya se descontó al producir el lote.
# Un "sin cebolla" no reserva la cebolla; un "extra tocineta" reserva
# la tocineta adicional.
#
# Faltar un ingrediente NO bloquea: la reserva se hace igual y se
# devuelven los `faltantes` para alertar al administrador.
# Los servicios no hacen commit (lo decide quien llama).
# ============================================================

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import (EstadoReserva, Extra, ExtraPlato, MotivoMerma, ReservaStock,
                    TipoItem, TipoMovimientoStock)
from servicios.stock import (aplicar_movimiento, cargar_item, obtener_stock,
                             validar_sucursal)
from unidades import a_decimal, redondear_cantidad

REFERENCIA_LINEA_PEDIDO = "linea_pedido"


@dataclass
class Faltante:
    """Un ingrediente que no alcanza para lo reservado."""
    item_id: int
    nombre: str
    falta: Decimal            # cuánto falta, en unidad base


@dataclass
class ResultadoReserva:
    reservas: list = field(default_factory=list)       # ReservaStock creadas
    faltantes: list = field(default_factory=list)      # lista de Faltante


# ------------------------------------------------------------
# Qué necesita una línea de pedido
# ------------------------------------------------------------
def calcular_necesidad(
    db: Session, *,
    empresa_id: int,
    item_id: int,
    cantidad=1,
    sin_ingredientes: Iterable[int] = (),
    extra_ids: Iterable[int] = (),
) -> dict:
    """
    Devuelve {ingrediente_id: cantidad_base} que consume `cantidad` unidades
    del plato, ya descontando lo que el cliente pidió quitar y sumando extras.
    """
    item = cargar_item(db, empresa_id, item_id)
    unidades = a_decimal(cantidad)
    if unidades <= 0:
        raise ErrorNegocio("La cantidad pedida debe ser mayor que cero.")
    if not item.es_vendible:
        raise ErrorNegocio(f"'{item.nombre}' no se vende: no puede ir en un pedido.")

    necesidad: dict = {}
    quitados = set(sin_ingredientes)
    receta = item.receta

    if receta is None:
        if item.tipo != TipoItem.vendible_reventa:
            raise ErrorNegocio(f"'{item.nombre}' no tiene receta.")
        if quitados:
            raise ErrorNegocio(f"'{item.nombre}' no tiene ingredientes que quitar.")
        necesidad[item.id] = unidades                      # una lata de cola descuenta la lata
    else:
        invalidos = quitados - {l.ingrediente_id for l in receta.lineas if l.es_removible}
        if invalidos:
            raise ErrorNegocio(f"No se pueden quitar de '{item.nombre}' ingredientes que no son removibles.")
        for linea in receta.lineas:
            if linea.ingrediente_id in quitados:
                continue
            necesidad[linea.ingrediente_id] = (necesidad.get(linea.ingrediente_id, Decimal("0"))
                                               + linea.cantidad / receta.rendimiento * unidades)

    for extra_id in extra_ids:
        extra = db.get(Extra, extra_id)
        if extra is None or extra.empresa_id != empresa_id or not extra.activo:
            raise ErrorNegocio("El extra pedido no existe.")
        if not extra.aplica_a_todos and db.get(ExtraPlato, (extra.id, item.id)) is None:
            raise ErrorNegocio(f"El extra '{extra.nombre}' no se ofrece en '{item.nombre}'.")
        necesidad[extra.ingrediente_id] = (necesidad.get(extra.ingrediente_id, Decimal("0"))
                                           + extra.cantidad * unidades)

    return {k: redondear_cantidad(v) for k, v in necesidad.items() if redondear_cantidad(v) > 0}


# ------------------------------------------------------------
# Reservar al enviar a cocina
# ------------------------------------------------------------
def reservar_linea(
    db: Session, *,
    empresa_id: int,
    sucursal_id: int,
    referencia_id,
    item_id: int,
    cantidad=1,
    sin_ingredientes: Iterable[int] = (),
    extra_ids: Iterable[int] = (),
    referencia_tipo: str = REFERENCIA_LINEA_PEDIDO,
) -> ResultadoReserva:
    """Aparta los ingredientes de una línea de pedido. No bloquea si falta stock."""
    validar_sucursal(db, empresa_id, sucursal_id)
    if _reservas(db, empresa_id, referencia_tipo, referencia_id, None):    # en cualquier estado
        raise ErrorNegocio("Esta línea ya tiene reservas: no se puede reservar dos veces.")

    necesidad = calcular_necesidad(db, empresa_id=empresa_id, item_id=item_id, cantidad=cantidad,
                                   sin_ingredientes=sin_ingredientes, extra_ids=extra_ids)
    resultado = ResultadoReserva()
    for ingrediente_id, cant in necesidad.items():
        stock = obtener_stock(db, empresa_id, ingrediente_id, sucursal_id)
        stock.cantidad_reservada = (stock.cantidad_reservada or Decimal("0")) + cant
        resultado.reservas.append(ReservaStock(
            empresa_id=empresa_id, sucursal_id=sucursal_id, item_id=ingrediente_id,
            referencia_tipo=referencia_tipo, referencia_id=str(referencia_id),
            cantidad=cant, estado=EstadoReserva.activa))
        if stock.disponible < 0:
            resultado.faltantes.append(Faltante(
                item_id=ingrediente_id, nombre=stock.item.nombre, falta=-stock.disponible))
    db.add_all(resultado.reservas)
    db.flush()
    return resultado


# ------------------------------------------------------------
# Cerrar la reserva: consumir, liberar o mermar
# ------------------------------------------------------------
def _reservas(db, empresa_id, referencia_tipo, referencia_id, estado):
    consulta = db.query(ReservaStock).filter_by(
        empresa_id=empresa_id, referencia_tipo=referencia_tipo, referencia_id=str(referencia_id))
    if estado is not None:
        consulta = consulta.filter_by(estado=estado)
    return consulta.all()


def _activas(db, empresa_id, referencia_tipo, referencia_id):
    activas = _reservas(db, empresa_id, referencia_tipo, referencia_id, EstadoReserva.activa)
    if not activas:
        raise ErrorNegocio("No hay reservas activas para esta línea (¿ya se cerró o nunca se envió?).")
    return activas


def _cerrar(db, reserva: ReservaStock, estado: EstadoReserva, *, tipo_movimiento=None,
            motivo=None, usuario_id=None):
    """Retira la etiqueta 'reservado' y, si corresponde, descuenta el stock físico."""
    stock = obtener_stock(db, reserva.empresa_id, reserva.item_id, reserva.sucursal_id)
    stock.cantidad_reservada = (stock.cantidad_reservada or Decimal("0")) - reserva.cantidad
    if tipo_movimiento is not None:
        aplicar_movimiento(
            db, stock=stock, tipo=tipo_movimiento, cantidad=-reserva.cantidad,
            costo_unitario=stock.item.costo_referencia, motivo_merma=motivo, usuario_id=usuario_id,
            referencia_tipo=reserva.referencia_tipo, referencia_id=reserva.referencia_id)
    reserva.estado = estado
    reserva.cerrado_en = datetime.now(timezone.utc)


def consumir_reserva(db: Session, *, empresa_id: int, referencia_id, usuario_id: Optional[int] = None,
                     referencia_tipo: str = REFERENCIA_LINEA_PEDIDO) -> list:
    """Cocina marcó 'listo': los ingredientes salen del stock físico (consumo por venta)."""
    activas = _activas(db, empresa_id, referencia_tipo, referencia_id)
    for r in activas:
        _cerrar(db, r, EstadoReserva.consumida, tipo_movimiento=TipoMovimientoStock.consumo_venta,
                usuario_id=usuario_id)
    db.flush()
    return activas


def liberar_reserva(db: Session, *, empresa_id: int, referencia_id,
                    referencia_tipo: str = REFERENCIA_LINEA_PEDIDO) -> list:
    """Se canceló antes de cocinar: el stock queda como estaba, solo se quita la reserva."""
    activas = _activas(db, empresa_id, referencia_tipo, referencia_id)
    for r in activas:
        _cerrar(db, r, EstadoReserva.liberada)
    db.flush()
    return activas


def mermar_reserva(db: Session, *, empresa_id: int, referencia_id, usuario_id: Optional[int] = None,
                   referencia_tipo: str = REFERENCIA_LINEA_PEDIDO) -> list:
    """Se canceló ya en preparación: lo cocinado se perdió → descuento + merma anotada."""
    activas = _activas(db, empresa_id, referencia_tipo, referencia_id)
    for r in activas:
        _cerrar(db, r, EstadoReserva.merma, tipo_movimiento=TipoMovimientoStock.merma,
                motivo=MotivoMerma.cancelacion_en_preparacion, usuario_id=usuario_id)
    db.flush()
    return activas
