# ============================================================
# YEPAR RESTAURANT — backend/models/compras.py
# Facturas de compra pendientes de recepción física.
#
# Analogía: la factura del proveedor es el "pedido que dice el papel"; la
# recepción es el cocinero abriendo las cajas y contando lo que de verdad
# llegó. El stock solo sube con lo contado, nunca con lo facturado.
# ============================================================

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.enums import EstadoCompra, columna_enum
from models.inventario import CANTIDAD, COSTO_UNITARIO


class Compra(Base):
    __tablename__ = "compras"
    __table_args__ = (
        # La misma factura de un proveedor no se registra dos veces.
        UniqueConstraint("empresa_id", "proveedor", "numero_documento", name="uq_compra_documento"),
    )

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    proveedor:   Mapped[str] = mapped_column(String(120))
    numero_documento: Mapped[Optional[str]] = mapped_column(String(60))
    estado:      Mapped[EstadoCompra] = mapped_column(columna_enum(EstadoCompra), default=EstadoCompra.por_recibir)
    nota:        Mapped[Optional[str]] = mapped_column(Text)
    creada_por_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    creada_en:      Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recibida_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    recibida_en:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    lineas: Mapped[list["CompraLinea"]] = relationship(back_populates="compra", cascade="all, delete-orphan",
                                                      order_by="CompraLinea.id")


class CompraLinea(Base):
    __tablename__ = "compra_lineas"
    __table_args__ = (UniqueConstraint("compra_id", "item_id", name="uq_compra_linea_item"),)

    id:        Mapped[int] = mapped_column(primary_key=True)
    compra_id: Mapped[int] = mapped_column(ForeignKey("compras.id", ondelete="CASCADE"), index=True)
    item_id:   Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    # Todo en unidad base: lo que dice el papel y lo que costó cada unidad base.
    cantidad_facturada: Mapped[Decimal] = mapped_column(CANTIDAD)
    costo_unitario_base: Mapped[Decimal] = mapped_column(COSTO_UNITARIO)
    # Lo que el cocinero contó al recibir (nulo hasta recibir; 0 = no llegó).
    cantidad_recibida: Mapped[Optional[Decimal]] = mapped_column(CANTIDAD)

    compra: Mapped["Compra"] = relationship(back_populates="lineas")
    item = relationship("Item")
