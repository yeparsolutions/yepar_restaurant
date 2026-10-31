# ============================================================
# YEPAR RESTAURANT — backend/models/conteo.py
# Inventario físico ciego: contar la bodega sin ver lo que dice el sistema.
#
# Analogía: es el arqueo de caja pero de la bodega. Quien cuenta no ve
# cuánto "debería" haber, así no puede ajustar el número para que cuadre.
# ============================================================

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.enums import EstadoInventarioFisico, columna_enum
from models.inventario import CANTIDAD, COSTO_UNITARIO


class InventarioFisico(Base):
    __tablename__ = "inventarios_fisicos"

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    estado: Mapped[EstadoInventarioFisico] = mapped_column(columna_enum(EstadoInventarioFisico),
                                                           default=EstadoInventarioFisico.contando)
    # Nulo = inventario general; con valor = solo los ítems de esa categoría.
    alcance_categoria_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categorias_item.id", ondelete="SET NULL"))
    nota:          Mapped[Optional[str]] = mapped_column(Text)
    creado_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    creado_en:     Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cerrado_en:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    lineas: Mapped[list["InventarioFisicoLinea"]] = relationship(
        back_populates="inventario", cascade="all, delete-orphan", order_by="InventarioFisicoLinea.id")


class InventarioFisicoLinea(Base):
    __tablename__ = "inventario_fisico_lineas"
    __table_args__ = (UniqueConstraint("inventario_id", "item_id", name="uq_conteo_linea_item"),)

    id:            Mapped[int] = mapped_column(primary_key=True)
    inventario_id: Mapped[int] = mapped_column(ForeignKey("inventarios_fisicos.id", ondelete="CASCADE"), index=True)
    item_id:       Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    # Foto del sistema al abrir el conteo (no cambia aunque haya ventas durante el conteo).
    cantidad_sistema:  Mapped[Decimal] = mapped_column(CANTIDAD)
    costo_referencia:  Mapped[Decimal] = mapped_column(COSTO_UNITARIO)
    cantidad_contada:  Mapped[Optional[Decimal]] = mapped_column(CANTIDAD)
    contada_por_id:    Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    contada_en:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    inventario: Mapped["InventarioFisico"] = relationship(back_populates="lineas")
    item = relationship("Item")
