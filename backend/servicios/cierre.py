# ============================================================
# YEPAR RESTAURANT — backend/servicios/cierre.py
# Cuadre por terminal de tarjeta y resumen del día.
#
# Analogía: al final del día se comparan dos cuadernos: el nuestro
# (los pagos que registramos) contra el del terminal de tarjetas (el
# comprobante de cierre del banco). Si no calzan, hay un pago mal anotado.
#
# Los rangos de fecha los define quien llama (cada local decide cuándo
# empieza su "día"), así no dependemos de zonas horarias aquí.
# Todo es de solo lectura.
# ============================================================

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import (EstadoPedido, EstadoTurno, MedioPago, Pago, Pedido, TerminalPago,
                    TurnoCaja)
from servicios.cobro import calcular_cuenta
from servicios.stock import validar_sucursal

CENTAVO = Decimal("0.01")
CERO = Decimal("0")


@dataclass
class CuadreTerminal:
    terminal_id: int
    nombre: str
    cantidad: int
    total_registrado: Decimal               # lo que anotamos nosotros
    total_reportado: Optional[Decimal] = None   # lo que dice el cierre del terminal
    diferencia: Optional[Decimal] = None        # reportado − registrado (negativo = nos falta anotar)
    operaciones: list = field(default_factory=list)   # [(numero_operacion, monto)]


@dataclass
class ResumenDia:
    cerradas: int                           # mesas cobradas en el período
    ventas: Decimal                         # suma de subtotales
    descuentos: Decimal
    propinas: Decimal
    total_cobrado: Decimal                  # ventas − descuentos + propinas
    por_medio: dict = field(default_factory=dict)      # {"efectivo": monto, "tarjeta": ..., ...}
    turnos_con_diferencia: list = field(default_factory=list)   # [(turno_id, diferencia)]


def cuadre_terminal(db: Session, *, empresa_id: int, terminal_id: int, desde: datetime, hasta: datetime,
                    reportado=None) -> CuadreTerminal:
    """
    Suma lo registrado con ese terminal entre `desde` y `hasta` y, si se entrega el total
    del comprobante del terminal (`reportado`), calcula la diferencia.
    """
    terminal = db.get(TerminalPago, terminal_id)
    if terminal is None or terminal.empresa_id != empresa_id:
        raise ErrorNoEncontrado("El terminal no existe.")
    pagos = (db.query(Pago).filter(Pago.terminal_id == terminal.id, Pago.medio == MedioPago.tarjeta,
                                   Pago.creado_en >= desde, Pago.creado_en < hasta)
             .order_by(Pago.creado_en, Pago.numero_operacion).all())
    total = sum((p.monto for p in pagos), CERO).quantize(CENTAVO)
    cuadre = CuadreTerminal(terminal_id=terminal.id, nombre=terminal.nombre, cantidad=len(pagos),
                            total_registrado=total,
                            operaciones=[(p.numero_operacion, p.monto) for p in pagos])
    if reportado is not None:
        cuadre.total_reportado = Decimal(str(reportado)).quantize(CENTAVO)
        cuadre.diferencia = cuadre.total_reportado - total
    return cuadre


def resumen_periodo(db: Session, *, empresa_id: int, sucursal_id: int, desde: datetime,
                    hasta: datetime) -> ResumenDia:
    """Lo vendido y cobrado entre `desde` y `hasta` en un local (mesas cerradas en ese rango)."""
    validar_sucursal(db, empresa_id, sucursal_id)
    pedidos = (db.query(Pedido).filter(Pedido.empresa_id == empresa_id, Pedido.sucursal_id == sucursal_id,
                                       Pedido.estado == EstadoPedido.cerrado,
                                       Pedido.cerrado_en >= desde, Pedido.cerrado_en < hasta).all())
    resumen = ResumenDia(cerradas=len(pedidos), ventas=CERO, descuentos=CERO, propinas=CERO, total_cobrado=CERO)
    for pedido in pedidos:
        cuenta = calcular_cuenta(db, empresa_id=empresa_id, pedido_id=pedido.id)
        resumen.ventas += cuenta.subtotal
        resumen.descuentos += cuenta.descuento
        resumen.propinas += cuenta.propina
    resumen.total_cobrado = resumen.ventas - resumen.descuentos + resumen.propinas

    por_medio = (db.query(Pago.medio, func.sum(Pago.monto))
                 .join(Pedido, Pago.pedido_id == Pedido.id)
                 .filter(Pago.empresa_id == empresa_id, Pago.sucursal_id == sucursal_id,
                         Pago.creado_en >= desde, Pago.creado_en < hasta)
                 .group_by(Pago.medio).all())
    resumen.por_medio = {medio.value: Decimal(total).quantize(CENTAVO) for medio, total in por_medio}

    turnos = (db.query(TurnoCaja).filter(TurnoCaja.empresa_id == empresa_id, TurnoCaja.sucursal_id == sucursal_id,
                                         TurnoCaja.estado == EstadoTurno.cerrado,
                                         TurnoCaja.cerrado_en >= desde, TurnoCaja.cerrado_en < hasta,
                                         TurnoCaja.diferencia != 0).order_by(TurnoCaja.cerrado_en).all())
    resumen.turnos_con_diferencia = [(t.id, t.diferencia) for t in turnos]
    return resumen
