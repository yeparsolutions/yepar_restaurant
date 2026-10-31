# ============================================================
# YEPAR RESTAURANT — backend/servicios/compras.py
# Ingreso de mercadería comprada: convierte unidades, sube el stock,
# recalcula el costo promedio y deja el movimiento en el libro.
#
# Analogía: es la puerta de recepción de la bodega. Llega el camión con
# "5 kilos de tomate a $7.500", el recepcionista lo traduce a la regla
# única de la bodega (5.000 g), lo anota en el libro y actualiza cuánto
# cuesta ahora el gramo.
#
# Este servicio se llama cuando el COCINERO confirma la recepción física
# (la segunda llave). La factura que registra el admin es la primera llave
# y vive en el módulo de compras que se reutiliza de Carora.
# ============================================================

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import ItemPresentacion, MovimientoStock, TipoItem, TipoMovimientoStock, Unidad
from servicios.stock import (aplicar_movimiento, cargar_item, obtener_stock,
                             total_fisico_item, validar_sucursal)
from unidades import (a_decimal, convertir_a_unidad_base, costo_de_referencia,
                      costo_por_unidad_base, costo_promedio_ponderado,
                      redondear_cantidad)

# Lo que se compra: materia prima y bebidas de reventa. Los componentes se
# producen en lote y los platos se preparan; ninguno de los dos se compra.
TIPOS_COMPRABLES = frozenset({TipoItem.materia_prima, TipoItem.vendible_reventa})


@dataclass(frozen=True)
class ResultadoCompra:
    movimiento: MovimientoStock
    cantidad_base: Decimal          # lo que entró, en unidad base
    costo_unitario_base: Decimal    # $ por unidad base de ESTA compra
    costo_promedio: Decimal         # nuevo promedio ponderado del ítem
    costo_referencia: Decimal       # el mayor entre promedio y último precio


def resolver_cantidad_y_costo(db: Session, item, *, cantidad, unidad=None, presentacion_id=None,
                              monto_neto=None, costo_unitario_base=None) -> tuple:
    """
    Pasa lo que dice una factura (3 kg, 2 cajas de 12...) a unidad base y calcula el costo por unidad base.
    Devuelve (cantidad_base, costo_unitario_base). No toca el stock: la usan tanto el ingreso directo de una
    compra como el registro de una factura que aún no se recibe.
    """
    if (monto_neto is None) == (costo_unitario_base is None):
        raise ErrorNegocio("Indica el costo con monto_neto O con costo_unitario_base (uno solo).")
    if unidad is not None and presentacion_id is not None:
        raise ErrorNegocio("Indica la unidad O la presentación de origen, no ambas.")
    # 1) A unidad base.
    if presentacion_id is not None:
        presentacion = db.get(ItemPresentacion, presentacion_id)
        if presentacion is None or presentacion.item_id != item.id:
            raise ErrorNegocio("La presentación no pertenece a este ítem.")
        cantidad_base = convertir_a_unidad_base(item, cantidad, presentacion=presentacion)
    elif unidad is not None:
        catalogo = db.query(Unidad).filter_by(codigo=unidad).one_or_none()
        if catalogo is None:
            raise ErrorNegocio(f"La unidad '{unidad}' no existe en el catálogo.")
        cantidad_base = convertir_a_unidad_base(item, cantidad, unidad=catalogo)
    else:
        cantidad_base = redondear_cantidad(a_decimal(cantidad))
        if cantidad_base <= 0:
            raise ErrorNegocio("La cantidad comprada debe ser mayor que cero.")

    # 2) Costo por unidad base de esta compra.
    if monto_neto is not None:
        costo_nuevo = costo_por_unidad_base(monto_neto, cantidad_base)
    else:
        costo_nuevo = a_decimal(costo_unitario_base)
        if costo_nuevo < 0:
            raise ErrorNegocio("El costo no puede ser negativo.")
    return cantidad_base, costo_nuevo


def convertir_cantidad(db: Session, item, *, cantidad, unidad=None, presentacion_id=None,
                       permitir_cero: bool = False) -> Decimal:
    """
    Lleva una cantidad dicha en kg, cajas, etc. a la unidad base del ítem (sin costos ni stock).
    Con `permitir_cero` acepta 0 (un conteo puede decir "no queda nada"); nunca acepta negativos.
    """
    cantidad = a_decimal(cantidad)
    if cantidad < 0:
        raise ErrorNegocio("La cantidad no puede ser negativa.")
    if cantidad == 0:
        if permitir_cero:
            return Decimal("0.000")
        raise ErrorNegocio("La cantidad debe ser mayor que cero.")
    return resolver_cantidad_y_costo(db, item, cantidad=cantidad, unidad=unidad,
                                     presentacion_id=presentacion_id, costo_unitario_base=0)[0]


def ingresar_compra(
    db: Session, *,
    empresa_id: int,
    sucursal_id: int,
    item_id: int,
    cantidad,
    unidad: Optional[str] = None,
    presentacion_id: Optional[int] = None,
    monto_neto=None,
    costo_unitario_base=None,
    usuario_id: Optional[int] = None,
    referencia_tipo: Optional[str] = "compra",
    referencia_id=None,
    nota: Optional[str] = None,
) -> ResultadoCompra:
    """
    Registra la entrada física de una compra.

    Cantidad (una sola forma de origen):
      - `unidad`: código del catálogo ('kg', 'l', 'g'...) de la misma familia que el ítem.
      - `presentacion_id`: una presentación del ítem ("Caja 12 un").
      - ninguna: `cantidad` ya viene en la unidad base.

    Costo (una sola de las dos):
      - `monto_neto`: lo pagado por TODA la línea, SIN IVA (el IVA no es costo).
      - `costo_unitario_base`: $ por unidad base, si ya se conoce.

    El costo promedio se pondera con el stock de TODAS las sucursales
    del ítem, porque el costo es un dato del ítem y no de cada local.
    """
    item = cargar_item(db, empresa_id, item_id)
    validar_sucursal(db, empresa_id, sucursal_id)

    if item.tipo not in TIPOS_COMPRABLES:
        raise ErrorNegocio(
            f"'{item.nombre}' es de tipo '{item.tipo.value}': no se compra, se produce.")

    cantidad_base, costo_nuevo = resolver_cantidad_y_costo(
        db, item, cantidad=cantidad, unidad=unidad, presentacion_id=presentacion_id,
        monto_neto=monto_neto, costo_unitario_base=costo_unitario_base)

    # 3) Nuevo promedio ponderado, con el stock total ANTES de que entre esta compra.
    stock_total_antes = total_fisico_item(db, item.id)
    item.costo_promedio = costo_promedio_ponderado(
        stock_total_antes, item.costo_promedio, cantidad_base, costo_nuevo)
    item.costo_ultimo = costo_nuevo

    # 4) Subir el stock y dejar el movimiento en el libro.
    stock = obtener_stock(db, empresa_id, item.id, sucursal_id)
    movimiento = aplicar_movimiento(
        db, stock=stock, tipo=TipoMovimientoStock.compra, cantidad=cantidad_base,
        costo_unitario=costo_nuevo, usuario_id=usuario_id,
        referencia_tipo=referencia_tipo, referencia_id=referencia_id, nota=nota)

    return ResultadoCompra(
        movimiento=movimiento,
        cantidad_base=cantidad_base,
        costo_unitario_base=costo_nuevo,
        costo_promedio=item.costo_promedio,
        costo_referencia=costo_de_referencia(item.costo_promedio, item.costo_ultimo),
    )
