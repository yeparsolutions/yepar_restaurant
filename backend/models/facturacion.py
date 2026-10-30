# ============================================================
# YEPAR RESTAURANT — backend/models/facturacion.py
# Facturación electrónica: con quién factura cada restaurante y los
# documentos tributarios (boleta/factura) que salen de las cuentas pagadas.
#
# Analogía: IntegracionFacturacion es la "tarjeta de contacto" del notario
# del restaurante (YeparDTE en Chile, YeparFactura en Venezuela);
# DocumentoTributario es el recibo timbrado que el notario devuelve.
# ============================================================

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func,
                        false, true)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.enums import EstadoDocumento, ProveedorFacturacion, TipoDocumento, columna_enum

DINERO = Numeric(16, 2)


class IntegracionFacturacion(Base):
    """El facturador de un restaurante. Uno por empresa (la API Key va CIFRADA)."""
    __tablename__ = "integraciones_facturacion"

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), primary_key=True)
    proveedor:  Mapped[ProveedorFacturacion] = mapped_column(columna_enum(ProveedorFacturacion))
    api_key_cifrada: Mapped[str] = mapped_column(Text)
    activo:     Mapped[bool] = mapped_column(default=True, server_default=true())
    # Al cerrarse la mesa (pagada) se emite sola la boleta, sin que el cajero haga nada.
    emision_automatica: Mapped[bool] = mapped_column(default=False, server_default=false())
    tipo_automatico:    Mapped[TipoDocumento] = mapped_column(columna_enum(TipoDocumento), default=TipoDocumento.boleta)
    actualizado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class DocumentoTributario(Base):
    __tablename__ = "documentos_tributarios"
    __table_args__ = (
        # Una cuenta tiene a lo sumo UN documento: reintentar nunca duplica el folio.
        UniqueConstraint("pedido_id", name="uq_documento_pedido"),
        UniqueConstraint("empresa_id", "idempotency_key", name="uq_documento_clave"),
    )

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    pedido_id:   Mapped[str] = mapped_column(ForeignKey("pedidos.id"))

    proveedor: Mapped[ProveedorFacturacion] = mapped_column(columna_enum(ProveedorFacturacion))
    tipo:      Mapped[TipoDocumento]        = mapped_column(columna_enum(TipoDocumento))
    estado:    Mapped[EstadoDocumento]      = mapped_column(columna_enum(EstadoDocumento),
                                                            default=EstadoDocumento.pendiente)
    # Clave estable que se envía al facturador: ante un reintento devuelve el mismo folio.
    idempotency_key: Mapped[str] = mapped_column(String(80))

    receptor:    Mapped[dict] = mapped_column(JSON, default=dict)      # lo que se mandó (rut, nombre, giro...)
    moneda:      Mapped[Optional[str]] = mapped_column(String(10))           # moneda en que vendió el restaurante
    moneda_montos: Mapped[Optional[str]] = mapped_column(String(10))         # moneda de neto/iva/total (VE: VES)
    tasa_cambio: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))   # VE: la congela YeparFactura (BCV vía YeparFX)
    total_divisa: Mapped[Optional[Decimal]] = mapped_column(DINERO)          # VE: total en la moneda original

    folio:     Mapped[Optional[str]] = mapped_column(String(40))
    neto:      Mapped[Optional[Decimal]] = mapped_column(DINERO)
    iva:       Mapped[Optional[Decimal]] = mapped_column(DINERO)
    total:     Mapped[Optional[Decimal]] = mapped_column(DINERO)
    pdf_url:   Mapped[Optional[str]] = mapped_column(String(500))
    track_id:  Mapped[Optional[str]] = mapped_column(String(80))

    intentos:      Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ultimo_error:  Mapped[Optional[str]] = mapped_column(String(500))
    emitido_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    creado_en:     Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    emitido_en:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
