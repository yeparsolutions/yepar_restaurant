# ============================================================
# YEPAR RESTAURANT — backend/servicios/mermas.py
# Mermas manuales y consultas de stock / libro de movimientos.
#
# Analogía: la merma es el "papel de la basura" de la cocina: cada
# vez que algo se pierde (se venció, se cayó) se anota QUÉ, CUÁNTO y
# POR QUÉ. Sin ese papel el stock del sistema nunca cuadraría con el
# estante real, y no sabrías dónde se te va la plata.
# ============================================================

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import (Item, MotivoMerma, MovimientoStock, StockSucursal, TipoItem,
                    TipoMovimientoStock)
from servicios.stock import (aplicar_movimiento, cargar_item, obtener_stock,
                             validar_sucursal)
from unidades import a_decimal, redondear_cantidad


def registrar_merma(
    db: Session, *,
    empresa_id: int,
    sucursal_id: int,
    item_id: int,
    cantidad,
    motivo: str,
    usuario_id: Optional[int] = None,
    nota: Optional[str] = None,
) -> MovimientoStock:
    """
    Anota una pérdida de stock (cantidad POSITIVA en unidad base; el servicio
    la resta). Valida que el ítem y la sucursal sean del cliente. No hace commit.
    Los platos terminados no se mermán aquí: su pérdida es la merma de sus
    ingredientes (se genera al cancelar un plato en preparación).
    """
    item = cargar_item(db, empresa_id, item_id)
    validar_sucursal(db, empresa_id, sucursal_id)
    try:
        motivo_enum = MotivoMerma(motivo)
    except ValueError:
        raise ErrorNegocio(f"El motivo de merma '{motivo}' no existe.")
    if motivo_enum == MotivoMerma.cancelacion_en_preparacion:
        raise ErrorNegocio("Ese motivo lo genera el sistema al cancelar un plato en preparación.")
    if item.tipo in (TipoItem.vendible_preparado,):
        raise ErrorNegocio(f"'{item.nombre}' es un plato: la merma se registra sobre sus ingredientes.")
    cantidad = redondear_cantidad(a_decimal(cantidad))
    if cantidad <= 0:
        raise ErrorNegocio("La cantidad de la merma debe ser mayor que cero.")
    stock = obtener_stock(db, empresa_id, item.id, sucursal_id)
    return aplicar_movimiento(
        db, stock=stock, tipo=TipoMovimientoStock.merma, cantidad=-cantidad,
        costo_unitario=item.costo_referencia, motivo_merma=motivo_enum, usuario_id=usuario_id,
        referencia_tipo="merma_manual", nota=nota)


def listar_stock(db: Session, *, empresa_id: int, sucursal_id: int, solo_bajo_minimo: bool = False) -> list:
    """
    Foto del stock de la sucursal: [(item, físico, reservado, disponible)] de todos los
    ingredientes activos (aunque nunca hayan tenido movimiento: salen en cero).
    """
    validar_sucursal(db, empresa_id, sucursal_id)
    filas = {s.item_id: s for s in db.query(StockSucursal).filter_by(empresa_id=empresa_id, sucursal_id=sucursal_id)}
    items = (db.query(Item).filter(Item.empresa_id == empresa_id, Item.activo.is_(True),
                                   Item.tipo != TipoItem.vendible_preparado)
             .order_by(Item.nombre).all())
    salida = []
    for item in items:
        fila = filas.get(item.id)
        fisico = a_decimal(fila.cantidad_fisica) if fila else Decimal("0")
        reservado = a_decimal(fila.cantidad_reservada) if fila else Decimal("0")
        disponible = fisico - reservado
        if solo_bajo_minimo and not (item.stock_minimo > 0 and disponible < item.stock_minimo):
            continue
        salida.append((item, fisico, reservado, disponible))
    return salida


def listar_movimientos(db: Session, *, empresa_id: int, sucursal_id: int, item_id: Optional[int] = None,
                       limite: int = 100) -> list:
    """Libro de movimientos (el más reciente primero), de toda la sucursal o de un ítem."""
    validar_sucursal(db, empresa_id, sucursal_id)
    consulta = db.query(MovimientoStock).filter_by(empresa_id=empresa_id, sucursal_id=sucursal_id)
    if item_id is not None:
        cargar_item(db, empresa_id, item_id)
        consulta = consulta.filter_by(item_id=item_id)
    return consulta.order_by(MovimientoStock.id.desc()).limit(limite).all()
