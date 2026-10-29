# ============================================================
# YEPAR RESTAURANT — backend/servicios/items.py
# El catálogo: categorías, ítems (los cuatro tipos), presentaciones y extras.
#
# Analogía: es el "libro de la despensa y la carta". Aquí el administrador
# da de alta cada cosa del restaurante: lo que se compra (tomates), lo que
# se prepara en lote (salsa de ajo), lo que se cocina al momento
# (hamburguesa) y lo que se revende (cola en lata).
#
# Una vez creado, el TIPO y la UNIDAD BASE de un ítem no cambian: ya hay
# recetas, stock y movimientos medidos con esa regla.
# Los servicios no hacen commit (lo decide quien llama).
# ============================================================

from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import (CategoriaItem, EstacionCocina, Extra, ExtraPlato, Item, ItemPresentacion,
                    TipoItem, Unidad)
from servicios.recetas import TIPOS_INGREDIENTE
from servicios.stock import cargar_item
from unidades import a_decimal, exigir_unidad_base, redondear_cantidad

CAMPOS_EDITABLES = ("nombre", "precio_venta", "categoria_id", "stock_minimo", "estacion", "foto_url",
                    "codigo_barra", "activo")


def _limpio(texto: Optional[str]) -> Optional[str]:
    texto = (texto or "").strip()
    return texto or None


def _dinero(valor, nombre: str) -> Decimal:
    try:
        dinero = a_decimal(valor).quantize(Decimal("0.01"))
    except Exception:
        raise ErrorNegocio(f"{nombre} no es un monto válido.")
    if dinero < 0:
        raise ErrorNegocio(f"{nombre} no puede ser negativo.")
    return dinero


# ------------------------------------------------------------
# Unidades y categorías
# ------------------------------------------------------------
def listar_unidades(db: Session) -> list:
    return db.query(Unidad).order_by(Unidad.familia, Unidad.factor_a_base).all()


def crear_categoria(db: Session, *, empresa_id: int, nombre: str, orden: int = 0) -> CategoriaItem:
    nombre = _limpio(nombre)
    if nombre is None:
        raise ErrorNegocio("La categoría necesita un nombre.")
    existe = db.query(CategoriaItem).filter(CategoriaItem.empresa_id == empresa_id,
                                            func.lower(CategoriaItem.nombre) == nombre.lower()).first()
    if existe is not None:
        raise ErrorNegocio(f"Ya existe la categoría '{nombre}'.")
    categoria = CategoriaItem(empresa_id=empresa_id, nombre=nombre, orden=orden)
    db.add(categoria)
    db.flush()
    return categoria


def listar_categorias(db: Session, empresa_id: int) -> list:
    return db.query(CategoriaItem).filter_by(empresa_id=empresa_id).order_by(CategoriaItem.orden,
                                                                              CategoriaItem.nombre).all()


def _validar_categoria(db: Session, empresa_id: int, categoria_id: Optional[int]):
    if categoria_id is None:
        return
    categoria = db.get(CategoriaItem, categoria_id)
    if categoria is None or categoria.empresa_id != empresa_id:
        raise ErrorNoEncontrado("La categoría no existe.")


# ------------------------------------------------------------
# Ítems
# ------------------------------------------------------------
def _validar_campos(db: Session, empresa_id: int, tipo: TipoItem, datos: dict, *, item_id: Optional[int] = None):
    """Reglas comunes de crear y editar: nombre, precio, estación, stock mínimo, código de barra."""
    vendible = tipo in (TipoItem.vendible_preparado, TipoItem.vendible_reventa)
    if "nombre" in datos:
        nombre = _limpio(datos["nombre"])
        if nombre is None:
            raise ErrorNegocio("El ítem necesita un nombre.")
        datos["nombre"] = nombre
        repetido = db.query(Item).filter(Item.empresa_id == empresa_id,
                                         func.lower(Item.nombre) == nombre.lower())
        if item_id is not None:
            repetido = repetido.filter(Item.id != item_id)
        if repetido.first() is not None:
            raise ErrorNegocio(f"Ya existe un ítem llamado '{nombre}'.")
    if "precio_venta" in datos and datos["precio_venta"] is not None:
        if not vendible:
            raise ErrorNegocio("Solo los ítems vendibles llevan precio de venta.")
        datos["precio_venta"] = _dinero(datos["precio_venta"], "El precio de venta")
    if "estacion" in datos and datos["estacion"] is not None:
        if not vendible:
            raise ErrorNegocio("Solo los ítems vendibles se envían a una estación (cocina o barra).")
        datos["estacion"] = EstacionCocina(datos["estacion"])
    if "stock_minimo" in datos:
        minimo = redondear_cantidad(a_decimal(datos["stock_minimo"] if datos["stock_minimo"] is not None else 0))
        if minimo < 0:
            raise ErrorNegocio("El stock mínimo no puede ser negativo.")
        datos["stock_minimo"] = minimo
    if "codigo_barra" in datos:
        datos["codigo_barra"] = _limpio(datos["codigo_barra"])
        if datos["codigo_barra"] is not None:
            repetido = db.query(Item).filter_by(empresa_id=empresa_id, codigo_barra=datos["codigo_barra"])
            if item_id is not None:
                repetido = repetido.filter(Item.id != item_id)
            if repetido.first() is not None:
                raise ErrorNegocio("Ese código de barra ya está en otro ítem.")
    if "categoria_id" in datos:
        _validar_categoria(db, empresa_id, datos["categoria_id"])


def crear_item(db: Session, *, empresa_id: int, tipo: TipoItem, nombre: str, unidad_base: str,
               precio_venta=None, categoria_id: Optional[int] = None, stock_minimo=0,
               estacion: Optional[str] = None, foto_url: Optional[str] = None,
               codigo_barra: Optional[str] = None) -> Item:
    """
    Da de alta un ítem. `unidad_base` es el código de una unidad base ('g', 'ml' o 'und'):
    en ella se guardará todo su stock y sus recetas.
    """
    tipo = TipoItem(tipo)
    datos = dict(nombre=nombre, precio_venta=precio_venta, estacion=estacion, stock_minimo=stock_minimo,
                 codigo_barra=codigo_barra, categoria_id=categoria_id)
    _validar_campos(db, empresa_id, tipo, datos)

    unidad = db.query(Unidad).filter_by(codigo=unidad_base).one_or_none()
    if unidad is None:
        raise ErrorNegocio(f"La unidad '{unidad_base}' no existe en el catálogo.")
    exigir_unidad_base(unidad)

    item = Item(empresa_id=empresa_id, tipo=tipo, unidad_base_id=unidad.id, foto_url=_limpio(foto_url), **datos)
    db.add(item)
    db.flush()
    return item


def actualizar_item(db: Session, *, empresa_id: int, item_id: int, **cambios) -> Item:
    """
    Cambia solo los campos indicados (nombre, precio_venta, categoria_id, stock_minimo,
    estacion, foto_url, codigo_barra, activo). El tipo y la unidad base no se cambian.
    """
    item = cargar_item(db, empresa_id, item_id)
    desconocidos = set(cambios) - set(CAMPOS_EDITABLES)
    if desconocidos:
        raise ErrorNegocio("No se puede cambiar: " + ", ".join(sorted(desconocidos)) +
                           ". El tipo y la unidad base de un ítem no se modifican.")
    datos = dict(cambios)
    _validar_campos(db, empresa_id, item.tipo, datos, item_id=item.id)
    if "foto_url" in datos:
        datos["foto_url"] = _limpio(datos["foto_url"])
    for campo, valor in datos.items():
        setattr(item, campo, valor)
    db.flush()
    return item


def listar_items(db: Session, *, empresa_id: int, tipo: Optional[TipoItem] = None, texto: Optional[str] = None,
                 categoria_id: Optional[int] = None, solo_activos: bool = True) -> list:
    consulta = db.query(Item).filter_by(empresa_id=empresa_id)
    if tipo is not None:
        consulta = consulta.filter_by(tipo=tipo)
    if categoria_id is not None:
        consulta = consulta.filter_by(categoria_id=categoria_id)
    if solo_activos:
        consulta = consulta.filter(Item.activo.is_(True))
    if texto and texto.strip():
        consulta = consulta.filter(func.lower(Item.nombre).contains(texto.strip().lower()))
    return consulta.order_by(Item.nombre).all()


# ------------------------------------------------------------
# Presentaciones (caja de 12, saco de 25 kg)
# ------------------------------------------------------------
def crear_presentacion(db: Session, *, empresa_id: int, item_id: int, nombre: str, cantidad_en_base,
                       es_defecto: bool = False) -> ItemPresentacion:
    item = cargar_item(db, empresa_id, item_id)
    nombre = _limpio(nombre)
    if nombre is None:
        raise ErrorNegocio("La presentación necesita un nombre.")
    cantidad = redondear_cantidad(a_decimal(cantidad_en_base))
    if cantidad <= 0:
        raise ErrorNegocio("La presentación debe traer una cantidad mayor que cero.")
    if any(p.nombre.lower() == nombre.lower() for p in item.presentaciones):
        raise ErrorNegocio(f"'{item.nombre}' ya tiene una presentación '{nombre}'.")
    if es_defecto:
        for otra in item.presentaciones:
            otra.es_defecto = False
    presentacion = ItemPresentacion(item_id=item.id, nombre=nombre, cantidad_en_base=cantidad, es_defecto=es_defecto)
    item.presentaciones.append(presentacion)
    db.flush()
    return presentacion


# ------------------------------------------------------------
# Extras ("extra tocineta")
# ------------------------------------------------------------
def crear_extra(db: Session, *, empresa_id: int, nombre: str, precio, ingrediente_id: int, cantidad,
                aplica_a_todos: bool = True, plato_ids: Iterable[int] = ()) -> Extra:
    """
    Un adicional que se cobra aparte y descuenta `cantidad` (en unidad base) de un ingrediente.
    Si no aplica a todos los platos, hay que indicar en cuáles se ofrece.
    """
    nombre = _limpio(nombre)
    if nombre is None:
        raise ErrorNegocio("El extra necesita un nombre.")
    if db.query(Extra).filter(Extra.empresa_id == empresa_id, func.lower(Extra.nombre) == nombre.lower()).first():
        raise ErrorNegocio(f"Ya existe un extra llamado '{nombre}'.")
    precio = _dinero(precio, "El precio del extra")
    cantidad = redondear_cantidad(a_decimal(cantidad))
    if cantidad <= 0:
        raise ErrorNegocio("La cantidad del extra debe ser mayor que cero.")
    ingrediente = cargar_item(db, empresa_id, ingrediente_id)
    if ingrediente.tipo not in TIPOS_INGREDIENTE:
        raise ErrorNegocio(f"'{ingrediente.nombre}' no puede usarse como extra: no es un ingrediente.")
    platos = []
    for plato_id in dict.fromkeys(plato_ids):
        plato = cargar_item(db, empresa_id, plato_id)
        if plato.tipo != TipoItem.vendible_preparado:
            raise ErrorNegocio(f"'{plato.nombre}' no es un plato preparado: no admite extras.")
        platos.append(plato)
    if not aplica_a_todos and not platos:
        raise ErrorNegocio("Indica en qué platos se ofrece el extra (o márcalo para todos).")

    extra = Extra(empresa_id=empresa_id, nombre=nombre, precio=precio, ingrediente_id=ingrediente.id,
                  cantidad=cantidad, aplica_a_todos=aplica_a_todos)
    db.add(extra)
    db.flush()
    if not aplica_a_todos:
        db.add_all(ExtraPlato(extra_id=extra.id, item_id=p.id) for p in platos)
        db.flush()
    return extra


def listar_extras(db: Session, empresa_id: int) -> list:
    return db.query(Extra).filter_by(empresa_id=empresa_id).order_by(Extra.nombre).all()


def platos_del_extra(db: Session, extra_id: int) -> list:
    """Ids de los platos donde se ofrece un extra que no aplica a todos."""
    return [fila.item_id for fila in db.query(ExtraPlato).filter_by(extra_id=extra_id).all()]
