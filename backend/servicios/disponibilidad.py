# ============================================================
# YEPAR RESTAURANT — backend/servicios/disponibilidad.py
# ¿Alcanza para este plato? Alertas de stock bajo y lista de compras.
#
# Analogía: es el "jefe de sala" que mira la despensa antes de
# dejar que el mesero prometa un plato:
#   - Al mesero le responde "OK, alcanza" o "ojo, falta X".
#   - Al administrador le avisa qué ingredientes están por acabarse.
#   - Y le deja armada una lista de compras para el mercado.
#
# Todo aquí es de SOLO LECTURA: no crea filas ni mueve stock.
# Lo que está reservado por pedidos en cocina ya no cuenta como
# disponible (disponible = físico − reservado).
# ============================================================

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from models import Item, StockSucursal, TipoItem
from servicios.reservas import calcular_necesidad
from servicios.stock import cargar_item, validar_sucursal
from unidades import costo_de_referencia, redondear_cantidad

CERO = Decimal("0")
TIPOS_QUE_SE_COMPRAN = (TipoItem.materia_prima, TipoItem.vendible_reventa)


@dataclass
class Falta:
    """Un ingrediente que no alcanza para lo pedido."""
    item_id: int
    nombre: str
    falta: Decimal                 # cuánto falta (unidad base); 0 si solo está marcado agotado
    agotado_manual: bool = False   # el cocinero apretó "se acabó"


@dataclass
class Disponibilidad:
    item_id: int
    nombre: str
    alcanza: bool
    faltas: list = field(default_factory=list)


@dataclass
class AlertaStock:
    item_id: int
    nombre: str
    tipo: TipoItem
    disponible: Decimal
    stock_minimo: Decimal
    se_produce: bool               # componente: se repone produciendo, no comprando


@dataclass
class LineaCompra:
    item_id: int
    nombre: str
    cantidad_base: Decimal                      # lo que conviene reponer, en unidad base
    unidad: str                                 # código de la unidad base ('g', 'ml', 'und')
    presentacion: Optional[str] = None          # ej. "Caja 12 un"
    cantidad_presentacion: Optional[int] = None # cuántas cajas/sacos comprar (redondeado hacia arriba)
    costo_estimado: Decimal = CERO


@dataclass
class ListaCompras:
    lineas: list = field(default_factory=list)
    costo_total_estimado: Decimal = CERO


# ------------------------------------------------------------
# Ayudas
# ------------------------------------------------------------
def _mapa_disponible(db: Session, empresa_id: int, sucursal_id: int) -> dict:
    """{item_id: disponible} de toda la sucursal en una sola consulta."""
    filas = db.query(StockSucursal).filter_by(empresa_id=empresa_id, sucursal_id=sucursal_id).all()
    return {f.item_id: f.disponible for f in filas}


def _evaluar(db, item: Item, disponibles: dict, *, cantidad=1, sin_ingredientes=(), extra_ids=()) -> Disponibilidad:
    necesidad = calcular_necesidad(db, empresa_id=item.empresa_id, item_id=item.id, cantidad=cantidad,
                                   sin_ingredientes=sin_ingredientes, extra_ids=extra_ids)
    faltas = []
    for ingrediente_id, necesita in necesidad.items():
        ingrediente = db.get(Item, ingrediente_id)
        hay = disponibles.get(ingrediente_id, CERO)
        if ingrediente.agotado_manual:
            faltas.append(Falta(ingrediente_id, ingrediente.nombre, max(necesita - hay, CERO), True))
        elif hay < necesita:
            faltas.append(Falta(ingrediente_id, ingrediente.nombre, redondear_cantidad(necesita - hay)))
    return Disponibilidad(item_id=item.id, nombre=item.nombre, alcanza=not faltas, faltas=faltas)


# ------------------------------------------------------------
# Para el mesero
# ------------------------------------------------------------
def revisar_disponibilidad(
    db: Session, *,
    empresa_id: int,
    sucursal_id: int,
    item_id: int,
    cantidad=1,
    sin_ingredientes: Iterable[int] = (),
    extra_ids: Iterable[int] = (),
) -> Disponibilidad:
    """¿Alcanza para `cantidad` de este plato (con sus quitados y extras)? Si no, dice qué falta."""
    validar_sucursal(db, empresa_id, sucursal_id)
    item = cargar_item(db, empresa_id, item_id)
    return _evaluar(db, item, _mapa_disponible(db, empresa_id, sucursal_id), cantidad=cantidad,
                    sin_ingredientes=sin_ingredientes, extra_ids=extra_ids)


def catalogo_mesero(db: Session, *, empresa_id: int, sucursal_id: int) -> list:
    """
    Lo que ve el mesero: solo los vendibles activos, cada uno con su semáforo
    (alcanza para 1 unidad, o qué falta). Los ingredientes nunca aparecen.
    """
    validar_sucursal(db, empresa_id, sucursal_id)
    disponibles = _mapa_disponible(db, empresa_id, sucursal_id)
    vendibles = (db.query(Item)
                 .filter(Item.empresa_id == empresa_id, Item.activo.is_(True),
                         Item.tipo.in_((TipoItem.vendible_preparado, TipoItem.vendible_reventa)))
                 .order_by(Item.nombre).all())
    resultado = []
    for item in vendibles:
        if item.receta is None and item.tipo == TipoItem.vendible_preparado:
            continue               # plato sin receta todavía: no se ofrece
        resultado.append(_evaluar(db, item, disponibles))
    return resultado


# ------------------------------------------------------------
# Para el administrador
# ------------------------------------------------------------
def alertas_stock_bajo(db: Session, *, empresa_id: int, sucursal_id: int) -> list:
    """
    Ingredientes cuyo disponible está bajo su stock mínimo (solo los que tienen
    un mínimo definido). Los más críticos (más lejos del mínimo) van primero.
    """
    validar_sucursal(db, empresa_id, sucursal_id)
    disponibles = _mapa_disponible(db, empresa_id, sucursal_id)
    ingredientes = (db.query(Item)
                    .filter(Item.empresa_id == empresa_id, Item.activo.is_(True), Item.stock_minimo > 0,
                            Item.tipo.in_((TipoItem.materia_prima, TipoItem.componente, TipoItem.vendible_reventa)))
                    .all())
    alertas = [
        AlertaStock(item_id=i.id, nombre=i.nombre, tipo=i.tipo, disponible=disponibles.get(i.id, CERO),
                    stock_minimo=i.stock_minimo, se_produce=i.tipo == TipoItem.componente)
        for i in ingredientes if disponibles.get(i.id, CERO) < i.stock_minimo
    ]
    return sorted(alertas, key=lambda a: a.disponible - a.stock_minimo)


def lista_compras_sugerida(
    db: Session, *,
    empresa_id: int,
    sucursal_id: int,
    factor_reposicion: Decimal = Decimal("2"),
) -> ListaCompras:
    """
    Qué comprar: cada ingrediente bajo su mínimo se repone hasta
    `factor_reposicion` × stock mínimo (por defecto el doble, para no volver a
    quedarse corto al día siguiente). Los componentes no se compran, se producen,
    así que no salen aquí (sí salen en las alertas).
    Si el ítem tiene presentación por defecto ("Caja 12 un") se sugiere en cajas,
    redondeando hacia arriba.
    """
    lista = ListaCompras()
    for alerta in alertas_stock_bajo(db, empresa_id=empresa_id, sucursal_id=sucursal_id):
        if alerta.tipo not in TIPOS_QUE_SE_COMPRAN:
            continue
        item = db.get(Item, alerta.item_id)
        objetivo = item.stock_minimo * factor_reposicion
        faltante = redondear_cantidad(objetivo - alerta.disponible)
        linea = LineaCompra(
            item_id=item.id, nombre=item.nombre, cantidad_base=faltante, unidad=item.unidad_base.codigo,
            costo_estimado=(faltante * costo_de_referencia(item.costo_promedio, item.costo_ultimo)).quantize(Decimal("0.01")))
        defecto = next((p for p in item.presentaciones if p.es_defecto), None)
        if defecto is not None:
            linea.presentacion = defecto.nombre
            linea.cantidad_presentacion = int((faltante / defecto.cantidad_en_base).to_integral_value(ROUND_CEILING))
        lista.lineas.append(linea)
        lista.costo_total_estimado += linea.costo_estimado
    return lista
