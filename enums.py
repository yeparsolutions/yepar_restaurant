# ============================================================
# YEPAR RESTAURANT — backend/models/enums.py
# Listas cerradas de valores que usa el modelo de datos.
#
# LECCIÓN APRENDIDA DE CARORA (YeparStock): allá los Enum se
# guardaban como tipos nativos de PostgreSQL, y agregar un valor
# nuevo obligaba a escribir scripts de migración (fix_enum.py,
# fix_enum2.py...). Acá los guardamos como TEXTO simple: agregar
# un valor nuevo es solo agregar una línea en la clase Python.
#
# Analogía: en vez de grabar los nombres de las salas en el
# cemento del edificio, los dejamos en un letrero que se cambia
# cuando haga falta.
# ============================================================

import enum

from sqlalchemy import Enum


def columna_enum(clase):
    """
    Devuelve el tipo de columna para guardar un Enum como texto (VARCHAR).
    Guarda el VALOR ("materia_prima"), no el nombre de Python, y rechaza
    textos que no pertenezcan a la lista.
    """
    return Enum(
        clase,
        native_enum=False,          # texto simple, sin tipo nativo de PostgreSQL
        length=30,
        validate_strings=True,      # un texto inválido falla antes de llegar a la base
        values_callable=lambda e: [m.value for m in e],
    )


# ── Unidades de medida ───────────────────────────────────────
class FamiliaUnidad(str, enum.Enum):
    """Solo se puede convertir DENTRO de una misma familia (nunca peso ↔ volumen)."""
    peso    = "peso"       # mg, g, kg
    volumen = "volumen"    # ml, cc, l
    unidad  = "unidad"     # und


# ── Ítems del inventario ─────────────────────────────────────
class TipoItem(str, enum.Enum):
    """
    Analogía de la casa:
      materia_prima      = los ladrillos (tomate, harina, licor)
      componente         = paredes prefabricadas (salsa de ajo, masa)
      vendible_preparado = la casa terminada (hamburguesa, trago)
      vendible_reventa   = se compra y se vende tal cual (agua, bebida en lata)
    """
    materia_prima      = "materia_prima"
    componente         = "componente"
    vendible_preparado = "vendible_preparado"
    vendible_reventa   = "vendible_reventa"


# Lo que ve el mesero en la carta.
TIPOS_VENDIBLES = frozenset({TipoItem.vendible_preparado, TipoItem.vendible_reventa})

# Lo que lleva receta (ingredientes + cantidades).
TIPOS_CON_RECETA = frozenset({TipoItem.componente, TipoItem.vendible_preparado})


# ── Stock ────────────────────────────────────────────────────
class TipoMovimientoStock(str, enum.Enum):
    compra             = "compra"              # entra por recepción física de una factura
    produccion_consumo = "produccion_consumo"  # sale: insumo gastado al producir un lote
    produccion_entrada = "produccion_entrada"  # entra: componente recién producido
    consumo_venta      = "consumo_venta"       # sale: lo descontado cuando cocina marca "listo"
    merma              = "merma"               # sale: pérdida (ver MotivoMerma)
    ajuste_inventario  = "ajuste_inventario"   # +/-: resultado aprobado de un conteo físico


class MotivoMerma(str, enum.Enum):
    vencido                     = "vencido"
    danado                      = "danado"
    error_preparacion           = "error_preparacion"
    sobrante                    = "sobrante"
    derrame                     = "derrame"
    cancelacion_en_preparacion  = "cancelacion_en_preparacion"   # plato cancelado cuando ya se estaba cocinando


# ── Usuarios ─────────────────────────────────────────────────
class RolUsuario(str, enum.Enum):
    administrador = "administrador"
    cajero        = "cajero"
    mesero        = "mesero"
    cocinero      = "cocinero"


class EstacionCocina(str, enum.Enum):
    """El barman es simplemente un cocinero con estación 'barra'."""
    cocina = "cocina"
    barra  = "barra"
