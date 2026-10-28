# ============================================================
# YEPAR RESTAURANT — backend/models/__init__.py
# Importar todos los modelos acá garantiza que SQLAlchemy los
# registre antes de crear las tablas (Base.metadata.create_all).
# ============================================================

from models.enums import (EstacionCocina, EstadoReserva, FamiliaUnidad, MotivoMerma,
                          RolUsuario, TipoItem, TipoMovimientoStock)
from models.inventario import (CategoriaItem, Extra, ExtraPlato, Item,
                               ItemPresentacion, LoteProduccion,
                               MovimientoStock, Receta, RecetaLinea,
                               ReservaStock, StockSucursal, Unidad)
from models.tenant import Empresa, Sucursal, Usuario, UsuarioRol

__all__ = [
    "EstacionCocina", "EstadoReserva", "ReservaStock", "FamiliaUnidad", "MotivoMerma", "RolUsuario", "TipoItem",
    "TipoMovimientoStock",
    "CategoriaItem", "Extra", "ExtraPlato", "Item", "ItemPresentacion",
    "LoteProduccion", "MovimientoStock", "Receta", "RecetaLinea",
    "StockSucursal", "Unidad",
    "Empresa", "Sucursal", "Usuario", "UsuarioRol",
]
