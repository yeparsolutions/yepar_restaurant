# ============================================================
# YEPAR RESTAURANT — backend/servicios/cobro.py
# La cuenta de una mesa: descuento, propina y pagos.
#
# Analogía: la cuenta en la mesa. El mesero la pide y anota la
# propina; el cajero aplica el descuento permitido y cobra. La
# tarjeta se pasa en la misma mesa (terminal portátil); el
# efectivo se paga en la caja, porque el mesero no carga plata.
# Un pedido puede pagarse en partes (pago mixto o cuenta dividida);
# se cierra cuando lo pagado cubre el total.
#
# Los servicios no hacen commit (lo decide quien llama).
# ============================================================

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import (ConfiguracionCobro, EstadoLinea, EstadoPedido, MedioPago, ModoPropina,
                    Pago, Pedido, RolUsuario, TerminalPago)
from servicios.caja import _dinero, cargar_usuario, tiene_rol, turno_abierto_de
from servicios.pedidos import cargar_pedido
from servicios.propinas import registrar_propina_de_pedido
from servicios.supervisor import autorizar

CERO = Decimal("0")
CENTAVO = Decimal("0.01")
_ROLES_DE_COBRO = (RolUsuario.cajero, RolUsuario.administrador, RolUsuario.mesero)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Cuenta:
    subtotal: Decimal       # platos no cancelados, con extras (quitar ingredientes no baja el precio)
    descuento: Decimal
    propina: Decimal
    total: Decimal          # subtotal − descuento + propina
    pagado: Decimal
    pendiente: Decimal      # total − pagado


def obtener_configuracion(db: Session, empresa_id: int) -> ConfiguracionCobro:
    """La configuración de cobro del restaurante (se crea con valores por defecto la primera vez)."""
    config = db.get(ConfiguracionCobro, empresa_id)
    if config is None:
        config = ConfiguracionCobro(empresa_id=empresa_id, propina_modo=ModoPropina.por_mesa,
                                    propina_sugerida_pct=Decimal("10"))
        db.add(config)
        db.flush()
    return config


def configurar_cobro(db: Session, *, empresa_id: int, propina_modo: Optional[ModoPropina] = None,
                     propina_sugerida_pct=None) -> ConfiguracionCobro:
    config = obtener_configuracion(db, empresa_id)
    if propina_modo is not None:
        config.propina_modo = propina_modo
    if propina_sugerida_pct is not None:
        pct = _dinero(propina_sugerida_pct, "El porcentaje de propina")
        if not (0 <= pct <= 100):
            raise ErrorNegocio("El porcentaje de propina debe estar entre 0 y 100.")
        config.propina_sugerida_pct = pct
    db.flush()
    return config


def _subtotal(pedido: Pedido) -> Decimal:
    return sum((l.total for l in pedido.lineas if l.estado != EstadoLinea.cancelada), CERO)


def _pagado(db: Session, pedido_id: str) -> Decimal:
    total = db.query(func.coalesce(func.sum(Pago.monto), 0)).filter(Pago.pedido_id == pedido_id).scalar()
    return Decimal(total).quantize(CENTAVO)


def calcular_cuenta(db: Session, *, empresa_id: int, pedido_id: str) -> Cuenta:
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    subtotal = _subtotal(pedido).quantize(CENTAVO)
    total = subtotal - pedido.descuento + pedido.propina
    pagado = _pagado(db, pedido.id)
    return Cuenta(subtotal=subtotal, descuento=pedido.descuento, propina=pedido.propina,
                  total=total, pagado=pagado, pendiente=total - pagado)


def _exigir_cuenta_pedida(pedido: Pedido):
    if pedido.estado == EstadoPedido.cerrado:
        raise ErrorNegocio("La cuenta ya está pagada y cerrada.")
    if pedido.estado != EstadoPedido.cuenta_pedida:
        raise ErrorNegocio("Primero hay que pedir la cuenta de la mesa.")


def _exigir_sin_pagos(db: Session, pedido: Pedido, que: str):
    if _pagado(db, pedido.id) > 0:
        raise ErrorNegocio(f"La cuenta ya tiene pagos: no se puede cambiar {que}.")


# ------------------------------------------------------------
# Propina y descuento
# ------------------------------------------------------------
def anotar_propina(db: Session, *, empresa_id: int, pedido_id: str, monto=None) -> Pedido:
    """
    El mesero anota la propina al pedir la cuenta. Sin monto se usa la sugerida
    del restaurante (por defecto 10% de lo que se cobra, ya con descuento).
    """
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    _exigir_cuenta_pedida(pedido)
    _exigir_sin_pagos(db, pedido, "la propina")
    if monto is None:
        pct = obtener_configuracion(db, empresa_id).propina_sugerida_pct
        base = _subtotal(pedido) - pedido.descuento
        propina = (base * pct / 100).quantize(CENTAVO)
    else:
        propina = _dinero(monto, "La propina")
    if propina < 0:
        raise ErrorNegocio("La propina no puede ser negativa.")
    pedido.propina = propina
    db.flush()
    return pedido


def aplicar_descuento(db: Session, *, empresa_id: int, pedido_id: str, usuario_id: int, porcentaje,
                      supervisor_id: Optional[int] = None, pin_supervisor: Optional[str] = None) -> Pedido:
    """
    El cajero aplica un descuento en % sobre el subtotal, hasta su tope personal
    (`descuento_max_pct`). El administrador no tiene tope. Para pasarse del tope el
    cajero pide a un supervisor que teclee su PIN (`supervisor_id` + `pin_supervisor`):
    el descuento queda anotado con quién lo autorizó.
    """
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    _exigir_cuenta_pedida(pedido)
    _exigir_sin_pagos(db, pedido, "el descuento")
    usuario = cargar_usuario(db, empresa_id, usuario_id)
    if not tiene_rol(usuario, RolUsuario.cajero, RolUsuario.administrador):
        raise ErrorNegocio(f"'{usuario.nombre}' no puede dar descuentos.")
    pct = _dinero(porcentaje, "El descuento")
    if not (0 <= pct < 100):
        raise ErrorNegocio("El descuento debe ser un porcentaje entre 0 y menos de 100.")
    es_admin = tiene_rol(usuario, RolUsuario.administrador)
    autorizador = None
    if not es_admin and pct > usuario.descuento_max_pct:
        if supervisor_id is None or not pin_supervisor:
            raise ErrorNegocio(f"El descuento excede el tope de '{usuario.nombre}' ({usuario.descuento_max_pct}%): "
                               "pide el PIN de un supervisor.")
        autorizador = autorizar(db, empresa_id=empresa_id, supervisor_id=supervisor_id, pin=pin_supervisor)
    pedido.descuento = (_subtotal(pedido) * pct / 100).quantize(CENTAVO)
    pedido.descuento_por_id = usuario.id if pct > 0 else None
    pedido.descuento_autorizado_por_id = autorizador.id if autorizador is not None else None
    db.flush()
    return pedido


# ------------------------------------------------------------
# Pagos
# ------------------------------------------------------------
def registrar_pago(
    db: Session, *,
    empresa_id: int,
    pedido_id: str,
    usuario_id: int,
    medio: MedioPago,
    monto,
    recibido=None,
    numero_operacion: Optional[str] = None,
    terminal_id: Optional[int] = None,
    pago_id: Optional[str] = None,
) -> Pago:
    """
    Registra un pago (total o parcial). Reglas:
      - efectivo: solo cajero/administrador, con turno abierto; `recibido` es lo que entregó el
        cliente (el vuelto = recibido − monto); el mesero no maneja efectivo.
      - tarjeta: terminal y número de operación obligatorios (para el cuadre por terminal).
      - transferencia: número de operación obligatorio.
      - nadie puede pagar más de lo pendiente (el efectivo da vuelto, lo demás no).
    Cuando lo pagado cubre el total, la mesa queda cerrada.
    """
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    _exigir_cuenta_pedida(pedido)
    if any(l.estado in (EstadoLinea.enviada, EstadoLinea.en_preparacion) for l in pedido.lineas):
        raise ErrorNegocio("Hay platos que cocina aún no termina: espera o cancélalos antes de cobrar.")
    if pago_id is not None and db.get(Pago, pago_id) is not None:
        raise ErrorNegocio("Ese pago ya existe (¿se sincronizó dos veces?).")

    usuario = cargar_usuario(db, empresa_id, usuario_id)
    if not tiene_rol(usuario, *_ROLES_DE_COBRO):
        raise ErrorNegocio(f"'{usuario.nombre}' no puede registrar pagos.")
    monto = _dinero(monto, "El monto")
    if monto <= 0:
        raise ErrorNegocio("El monto del pago debe ser mayor que cero.")
    cuenta = calcular_cuenta(db, empresa_id=empresa_id, pedido_id=pedido.id)
    if monto > cuenta.pendiente:
        raise ErrorNegocio(f"El pago ({monto}) supera lo pendiente de la cuenta ({cuenta.pendiente}).")

    pago = Pago(empresa_id=empresa_id, sucursal_id=pedido.sucursal_id, pedido_id=pedido.id, medio=medio,
                monto=monto, usuario_id=usuario.id)
    if medio == MedioPago.efectivo:
        if not tiene_rol(usuario, RolUsuario.cajero, RolUsuario.administrador):
            raise ErrorNegocio("El efectivo se cobra en la caja: el mesero no maneja efectivo.")
        turno = turno_abierto_de(db, usuario.id)
        if turno is None:
            raise ErrorNegocio("Para cobrar en efectivo hay que abrir turno de caja.")
        pago.turno_id = turno.id
        pago.recibido = monto if recibido is None else _dinero(recibido, "Lo recibido")
        if pago.recibido < monto:
            raise ErrorNegocio("Lo recibido no alcanza para el monto a cobrar.")
    else:
        if recibido is not None:
            raise ErrorNegocio("Solo el efectivo lleva 'recibido' y vuelto.")
        operacion = (numero_operacion or "").strip()
        if not operacion:
            raise ErrorNegocio("El número de operación es obligatorio para pagos con tarjeta o transferencia.")
        pago.numero_operacion = operacion
        if medio == MedioPago.tarjeta:
            terminal = db.get(TerminalPago, terminal_id) if terminal_id is not None else None
            if terminal is None or terminal.empresa_id != empresa_id or terminal.sucursal_id != pedido.sucursal_id \
                    or not terminal.activo:
                raise ErrorNegocio("El pago con tarjeta necesita un terminal válido de este local.")
            if db.query(Pago).filter_by(terminal_id=terminal.id, numero_operacion=operacion).first() is not None:
                raise ErrorNegocio("Ese número de operación ya se registró en este terminal.")
            pago.terminal_id = terminal.id
    if pago_id is not None:
        pago.id = pago_id
    db.add(pago)
    db.flush()

    if cuenta.pendiente - monto == 0:
        pedido.estado = EstadoPedido.cerrado
        pedido.cerrado_en = _ahora()
        registrar_propina_de_pedido(db, pedido, obtener_configuracion(db, empresa_id).propina_modo)
        db.flush()
    return pago
