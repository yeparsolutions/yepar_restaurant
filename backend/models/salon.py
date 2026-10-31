# ============================================================
# YEPAR RESTAURANT — backend/models/salon.py
# EL SALÓN: mesas, pedidos y los platos de cada pedido.
#
# Analogía: la mesa es el "puesto" físico; el pedido es la
# "cuenta abierta" de esa visita; cada línea es un renglón de la
# comanda que viaja por estados: anotado → enviado → en
# preparación → listo → entregado.
#
# REGLAS DE DISEÑO:
#  - Modo sin conexión: pedidos y líneas usan IDs UUID (texto) que se
#    generan EN LA TABLET, así se pueden crear sin red y sincronizar
#    después sin choques de numeración.
#  - Todo lleva empresa_id (multi-cliente). Una mesa pertenece a una
#    sucursal; nunca se mezclan mesas entre clientes ni entre locales.
#  - El precio se COPIA a la línea al tomarla: si mañana sube la carta,
#    la cuenta de hoy no cambia.
#  - Quitar un ingrediente ("sin cebolla") no cambia el precio; los
#    extras se cobran aparte (se copia su precio).
# ============================================================

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        Numeric, String, UniqueConstraint, func, text, true)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.enums import EstadoLinea, EstadoPedido, columna_enum

DINERO = Numeric(16, 2)
_ESTADOS_ABIERTOS = "estado IN ('abierto', 'cuenta_pedida')"


def nuevo_uuid() -> str:
    return str(uuid.uuid4())


# ============================================================
# TABLA: mesas  (plano visual del local)
# ============================================================
class Mesa(Base):
    __tablename__ = "mesas"
    __table_args__ = (
        UniqueConstraint("sucursal_id", "nombre", name="uq_mesa_sucursal_nombre"),
        CheckConstraint("capacidad > 0", name="ck_mesa_capacidad_positiva"),
    )

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)

    nombre:    Mapped[str] = mapped_column(String(40))              # "Mesa 5", "Terraza 2", "Barra 1"
    capacidad: Mapped[int] = mapped_column(Integer, default=4)

    # Posición en el plano (0–1000 sobre un lienzo imaginario; la app lo escala).
    pos_x:  Mapped[int] = mapped_column(Integer, default=0)
    pos_y:  Mapped[int] = mapped_column(Integer, default=0)
    ancho:  Mapped[int] = mapped_column(Integer, default=80)
    alto:   Mapped[int] = mapped_column(Integer, default=80)
    forma:  Mapped[str] = mapped_column(String(20), default="cuadrada")   # cuadrada | redonda | rectangular

    # Código del QR pegado en la mesa: un ATAJO para anclarse a ella, no la única forma.
    qr_token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid.uuid4().hex)

    activa:    Mapped[bool]     = mapped_column(default=True, server_default=true())
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# TABLA: pedidos  (la cuenta abierta de una mesa)
# ============================================================
class Pedido(Base):
    __tablename__ = "pedidos"
    __table_args__ = (
        # Una mesa no puede tener dos cuentas abiertas a la vez.
        Index("uq_pedido_mesa_abierta", "mesa_id", unique=True,
              postgresql_where=text(_ESTADOS_ABIERTOS), sqlite_where=text(_ESTADOS_ABIERTOS)),
        CheckConstraint("comensales IS NULL OR comensales > 0", name="ck_pedido_comensales_positivo"),
        CheckConstraint("descuento >= 0 AND propina >= 0", name="ck_pedido_descuento_propina_no_negativos"),
    )

    id:          Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_uuid)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    mesa_id:     Mapped[Optional[int]] = mapped_column(ForeignKey("mesas.id"), index=True)   # None: mostrador/delivery (más adelante)
    mesero_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True)

    estado:     Mapped[EstadoPedido] = mapped_column(columna_enum(EstadoPedido), default=EstadoPedido.abierto)
    comensales: Mapped[Optional[int]] = mapped_column(Integer)

    # Cobro: el descuento lo aplica el cajero (con su tope) y la propina la anota el mesero al pedir la cuenta.
    descuento:        Mapped[Decimal] = mapped_column(DINERO, default=Decimal("0"), server_default="0")
    descuento_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    propina:          Mapped[Decimal] = mapped_column(DINERO, default=Decimal("0"), server_default="0")

    abierto_en:        Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now())
    cuenta_pedida_en:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cerrado_en:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    mesa:      Mapped[Optional["Mesa"]]   = relationship()
    lineas:    Mapped[list["LineaPedido"]] = relationship(back_populates="pedido", cascade="all, delete-orphan",
                                                          order_by="LineaPedido.creado_en")
    traspasos: Mapped[list["TraspasoMesero"]] = relationship(cascade="all, delete-orphan")


# ============================================================
# TABLA: lineas_pedido  (un plato pedido, con su estado)
# ============================================================
class LineaPedido(Base):
    __tablename__ = "lineas_pedido"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_linea_cantidad_positiva"),
        CheckConstraint("precio_unitario >= 0", name="ck_linea_precio_no_negativo"),
        Index("ix_linea_estado", "empresa_id", "estado"),
    )

    id:         Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_uuid)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    pedido_id:  Mapped[str] = mapped_column(ForeignKey("pedidos.id", ondelete="CASCADE"), index=True)
    item_id:    Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)

    cantidad:        Mapped[int]     = mapped_column(Integer, default=1)
    precio_unitario: Mapped[Decimal] = mapped_column(DINERO)          # copiado del ítem al tomarla
    comensal:        Mapped[Optional[int]] = mapped_column(Integer)   # "cliente 2" (se toma cliente por cliente)
    nota:            Mapped[Optional[str]] = mapped_column(String(255))

    estado: Mapped[EstadoLinea] = mapped_column(columna_enum(EstadoLinea), default=EstadoLinea.tomada)
    estacion: Mapped[str] = mapped_column(String(20), default="cocina")   # copiada del ítem: cocina | barra

    creado_en:       Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviada_en:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    preparacion_en:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    lista_en:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    entregada_en:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelada_en:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    pedido:    Mapped["Pedido"] = relationship(back_populates="lineas")
    item:      Mapped["Item"]   = relationship()                      # noqa: F821 (definido en inventario)
    quitados:  Mapped[list["LineaQuitado"]] = relationship(cascade="all, delete-orphan")
    extras:    Mapped[list["LineaExtra"]]   = relationship(cascade="all, delete-orphan")

    @property
    def total(self) -> Decimal:
        """(precio del plato + extras) × cantidad. Quitar ingredientes no baja el precio."""
        adicionales = sum((e.precio for e in self.extras), Decimal("0"))
        return (self.precio_unitario + adicionales) * self.cantidad


class LineaQuitado(Base):
    """Un ingrediente que el cliente pidió quitar ("sin cebolla")."""
    __tablename__ = "linea_quitados"

    linea_id:       Mapped[str] = mapped_column(ForeignKey("lineas_pedido.id", ondelete="CASCADE"), primary_key=True)
    ingrediente_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)


class LineaExtra(Base):
    """Un extra pedido ("extra tocineta"), con su precio copiado al momento de pedirlo."""
    __tablename__ = "linea_extras"

    id:       Mapped[int] = mapped_column(primary_key=True)
    linea_id: Mapped[str] = mapped_column(ForeignKey("lineas_pedido.id", ondelete="CASCADE"), index=True)
    extra_id: Mapped[int] = mapped_column(ForeignKey("extras.id"))
    precio:   Mapped[Decimal] = mapped_column(DINERO)


# ============================================================
# TABLA: traspasos_mesero  (cambio de mesero en una mesa abierta)
# ============================================================
class TraspasoMesero(Base):
    __tablename__ = "traspasos_mesero"

    id:        Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[str] = mapped_column(ForeignKey("pedidos.id", ondelete="CASCADE"), index=True)
    de_usuario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    a_usuario_id:  Mapped[int]           = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
