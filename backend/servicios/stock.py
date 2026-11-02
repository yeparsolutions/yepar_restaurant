# ============================================================
# YEPAR RESTAURANT — backend/servicios/stock.py
# Único lugar donde se modifica el stock FÍSICO de un ítem.
#
# Analogía: es el libro de entradas y salidas de la bodega. Nadie
# mueve mercadería sin anotarla acá, así el saldo siempre coincide
# con la suma de los movimientos.
#
# Compras, producción, ventas, mermas y ajustes de inventario usan
# todos `aplicar_movimiento`; ninguno toca `cantidad_fisica` por su cuenta.
# ============================================================

from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import (Item, MotivoMerma, MovimientoStock, StockSucursal,
                    Sucursal, TipoMovimientoStock)
from unidades import a_decimal, redondear_cantidad

# Signo que debe tener cada tipo de movimiento: +1 entra, -1 sale, 0 cualquiera.
_SIGNO_ESPERADO = {
    TipoMovimientoStock.compra:             +1,
    TipoMovimientoStock.produccion_entrada: +1,
    TipoMovimientoStock.produccion_consumo: -1,
    TipoMovimientoStock.consumo_venta:      -1,
    TipoMovimientoStock.merma:              -1,
    TipoMovimientoStock.ajuste_inventario:   0,    # un conteo puede sobrar o faltar
}


def cargar_item(db: Session, empresa_id: int, item_id: int) -> Item:
    """
    Busca un ítem verificando que sea de ESTA empresa. Si pertenece a otro
    cliente respondemos "no existe": nunca confirmamos que el dato ajeno existe.
    """
    item = db.get(Item, item_id)
    if item is None or item.empresa_id != empresa_id:
        raise ErrorNegocio(f"El ítem {item_id} no existe.")
    return item


def validar_sucursal(db: Session, empresa_id: int, sucursal_id: int) -> Sucursal:
    """Verifica que la sucursal exista y sea de esta empresa."""
    sucursal = db.get(Sucursal, sucursal_id)
    if sucursal is None or sucursal.empresa_id != empresa_id:
        raise ErrorNegocio(f"La sucursal {sucursal_id} no existe.")
    return sucursal


def obtener_stock(db: Session, empresa_id: int, item_id: int, sucursal_id: int) -> StockSucursal:
    """
    Devuelve la fila de stock de un ítem en una sucursal; si no existe la crea en cero.
    Bloquea la fila (SELECT ... FOR UPDATE en PostgreSQL) para que dos movimientos
    simultáneos —por ejemplo dos tablets— no se pisen el saldo.
    """
    stock = (db.query(StockSucursal)
               .filter_by(item_id=item_id, sucursal_id=sucursal_id)
               .with_for_update()
               .one_or_none())
    if stock is None:
        stock = StockSucursal(empresa_id=empresa_id, item_id=item_id, sucursal_id=sucursal_id,
                              cantidad_fisica=Decimal("0"), cantidad_reservada=Decimal("0"))
        db.add(stock)
        db.flush()
    return stock


def total_fisico_item(db: Session, item_id: int) -> Decimal:
    """Stock físico del ítem sumando TODAS las sucursales (base del costo promedio)."""
    db.flush()   # asegura que los cambios pendientes ya estén en la sesión de la base
    total = (db.query(func.coalesce(func.sum(StockSucursal.cantidad_fisica), 0))
               .filter(StockSucursal.item_id == item_id)
               .scalar())
    return a_decimal(total)


def aplicar_movimiento(
    db: Session, *,
    stock: StockSucursal,
    tipo: TipoMovimientoStock,
    cantidad,
    costo_unitario=None,
    motivo_merma: Optional[MotivoMerma] = None,
    usuario_id: Optional[int] = None,
    referencia_tipo: Optional[str] = None,
    referencia_id=None,
    nota: Optional[str] = None,
) -> MovimientoStock:
    """
    Cambia el stock físico y deja la fila en el libro de movimientos.

    `cantidad` va CON SIGNO y en unidad base: entrada positiva, salida negativa.
    Faltar stock NO bloquea: el saldo puede quedar negativo (solo alerta).
    """
    cantidad = redondear_cantidad(a_decimal(cantidad))
    if cantidad == 0:
        raise ErrorNegocio("Un movimiento de stock no puede ser de cantidad cero.")

    signo = _SIGNO_ESPERADO[tipo]
    if signo > 0 and cantidad < 0:
        raise ErrorNegocio(f"Un movimiento de tipo '{tipo.value}' debe ser una entrada (cantidad positiva).")
    if signo < 0 and cantidad > 0:
        raise ErrorNegocio(f"Un movimiento de tipo '{tipo.value}' debe ser una salida (cantidad negativa).")

    if tipo == TipoMovimientoStock.merma and motivo_merma is None:
        raise ErrorNegocio("Toda merma necesita un motivo.")
    if tipo != TipoMovimientoStock.merma and motivo_merma is not None:
        raise ErrorNegocio("Solo las mermas llevan motivo de merma.")

    anterior = a_decimal(stock.cantidad_fisica or 0)
    nuevo = anterior + cantidad
    stock.cantidad_fisica = nuevo

    movimiento = MovimientoStock(
        empresa_id=stock.empresa_id, sucursal_id=stock.sucursal_id, item_id=stock.item_id,
        tipo=tipo, cantidad=cantidad, stock_anterior=anterior, stock_nuevo=nuevo,
        costo_unitario=costo_unitario, motivo_merma=motivo_merma, usuario_id=usuario_id,
        referencia_tipo=referencia_tipo,
        referencia_id=None if referencia_id is None else str(referencia_id),
        nota=nota,
    )
    db.add(movimiento)
    db.flush()
    return movimiento
