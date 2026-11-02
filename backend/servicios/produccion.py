# ============================================================
# YEPAR RESTAURANT — backend/servicios/produccion.py
# Producción de componentes por lote (ej. salsa de ajo).
#
# Analogía: es la "olla grande" de la cocina. Se sacan los ingredientes
# de la despensa (sale la mayonesa y el ajo), se cocina el lote y el
# resultado entra a la despensa como un ingrediente nuevo (entra la
# salsa de ajo). Todo queda anotado en el cuaderno de movimientos y el
# lote guarda cuánto costó, para saber el costo por gramo de la salsa.
# ============================================================

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import LoteProduccion, MovimientoStock, TipoItem, TipoMovimientoStock
from servicios.recetas import _costo_exacto_por_unidad
from servicios.stock import (aplicar_movimiento, cargar_item, obtener_stock,
                             total_fisico_item, validar_sucursal)
from unidades import (a_decimal, costo_promedio_ponderado, redondear_cantidad,
                      redondear_costo)


@dataclass
class ResultadoProduccion:
    """Lo que dejó producir un lote."""
    lote: LoteProduccion
    consumos: list = field(default_factory=list)      # MovimientoStock de cada insumo (salidas)
    entrada: Optional[MovimientoStock] = None          # MovimientoStock del componente producido
    faltantes: list = field(default_factory=list)      # nombres de insumos que quedaron en negativo


def producir_componente(
    db: Session, *,
    empresa_id: int,
    sucursal_id: int,
    item_id: int,
    cantidad_producida=None,
    usuario_id: Optional[int] = None,
    nota: Optional[str] = None,
) -> ResultadoProduccion:
    """
    Produce un lote del componente según su receta.

    - `cantidad_producida`: lo que realmente salió, en unidad base del componente.
      Si no se indica se usa el rendimiento de la receta. Los insumos se consumen
      en proporción (si la receta rinde 1000 g y salieron 500 g, se gasta la mitad).
    - Los insumos pueden quedar en negativo: faltar un ingrediente solo alerta,
      se informa en `faltantes` para que la app avise al administrador.
    - No hace commit (lo decide quien llama).
    """
    item = cargar_item(db, empresa_id, item_id)
    validar_sucursal(db, empresa_id, sucursal_id)      # primero lo del cliente, luego las reglas
    if item.tipo != TipoItem.componente:
        raise ErrorNegocio(f"'{item.nombre}' no es un componente: solo los componentes se producen por lote.")
    receta = item.receta
    if receta is None:
        raise ErrorNegocio(f"'{item.nombre}' no tiene receta.")

    producida = (receta.rendimiento if cantidad_producida is None
                 else redondear_cantidad(a_decimal(cantidad_producida)))
    if producida <= 0:
        raise ErrorNegocio("La cantidad producida debe ser mayor que cero.")
    proporcion = producida / receta.rendimiento

    # Costo del lote con los costos de hoy (antes de mover stock).
    costo_total = Decimal("0")
    gastos = []
    for linea in receta.lineas:
        gasto = redondear_cantidad(linea.cantidad * proporcion)
        if gasto <= 0:
            continue    # cantidad minúscula que redondea a cero: no mueve stock
        costo_total += gasto * _costo_exacto_por_unidad(db, linea.ingrediente, {item.id})
        gastos.append((linea.ingrediente, gasto))
    costo_total = costo_total.quantize(Decimal("0.01"))
    costo_unitario = redondear_costo(costo_total / producida)

    lote = LoteProduccion(
        empresa_id=empresa_id, sucursal_id=sucursal_id, item_id=item.id, receta_id=receta.id,
        cantidad_producida=producida, costo_total=costo_total, costo_unitario=costo_unitario,
        producido_por_id=usuario_id, nota=nota)
    db.add(lote)
    db.flush()                                     # para tener lote.id como referencia

    resultado = ResultadoProduccion(lote=lote)
    for ingrediente, gasto in gastos:
        stock = obtener_stock(db, empresa_id, ingrediente.id, sucursal_id)
        resultado.consumos.append(aplicar_movimiento(
            db, stock=stock, tipo=TipoMovimientoStock.produccion_consumo, cantidad=-gasto,
            usuario_id=usuario_id, referencia_tipo="lote_produccion", referencia_id=lote.id))
        if stock.cantidad_fisica < 0:
            resultado.faltantes.append(ingrediente.nombre)

    # El componente producido entra y su costo se promedia con lo que ya había.
    item.costo_promedio = costo_promedio_ponderado(
        total_fisico_item(db, item.id), item.costo_promedio, producida, costo_unitario)
    item.costo_ultimo = costo_unitario
    resultado.entrada = aplicar_movimiento(
        db, stock=obtener_stock(db, empresa_id, item.id, sucursal_id),
        tipo=TipoMovimientoStock.produccion_entrada, cantidad=producida, costo_unitario=costo_unitario,
        usuario_id=usuario_id, referencia_tipo="lote_produccion", referencia_id=lote.id, nota=nota)
    return resultado
