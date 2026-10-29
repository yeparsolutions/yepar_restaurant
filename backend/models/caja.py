# ============================================================
# YEPAR RESTAURANT — backend/models/caja.py
# CAJA Y COBRO: cajas, turnos, terminales de tarjeta y pagos.
#
# Analogía: la caja registradora. El cajero "abre turno" con un fondo
# (el cambio con que parte), cobra durante el día y al cerrar cuenta
# lo que hay: si no calza con lo esperado, debe explicar la diferencia.
# (Misma idea que las cajas de YeparStock/Carora, pero con dinero
# exacto —Numeric— en vez de decimales flotantes.)
#
# REGLAS:
#  - El efectivo se cobra SOLO en caja, dentro de un turno abierto.
#  - La tarjeta se cobra en la mesa con un terminal portátil: exige
#    terminal y número de operación (para el cuadre por terminal).
#  - Un pedido puede pagarse en varias partes (cuenta dividida o
#    pago mixto): se cierra cuando lo pagado cubre el total.
#  - Pagos con UUID: la tablet los crea sin conexión y se sincronizan.
# ============================================================

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, Index, Numeric, String,
                        UniqueConstraint, func, text, true)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.enums import EstadoTurno, MedioPago, ModoPropina, columna_enum

DINERO = Numeric(16, 2)
_TURNO_ABIERTO = "estado = 'abierto'"


def nuevo_uuid() -> str:
    return str(uuid.uuid4())


class ConfiguracionCobro(Base):
    """Opciones de cobro de cada restaurante (la app es para terceros: cada uno decide)."""
    __tablename__ = "configuracion_cobro"
    __table_args__ = (CheckConstraint("propina_sugerida_pct >= 0 AND propina_sugerida_pct <= 100",
                                      name="ck_config_propina_pct"),)

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), primary_key=True)
    propina_modo: Mapped[ModoPropina] = mapped_column(columna_enum(ModoPropina), default=ModoPropina.por_mesa)
    propina_sugerida_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10"), server_default="10")


class Caja(Base):
    __tablename__ = "cajas"
    __table_args__ = (UniqueConstraint("sucursal_id", "nombre", name="uq_caja_sucursal_nombre"),)

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    nombre:      Mapped[str] = mapped_column(String(60))
    activa:      Mapped[bool] = mapped_column(default=True, server_default=true())


class TurnoCaja(Base):
    __tablename__ = "turnos_caja"
    __table_args__ = (
        # Una caja no puede tener dos turnos abiertos, ni un cajero estar en dos cajas a la vez.
        Index("uq_turno_caja_abierto", "caja_id", unique=True,
              postgresql_where=text(_TURNO_ABIERTO), sqlite_where=text(_TURNO_ABIERTO)),
        Index("uq_turno_usuario_abierto", "usuario_id", unique=True,
              postgresql_where=text(_TURNO_ABIERTO), sqlite_where=text(_TURNO_ABIERTO)),
        CheckConstraint("fondo >= 0", name="ck_turno_fondo_no_negativo"),
    )

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    caja_id:     Mapped[int] = mapped_column(ForeignKey("cajas.id"), index=True)
    usuario_id:  Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)     # el cajero del turno

    estado:    Mapped[EstadoTurno] = mapped_column(columna_enum(EstadoTurno), default=EstadoTurno.abierto)
    abierto_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fondo:     Mapped[Decimal] = mapped_column(DINERO, default=Decimal("0"))          # con cuánto partió

    cerrado_en:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cerrado_por_id: Mapped[Optional[int]]   = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    esperado:    Mapped[Optional[Decimal]]  = mapped_column(DINERO)     # fondo + efectivo cobrado
    contado:     Mapped[Optional[Decimal]]  = mapped_column(DINERO)     # lo que el cajero contó
    diferencia:  Mapped[Optional[Decimal]]  = mapped_column(DINERO)     # contado − esperado (negativo = faltante)
    nota:        Mapped[Optional[str]]      = mapped_column(String(300))
    revisado_por_id: Mapped[Optional[int]]  = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    revisado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    caja: Mapped["Caja"] = relationship()


class TerminalPago(Base):
    """Un terminal portátil de tarjeta (el que lleva el mesero a la mesa)."""
    __tablename__ = "terminales_pago"
    __table_args__ = (UniqueConstraint("sucursal_id", "nombre", name="uq_terminal_sucursal_nombre"),)

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    nombre:      Mapped[str] = mapped_column(String(60))
    activo:      Mapped[bool] = mapped_column(default=True, server_default=true())


class Pago(Base):
    __tablename__ = "pagos"
    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_pago_monto_positivo"),
        # Un mismo número de operación no puede repetirse en el mismo terminal.
        UniqueConstraint("terminal_id", "numero_operacion", name="uq_pago_terminal_operacion"),
        Index("ix_pago_pedido", "pedido_id"),
    )

    id:          Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_uuid)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    pedido_id:   Mapped[str] = mapped_column(ForeignKey("pedidos.id"))

    medio: Mapped[MedioPago] = mapped_column(columna_enum(MedioPago))
    monto: Mapped[Decimal]   = mapped_column(DINERO)                        # lo que abonó a la cuenta
    recibido: Mapped[Optional[Decimal]] = mapped_column(DINERO)             # efectivo: con cuánto pagó el cliente (monto + vuelto)

    numero_operacion: Mapped[Optional[str]] = mapped_column(String(60))
    terminal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("terminales_pago.id"), index=True)
    turno_id:    Mapped[Optional[int]] = mapped_column(ForeignKey("turnos_caja.id"), index=True)   # solo efectivo
    usuario_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    creado_en:   Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def vuelto(self) -> Decimal:
        return (self.recibido - self.monto) if self.recibido is not None else Decimal("0")
