# ============================================================
# YEPAR RESTAURANT — backend/models/tenant.py
# Quién usa el sistema: restaurantes (clientes), sus locales y su gente.
#
# Es un producto para TERCEROS: cada restaurante es un cliente
# aislado y solo ve sus propios datos. Por eso casi todas las
# tablas del sistema llevan `empresa_id`.
#
# Analogía: Empresa = el edificio completo de un cliente,
# Sucursal = cada local del cliente, Usuario = cada persona que
# tiene llave de ese edificio.
#
# NOTA: acá solo está lo MÍNIMO que necesita el núcleo de inventario.
# Planes, límites, datos tributarios y credenciales cifradas se
# copian desde Carora (YeparStock) más adelante, sin rediseñarlos.
# ============================================================

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (Boolean, DateTime, ForeignKey, Numeric, String,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.enums import EstacionCocina, RolUsuario, columna_enum


class Empresa(Base):
    """Un restaurante cliente (el 'inquilino' del sistema)."""
    __tablename__ = "empresas"

    id:            Mapped[int]           = mapped_column(primary_key=True)
    nombre:        Mapped[str]           = mapped_column(String(150))
    # Código corto que el dueño comparte con su equipo para iniciar sesión.
    codigo_acceso: Mapped[Optional[str]] = mapped_column(String(8), unique=True)
    pais:          Mapped[str]           = mapped_column(String(2), default="CL")
    moneda:        Mapped[str]           = mapped_column(String(10), default="CLP")
    activa:        Mapped[bool]          = mapped_column(Boolean, default=True)
    creado_en:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    sucursales: Mapped[list["Sucursal"]] = relationship(back_populates="empresa", cascade="all, delete-orphan")
    usuarios:   Mapped[list["Usuario"]]  = relationship(back_populates="empresa")


class Sucursal(Base):
    """
    Un local del restaurante. El stock se guarda POR sucursal: si el
    cliente quiere ver el total consolidado, se suma (ver StockSucursal).
    """
    __tablename__ = "sucursales"
    __table_args__ = (UniqueConstraint("empresa_id", "nombre", name="uq_sucursal_empresa_nombre"),)

    id:         Mapped[int]      = mapped_column(primary_key=True)
    empresa_id: Mapped[int]      = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    nombre:     Mapped[str]      = mapped_column(String(150))
    activa:     Mapped[bool]     = mapped_column(Boolean, default=True)
    creado_en:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped["Empresa"] = relationship(back_populates="sucursales")


class Usuario(Base):
    """
    Una persona del equipo. Puede tener VARIOS roles (en un local chico
    el dueño es administrador y cajero a la vez), por eso los roles viven
    en la tabla `UsuarioRol` y no en una sola columna.
    """
    __tablename__ = "usuarios"
    __table_args__ = (UniqueConstraint("empresa_id", "username", name="uq_usuario_empresa_username"),)

    id:            Mapped[int]           = mapped_column(primary_key=True)
    empresa_id:    Mapped[int]           = mapped_column(ForeignKey("empresas.id"), index=True)
    sucursal_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("sucursales.id", ondelete="SET NULL"), index=True)
    nombre:        Mapped[str]           = mapped_column(String(100))
    username:      Mapped[str]           = mapped_column(String(50))
    email:         Mapped[Optional[str]] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str]           = mapped_column(String(255))
    # Solo aplica al rol cocinero: ¿trabaja en cocina o en barra?
    estacion:      Mapped[Optional[EstacionCocina]] = mapped_column(columna_enum(EstacionCocina))
    # Tope de descuento (%) que este usuario puede dar al cobrar. 0 = ninguno.
    # Lo que exceda el tope pide el PIN de un supervisor.
    descuento_max_pct: Mapped[Decimal]   = mapped_column(Numeric(5, 2), default=Decimal("0"), server_default="0")
    activo:        Mapped[bool]          = mapped_column(Boolean, default=True)
    creado_en:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped["Empresa"] = relationship(back_populates="usuarios")
    roles:   Mapped[list["UsuarioRol"]] = relationship(back_populates="usuario", cascade="all, delete-orphan")


class UsuarioRol(Base):
    """Un rol asignado a un usuario. Un usuario no puede repetir el mismo rol."""
    __tablename__ = "usuario_roles"
    __table_args__ = (UniqueConstraint("usuario_id", "rol", name="uq_usuario_rol"),)

    id:         Mapped[int]        = mapped_column(primary_key=True)
    usuario_id: Mapped[int]        = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    rol:        Mapped[RolUsuario] = mapped_column(columna_enum(RolUsuario))

    usuario: Mapped["Usuario"] = relationship(back_populates="roles")
