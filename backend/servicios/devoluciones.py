# ============================================================
# YEPAR RESTAURANT — backend/servicios/devoluciones.py
# Devolver dinero al cliente de una cuenta ya cobrada.
#
# Analogía: el mostrador de devoluciones. El cliente trae su comprobante; el supervisor da el visto
# bueno con su PIN; el dinero vuelve por el mismo camino por el que entró (el efectivo sale del cajón,
# la tarjeta o la transferencia se devuelven por su canal) y queda anotado quién, cuánto y por qué.
#
# REGLAS:
#  - Solo de cuentas CERRADAS (ya cobradas).
#  - Por medio: no se devuelve más de lo que entró por ese medio (menos lo ya devuelto).
#  - Siempre con motivo. El cajero necesita el PIN de un supervisor; el administrador no.
#  - Efectivo: el cajón debe estar a cargo de quien devuelve (turno abierto): baja el arqueo del turno.
# ============================================================

from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import Devolucion, EstadoPedido, MedioPago, Pago, RolUsuario
from servicios.caja import _dinero, cargar_usuario, tiene_rol, turno_abierto_de
from servicios.pedidos import cargar_pedido
from servicios.supervisor import autorizar

CENTAVO = Decimal("0.01")
CERO = Decimal("0")


def _suma(db: Session, modelo, pedido_id: str, medio: MedioPago) -> Decimal:
    total = db.query(func.coalesce(func.sum(modelo.monto), 0)).filter(
        modelo.pedido_id == pedido_id, modelo.medio == medio).scalar()
    return Decimal(total).quantize(CENTAVO)


def devuelto_por_medio(db: Session, pedido_id: str) -> dict:
    return {m.value: _suma(db, Devolucion, pedido_id, m) for m in MedioPago}


def pagado_por_medio(db: Session, pedido_id: str) -> dict:
    return {m.value: _suma(db, Pago, pedido_id, m) for m in MedioPago}


def listar(db: Session, *, empresa_id: int, pedido_id: str) -> list:
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    return (db.query(Devolucion).filter_by(pedido_id=pedido.id).order_by(Devolucion.creado_en, Devolucion.id).all())


def devolver(db: Session, *, empresa_id: int, pedido_id: str, usuario_id: int, medio: MedioPago, monto, motivo: str,
             numero_operacion: Optional[str] = None, supervisor_id: Optional[int] = None,
             pin_supervisor: Optional[str] = None) -> Devolucion:
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    if pedido.estado != EstadoPedido.cerrado:
        raise ErrorNegocio("Solo se devuelve dinero de una cuenta ya cobrada.")
    usuario = cargar_usuario(db, empresa_id, usuario_id)
    es_admin = tiene_rol(usuario, RolUsuario.administrador)
    if not es_admin and not tiene_rol(usuario, RolUsuario.cajero):
        raise ErrorNegocio(f"'{usuario.nombre}' no puede hacer devoluciones.")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErrorNegocio("Indica el motivo de la devolución.")
    monto = _dinero(monto, "El monto")
    if monto <= 0:
        raise ErrorNegocio("El monto de la devolución debe ser mayor que cero.")

    disponible = _suma(db, Pago, pedido.id, medio) - _suma(db, Devolucion, pedido.id, medio)
    if monto > disponible:
        raise ErrorNegocio(f"No se puede devolver {monto} por {medio.value}: de ese medio quedan {disponible} por devolver.")

    autorizador = None
    if not es_admin:
        if supervisor_id is None or not pin_supervisor:
            raise ErrorNegocio("Una devolución necesita el PIN de un supervisor.")
        autorizador = autorizar(db, empresa_id=empresa_id, supervisor_id=supervisor_id, pin=pin_supervisor)

    dev = Devolucion(empresa_id=empresa_id, sucursal_id=pedido.sucursal_id, pedido_id=pedido.id, medio=medio,
                     monto=monto, motivo=motivo[:200], usuario_id=usuario.id,
                     autorizado_por_id=autorizador.id if autorizador is not None else None)
    if medio == MedioPago.efectivo:
        turno = turno_abierto_de(db, usuario.id)
        if turno is None:
            raise ErrorNegocio("Para devolver efectivo hay que tener el turno de caja abierto: el dinero sale del cajón.")
        dev.turno_id = turno.id
    else:
        operacion = (numero_operacion or "").strip()
        if not operacion:
            raise ErrorNegocio("Indica el número de operación de la devolución por tarjeta o transferencia.")
        dev.numero_operacion = operacion[:60]
        if medio == MedioPago.tarjeta:
            # La devolución sale por el mismo terminal por el que se cobró (para el cuadre del terminal).
            ultimo = (db.query(Pago).filter(Pago.pedido_id == pedido.id, Pago.medio == MedioPago.tarjeta)
                      .order_by(Pago.creado_en.desc()).first())
            dev.terminal_id = ultimo.terminal_id if ultimo is not None else None
    db.add(dev)
    db.flush()
    return dev
