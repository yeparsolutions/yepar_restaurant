# ============================================================
# YEPAR RESTAURANT — backend/models/despacho.py
# Delivery con Yepar Go: con qué cuenta despacha cada restaurante y la
# orden de entrega que sale de una cuenta.
#
# Analogía: IntegracionDespacho es el contrato con la empresa de reparto
# (la llave con la que se le piden motoristas); Despacho es el "talón de
# encargo" de una cuenta: a quién se lleva, adónde, y el link para seguirlo.
# ============================================================

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.enums import EstadoDespacho, columna_enum


class IntegracionDespacho(Base):
    """La cuenta de Yepar Go del restaurante. Una por empresa (la API Key va CIFRADA)."""
    __tablename__ = "integraciones_despacho"

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), primary_key=True)
    api_key_cifrada: Mapped[str] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Dónde retira el motorista (el local). Yepar Go solo geocodifica el destino.
    direccion_retiro: Mapped[Optional[str]] = mapped_column(String(300))
    centro_retiro_id: Mapped[Optional[str]] = mapped_column(String(40))     # UUID de un centro de retiro de Yepar Go
    actualizado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class Despacho(Base):
    __tablename__ = "despachos"
    __table_args__ = (UniqueConstraint("pedido_id", name="uq_despacho_pedido"),)   # una cuenta, un despacho

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    pedido_id:   Mapped[str] = mapped_column(ForeignKey("pedidos.id"))
    estado: Mapped[EstadoDespacho] = mapped_column(columna_enum(EstadoDespacho), default=EstadoDespacho.pendiente)

    # A quién y adónde.
    destinatario: Mapped[str] = mapped_column(String(150))
    telefono:     Mapped[Optional[str]] = mapped_column(String(40))
    email:        Mapped[Optional[str]] = mapped_column(String(150))
    direccion:    Mapped[str] = mapped_column(String(300))
    ciudad:       Mapped[Optional[str]] = mapped_column(String(100))
    region:       Mapped[Optional[str]] = mapped_column(String(100))
    latitud:      Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    longitud:     Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    notas:        Mapped[Optional[str]] = mapped_column(Text)

    # Lo que devuelve Yepar Go.
    go_orden_id:  Mapped[Optional[str]] = mapped_column(String(40))
    go_numero:    Mapped[Optional[str]] = mapped_column(String(40))
    estado_go:    Mapped[Optional[str]] = mapped_column(String(20))   # pending|assigned|in_route|delivered|failed|rescheduled|cancelled
    seguimiento_url: Mapped[Optional[str]] = mapped_column(String(500))

    intentos:     Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ultimo_error: Mapped[Optional[str]] = mapped_column(Text)
    creado_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    creado_en:    Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())
