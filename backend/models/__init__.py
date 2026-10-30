# ============================================================
# YEPAR RESTAURANT — backend/models/__init__.py
# Importar todos los modelos acá garantiza que SQLAlchemy los
# registre antes de crear las tablas (Base.metadata.create_all).
# ============================================================

from models.enums import (EstacionCocina, EstadoPropina, EstadoTurno, MedioPago, ModoPropina, EstadoLinea, EstadoPedido, EstadoReserva, FamiliaUnidad, MotivoMerma,
                          RolUsuario, TipoItem, TipoMovimientoStock, EstadoDocumento, ProveedorFacturacion,
                          TipoDocumento)
from models.facturacion import DocumentoTributario, IntegracionFacturacion
from models.inventario import (CategoriaItem, Extra, ExtraPlato, Item,
                               ItemPresentacion, LoteProduccion,
                               MovimientoStock, Receta, RecetaLinea,
                               ReservaStock, StockSucursal, Unidad)
from models.caja import (Caja, ConfiguracionCobro, Pago, PropinaPorEntregar, TerminalPago,
                         TurnoCaja)
from models.salon import (LineaExtra, LineaPedido, LineaQuitado, Mesa, Pedido,
                          TraspasoMesero)
from models.tenant import Empresa, Sucursal, Usuario, UsuarioRol

__all__ = [
    "EstacionCocina", "EstadoPropina", "PropinaPorEntregar", "EstadoTurno", "MedioPago", "ModoPropina", "Caja", "ConfiguracionCobro", "Pago",
    "TerminalPago", "TurnoCaja", "EstadoLinea", "EstadoPedido", "LineaExtra", "LineaPedido", "LineaQuitado",
    "Mesa", "Pedido", "TraspasoMesero", "EstadoReserva", "ReservaStock", "FamiliaUnidad", "MotivoMerma", "RolUsuario", "TipoItem",
    "TipoMovimientoStock",
    "CategoriaItem", "Extra", "ExtraPlato", "Item", "ItemPresentacion",
    "LoteProduccion", "MovimientoStock", "Receta", "RecetaLinea",
    "StockSucursal", "Unidad",
    "Empresa", "Sucursal", "Usuario", "UsuarioRol",
    "EstadoDocumento", "ProveedorFacturacion", "TipoDocumento", "DocumentoTributario", "IntegracionFacturacion",
]
