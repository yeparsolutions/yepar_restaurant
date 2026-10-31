# ============================================================
# YEPAR RESTAURANT — backend/servicios/recetas.py
# Guardar recetas con validaciones y calcular su costo teórico.
#
# Analogía: este servicio es el "jefe de cocina" que revisa cada
# receta antes de archivarla: ¿los ingredientes existen?, ¿las
# unidades tienen sentido?, ¿nadie pide algo que se pide a sí mismo?
#
# Una receta puede usar otro componente (la salsa de ajo dentro de la
# hamburguesa). Eso arma un "árbol" de recetas; si el árbol diera la
# vuelta sobre sí mismo (A usa B y B usa A) el costo sería infinito,
# por eso se detectan los ciclos antes de guardar.
# ============================================================

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import Item, Receta, RecetaLinea, TipoItem, Unidad
from servicios.stock import cargar_item
from unidades import (a_decimal, convertir_a_unidad_base, redondear_cantidad,
                      redondear_costo)

# Qué tipos de ítem pueden ser ingrediente. Un vendible de reventa sí puede
# (ej. la lata de cola dentro de un trago); un plato terminado no.
TIPOS_INGREDIENTE = frozenset({TipoItem.materia_prima, TipoItem.componente, TipoItem.vendible_reventa})


@dataclass(frozen=True)
class LineaReceta:
    """
    Un ingrediente pedido por el usuario al armar una receta.

    `unidad` es el código de una unidad del catálogo ('g', 'kg', 'ml', 'l'...).
    Si es None, `cantidad` ya viene en la unidad base del ingrediente.
    """
    ingrediente_id: int
    cantidad: object                  # Decimal, int, float o str
    unidad: Optional[str] = None
    es_removible: bool = False


@dataclass
class LineaCosto:
    """Una línea del desglose de costo de una receta."""
    ingrediente_id: int
    nombre: str
    cantidad: Decimal                 # en unidad base del ingrediente
    costo_unitario: Decimal           # $ por unidad base del ingrediente
    costo_linea: Decimal              # cantidad × costo_unitario


@dataclass
class CostoReceta:
    """Costo teórico de producir una receta."""
    item_id: int
    rendimiento: Decimal
    costo_total: Decimal              # costo de TODA la receta
    costo_unitario: Decimal           # costo_total / rendimiento (por unidad base producida)
    lineas: list = field(default_factory=list)


# ------------------------------------------------------------
# Ayudas internas
# ------------------------------------------------------------
def _buscar_unidad(db: Session, codigo: str) -> Unidad:
    unidad = db.query(Unidad).filter_by(codigo=codigo).one_or_none()
    if unidad is None:
        raise ErrorNegocio(f"La unidad '{codigo}' no existe en el catálogo.")
    return unidad


def _a_base(db: Session, item: Item, cantidad, unidad_codigo: Optional[str]) -> Decimal:
    """Pasa una cantidad a la unidad base del ítem (si ya viene en base, solo la valida)."""
    if unidad_codigo is None:
        valor = redondear_cantidad(a_decimal(cantidad))
        if valor <= 0:
            raise ErrorNegocio(f"La cantidad de '{item.nombre}' debe ser mayor que cero.")
        return valor
    return convertir_a_unidad_base(item, cantidad, unidad=_buscar_unidad(db, unidad_codigo))


def _hay_ciclo(db: Session, item_id: int, ingredientes_ids: Iterable[int]) -> bool:
    """
    ¿Alguno de estos ingredientes, directa o indirectamente, necesita al ítem?
    Recorre las recetas hacia abajo; si vuelve a encontrar el ítem de partida,
    la receta daría una vuelta completa.
    """
    pendientes = list(ingredientes_ids)
    visitados: set = set()
    while pendientes:
        actual = pendientes.pop()
        if actual == item_id:
            return True
        if actual in visitados:
            continue
        visitados.add(actual)
        receta = db.query(Receta).filter_by(item_id=actual).one_or_none()
        if receta is not None:
            pendientes.extend(linea.ingrediente_id for linea in receta.lineas)
    return False


# ------------------------------------------------------------
# Guardar una receta
# ------------------------------------------------------------
def guardar_receta(
    db: Session, *,
    empresa_id: int,
    item_id: int,
    rendimiento,
    lineas: list,
    rendimiento_unidad: Optional[str] = None,
    instrucciones: Optional[str] = None,
) -> Receta:
    """
    Crea la receta del ítem, o la reemplaza completa si ya tenía una.

    - `rendimiento`: cuánto sale de producir la receta (1 para un plato, 1000 g
      de salsa...). Con `rendimiento_unidad` puede darse en otra unidad ("1" "kg").
    - `lineas`: lista de LineaReceta.
    """
    item = cargar_item(db, empresa_id, item_id)
    if not item.lleva_receta:
        raise ErrorNegocio(f"'{item.nombre}' es de tipo '{item.tipo.value}' y no lleva receta.")
    if not lineas:
        raise ErrorNegocio("Una receta necesita al menos un ingrediente.")

    rendimiento_base = _a_base(db, item, rendimiento, rendimiento_unidad)

    ids = [linea.ingrediente_id for linea in lineas]
    if len(ids) != len(set(ids)):
        raise ErrorNegocio("Un ingrediente no puede repetirse dentro de la misma receta.")

    # Validar cada ingrediente y pasar su cantidad a unidad base.
    preparadas = []
    for orden, linea in enumerate(lineas, start=1):
        if linea.ingrediente_id == item.id:
            raise ErrorNegocio(f"'{item.nombre}' no puede ser ingrediente de sí mismo.")
        ingrediente = cargar_item(db, empresa_id, linea.ingrediente_id)
        if ingrediente.tipo not in TIPOS_INGREDIENTE:
            raise ErrorNegocio(
                f"'{ingrediente.nombre}' es de tipo '{ingrediente.tipo.value}' y no puede ser ingrediente.")
        cantidad_base = _a_base(db, ingrediente, linea.cantidad, linea.unidad)
        preparadas.append((ingrediente.id, cantidad_base, linea.es_removible, orden))

    if _hay_ciclo(db, item.id, ids):
        raise ErrorNegocio(
            f"Receta circular: alguno de los ingredientes de '{item.nombre}' "
            f"necesita a '{item.nombre}' para prepararse.")

    receta = item.receta
    if receta is None:
        receta = Receta(empresa_id=empresa_id, rendimiento=rendimiento_base,
                        instrucciones=instrucciones)
        # Asignarla por la relación (y no solo por item_id) deja `item.receta`
        # al día dentro de esta misma sesión, sin esperar a recargar el ítem.
        item.receta = receta
        db.flush()
    else:
        receta.rendimiento = rendimiento_base
        receta.instrucciones = instrucciones
        # Primero borramos las líneas viejas y lo confirmamos en la sesión: si
        # no, al reinsertar el mismo ingrediente chocaría con la restricción de
        # "no repetir ingrediente" antes de que se alcance a borrar el anterior.
        receta.lineas.clear()
        db.flush()

    for ingrediente_id, cantidad_base, es_removible, orden in preparadas:
        receta.lineas.append(RecetaLinea(ingrediente_id=ingrediente_id, cantidad=cantidad_base,
                                         es_removible=es_removible, orden=orden))
    db.flush()
    return receta


# ------------------------------------------------------------
# Costo teórico
# ------------------------------------------------------------
def _costo_exacto_por_unidad(db: Session, item: Item, en_curso: set) -> Decimal:
    """
    Costo exacto (sin redondear) de UNA unidad base de un ítem.
    - Con receta (componente): suma de sus ingredientes dividida por su rendimiento.
    - Sin receta (materia prima, reventa, o componente aún sin receta): su costo de referencia.
    """
    receta = item.receta
    if receta is None:
        return item.costo_referencia
    if item.id in en_curso:
        raise ErrorNegocio(f"Receta circular detectada en '{item.nombre}'.")
    en_curso = en_curso | {item.id}
    total = sum(
        (linea.cantidad * _costo_exacto_por_unidad(db, linea.ingrediente, en_curso)
         for linea in receta.lineas),
        Decimal("0"),
    )
    return total / receta.rendimiento


def calcular_costo_receta(
    db: Session, *,
    empresa_id: int,
    item_id: int,
    sin_ingredientes: Iterable[int] = (),
) -> CostoReceta:
    """
    Costo teórico de producir una receta, bajando por los componentes hasta
    las materias primas y usando su costo de referencia (el mayor entre el
    promedio ponderado y el último precio de compra).

    `sin_ingredientes` sirve para el costo REAL de un pedido: si el cliente
    pidió "sin cebolla", se pasa el id de la cebolla y ese costo no se suma.
    (Solo se pueden quitar los ingredientes marcados como removibles.)
    """
    item = cargar_item(db, empresa_id, item_id)
    receta = item.receta
    if receta is None:
        raise ErrorNegocio(f"'{item.nombre}' no tiene receta.")

    quitados = set(sin_ingredientes)
    no_removibles = [
        linea.ingrediente.nombre for linea in receta.lineas
        if linea.ingrediente_id in quitados and not linea.es_removible
    ]
    if no_removibles:
        raise ErrorNegocio("No se pueden quitar ingredientes que no son removibles: "
                           + ", ".join(no_removibles) + ".")

    desglose = []
    for linea in receta.lineas:
        if linea.ingrediente_id in quitados:
            continue
        unitario = _costo_exacto_por_unidad(db, linea.ingrediente, {item.id})
        desglose.append(LineaCosto(
            ingrediente_id=linea.ingrediente_id,
            nombre=linea.ingrediente.nombre,
            cantidad=linea.cantidad,
            costo_unitario=redondear_costo(unitario),
            costo_linea=linea.cantidad * unitario,
        ))

    total = sum((l.costo_linea for l in desglose), Decimal("0"))
    return CostoReceta(
        item_id=item.id,
        rendimiento=receta.rendimiento,
        costo_total=total,
        costo_unitario=redondear_costo(total / receta.rendimiento),
        lineas=desglose,
    )
