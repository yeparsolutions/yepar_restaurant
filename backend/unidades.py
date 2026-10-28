# ============================================================
# YEPAR RESTAURANT — backend/unidades.py
# Conversión de unidades de medida y cálculo de costos por unidad base.
#
# Analogía: este archivo es el "traductor" de la bodega. Alguien
# compra 1 kg de tomates y la receta pide 80 g: el traductor sabe
# que 1 kg son 1000 g y que nunca se puede traducir kilos a litros.
#
# Todo se calcula con Decimal (números exactos), NUNCA con float,
# para que sumar y restar gramos no acumule errores de redondeo.
# ============================================================

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

# Precisión con la que se guardan las cantidades y los costos.
_MILESIMA = Decimal("0.001")
_MILLONESIMA = Decimal("0.000001")


class ErrorUnidades(ValueError):
    """Se intentó una conversión o un dato de unidades que no es válido."""


def a_decimal(valor) -> Decimal:
    """
    Convierte a Decimal sin arrastrar los errores binarios de float.
    Ejemplo: Decimal(0.1) es 0.1000000000000000055...; a_decimal(0.1) es 0.1 exacto.
    """
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def redondear_cantidad(valor: Decimal) -> Decimal:
    """Redondea a milésimas (3 decimales), como se guardan las cantidades."""
    return a_decimal(valor).quantize(_MILESIMA, rounding=ROUND_HALF_UP)


def redondear_costo(valor: Decimal) -> Decimal:
    """Redondea a millonésimas (6 decimales), como se guardan los costos por unidad base."""
    return a_decimal(valor).quantize(_MILLONESIMA, rounding=ROUND_HALF_UP)


def exigir_unidad_base(unidad) -> None:
    """
    Un ítem solo puede guardar su stock en una unidad BASE (g, ml o und).
    Si alguien intenta usar 'kg' como unidad base, fallamos acá, antes de
    guardar nada.
    """
    if not unidad.es_base:
        raise ErrorUnidades(
            f"'{unidad.codigo}' no es una unidad base. El stock se guarda en "
            f"g, ml o und; las compras en kg, l o cajas se convierten al entrar."
        )


def convertir_a_unidad_base(item, cantidad, *, unidad=None, presentacion=None) -> Decimal:
    """
    Traduce una cantidad al UNIDAD BASE del ítem.

    Se indica de dónde viene con UNA de estas dos opciones:
      unidad       → una unidad estándar del catálogo (kg, l, cc, g...).
                     Solo vale si es de la misma familia que la unidad base del ítem.
      presentacion → una presentación propia del ítem (caja de 12, saco de 25 kg).

    Ejemplos (ítem Tomate, unidad base 'g'):
      convertir_a_unidad_base(tomate, 1, unidad=kg)   → 1000.000
      convertir_a_unidad_base(tomate, 2.5, unidad=kg) → 2500.000
      convertir_a_unidad_base(tomate, 1, unidad=l)    → ErrorUnidades (volumen ≠ peso)
    """
    if (unidad is None) == (presentacion is None):
        raise ErrorUnidades("Indica la unidad O la presentación de origen (una de las dos, no ambas).")

    cantidad = a_decimal(cantidad)
    if cantidad <= 0:
        raise ErrorUnidades("La cantidad a convertir debe ser mayor que cero.")

    if presentacion is not None:
        if presentacion.item_id is not None and item.id is not None and presentacion.item_id != item.id:
            raise ErrorUnidades("La presentación pertenece a otro ítem.")
        return redondear_cantidad(cantidad * presentacion.cantidad_en_base)

    base = item.unidad_base
    if unidad.familia != base.familia:
        raise ErrorUnidades(
            f"No se puede convertir '{unidad.codigo}' ({unidad.familia.value}) a "
            f"'{base.codigo}' ({base.familia.value}): son familias distintas."
        )
    # factor_a_base de la unidad base vale 1, pero dividimos igual por si el catálogo cambia.
    return redondear_cantidad(cantidad * a_decimal(unidad.factor_a_base) / a_decimal(base.factor_a_base))


def costo_por_unidad_base(monto_pagado, cantidad_base) -> Decimal:
    """
    Cuánto cuesta cada unidad base. Ejemplo: pagaste $1.500 por 1000 g → $1,5 por gramo.
    """
    cantidad_base = a_decimal(cantidad_base)
    if cantidad_base <= 0:
        raise ErrorUnidades("La cantidad comprada debe ser mayor que cero para calcular el costo.")
    return redondear_costo(a_decimal(monto_pagado) / cantidad_base)


def costo_promedio_ponderado(stock_actual, costo_actual, cantidad_nueva, costo_nuevo) -> Decimal:
    """
    Nuevo costo promedio tras una compra.

    Analogía: mezclar dos baldes de pintura de distinto precio; el precio del
    balde resultante depende de cuánta pintura aportó cada uno.

        (stock × costo_actual + compra × costo_nuevo) / (stock + compra)

    Si el stock actual es cero o negativo (se vendió de más antes de comprar),
    no hay nada que promediar: el costo es el de la compra nueva.
    """
    stock_actual   = a_decimal(stock_actual)
    cantidad_nueva = a_decimal(cantidad_nueva)
    if cantidad_nueva <= 0:
        raise ErrorUnidades("La cantidad comprada debe ser mayor que cero.")
    if stock_actual <= 0:
        return redondear_costo(costo_nuevo)
    total = stock_actual * a_decimal(costo_actual) + cantidad_nueva * a_decimal(costo_nuevo)
    return redondear_costo(total / (stock_actual + cantidad_nueva))


def costo_de_referencia(costo_promedio, costo_ultimo) -> Decimal:
    """El MAYOR entre el promedio ponderado y el último precio de compra."""
    return max(a_decimal(costo_promedio or 0), a_decimal(costo_ultimo or 0))
