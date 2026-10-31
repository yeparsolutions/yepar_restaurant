# ============================================================
# YEPAR RESTAURANT — backend/models/sync.py
# Bitácora de operaciones que la tablet hizo sin conexión y subió después.
#
# Analogía: es el "talonario con copia" del mesero. Cada hoja lleva un número
# único; si la misma hoja llega dos veces (se cortó el internet justo al
# enviar), el sistema reconoce el número y devuelve lo que ya había respondido.
# ============================================================

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class OperacionSync(Base):
    __tablename__ = "operaciones_sync"
    __table_args__ = (UniqueConstraint("empresa_id", "op_id", name="uq_operacion_sync"),)

    id:         Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    op_id:      Mapped[str] = mapped_column(String(36))          # UUID que generó la tablet
    tipo:       Mapped[str] = mapped_column(String(30))
    estado:     Mapped[str] = mapped_column(String(15))          # aplicada | rechazada
    error:      Mapped[Optional[str]] = mapped_column(Text)
    creada_en:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
