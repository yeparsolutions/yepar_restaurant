# ============================================================
# YEPAR RESTAURANT — backend/routers/catalogo.py
# El catálogo del administrador: unidades, categorías, ítems, presentaciones,
# extras, recetas y costos. El cocinero puede LEER las recetas (sin costos).
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from esquemas import (CategoriaIn, CategoriaOut, CostoLineaOut, CostoRecetaOut, ExtraIn, ExtraOut,
                      ItemCambiosIn, ItemIn, ItemOut, LineaRecetaOut, PresentacionIn, PresentacionOut,
                      RecetaIn, RecetaOut, UnidadOut)
from errores import ErrorNegocio
from models import Item, RolUsuario, TipoItem, Usuario
from seguridad import exigir_roles, usuario_actual
from servicios import items as svc_items
from servicios.recetas import LineaReceta, calcular_costo_receta, guardar_receta
from servicios.stock import cargar_item

router = APIRouter(tags=["catálogo"])

solo_admin = exigir_roles()
admin_o_cocina = exigir_roles(RolUsuario.cocinero)


def item_out(i: Item) -> ItemOut:
    return ItemOut(
        id=i.id, tipo=i.tipo.value, nombre=i.nombre, unidad_base=i.unidad_base.codigo, categoria_id=i.categoria_id,
        precio_venta=i.precio_venta, estacion=i.estacion.value if i.estacion else None, foto_url=i.foto_url,
        codigo_barra=i.codigo_barra, stock_minimo=i.stock_minimo, costo_promedio=i.costo_promedio,
        costo_ultimo=i.costo_ultimo, costo_referencia=i.costo_referencia, agotado_manual=i.agotado_manual,
        activo=i.activo, tiene_receta=i.receta is not None)


def extra_out(db: Session, e) -> ExtraOut:
    return ExtraOut(id=e.id, nombre=e.nombre, precio=e.precio, ingrediente_id=e.ingrediente_id, cantidad=e.cantidad,
                    aplica_a_todos=e.aplica_a_todos, plato_ids=svc_items.platos_del_extra(db, e.id), activo=e.activo)


def receta_out(item: Item) -> RecetaOut:
    r = item.receta
    return RecetaOut(
        item_id=item.id, nombre=item.nombre, rendimiento=r.rendimiento, unidad=item.unidad_base.codigo,
        instrucciones=r.instrucciones,
        lineas=[LineaRecetaOut(ingrediente_id=l.ingrediente_id, nombre=l.ingrediente.nombre, cantidad=l.cantidad,
                               unidad=l.ingrediente.unidad_base.codigo, es_removible=l.es_removible, orden=l.orden)
                for l in r.lineas])


# ── Unidades y categorías ────────────────────────────────────
@router.get("/unidades", response_model=list[UnidadOut])
def unidades(db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual)):
    """El catálogo de unidades de medida (kg, g, l, ml, cc, und)."""
    return [UnidadOut(codigo=u.codigo, nombre=u.nombre, familia=u.familia.value, factor_a_base=u.factor_a_base,
                      es_base=u.es_base) for u in svc_items.listar_unidades(db)]


@router.get("/categorias", response_model=list[CategoriaOut])
def categorias(db: Session = Depends(get_db), usuario: Usuario = Depends(admin_o_cocina)):
    return [CategoriaOut(id=c.id, nombre=c.nombre, orden=c.orden)
            for c in svc_items.listar_categorias(db, usuario.empresa_id)]


@router.post("/categorias", response_model=CategoriaOut, status_code=201)
def crear_categoria(datos: CategoriaIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    c = svc_items.crear_categoria(db, empresa_id=usuario.empresa_id, **datos.model_dump())
    db.commit()
    return CategoriaOut(id=c.id, nombre=c.nombre, orden=c.orden)


# ── Ítems ────────────────────────────────────────────────────
@router.get("/items", response_model=list[ItemOut])
def listar_items(tipo: Optional[TipoItem] = None, q: Optional[str] = None, categoria_id: Optional[int] = None,
                 incluir_inactivos: bool = False, db: Session = Depends(get_db),
                 usuario: Usuario = Depends(solo_admin)):
    items = svc_items.listar_items(db, empresa_id=usuario.empresa_id, tipo=tipo, texto=q, categoria_id=categoria_id,
                                   solo_activos=not incluir_inactivos)
    return [item_out(i) for i in items]


@router.post("/items", response_model=ItemOut, status_code=201)
def crear_item(datos: ItemIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    item = svc_items.crear_item(db, empresa_id=usuario.empresa_id, **datos.model_dump())
    db.commit()
    return item_out(item)


@router.get("/items/{item_id}", response_model=ItemOut)
def ver_item(item_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    return item_out(cargar_item(db, usuario.empresa_id, item_id))


@router.patch("/items/{item_id}", response_model=ItemOut)
def cambiar_item(item_id: int, datos: ItemCambiosIn, db: Session = Depends(get_db),
                 usuario: Usuario = Depends(solo_admin)):
    item = svc_items.actualizar_item(db, empresa_id=usuario.empresa_id, item_id=item_id,
                                     **datos.model_dump(exclude_unset=True))
    db.commit()
    return item_out(item)


@router.post("/items/{item_id}/presentaciones", response_model=PresentacionOut, status_code=201)
def crear_presentacion(item_id: int, datos: PresentacionIn, db: Session = Depends(get_db),
                       usuario: Usuario = Depends(solo_admin)):
    """Una forma de comprar el ítem: 'Caja 12 un', 'Saco 25 kg'."""
    p = svc_items.crear_presentacion(db, empresa_id=usuario.empresa_id, item_id=item_id, **datos.model_dump())
    db.commit()
    return PresentacionOut(id=p.id, item_id=p.item_id, nombre=p.nombre, cantidad_en_base=p.cantidad_en_base,
                           es_defecto=p.es_defecto)


# ── Extras ───────────────────────────────────────────────────
@router.get("/extras", response_model=list[ExtraOut])
def listar_extras(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    return [extra_out(db, e) for e in svc_items.listar_extras(db, usuario.empresa_id)]


@router.post("/extras", response_model=ExtraOut, status_code=201)
def crear_extra(datos: ExtraIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    e = svc_items.crear_extra(db, empresa_id=usuario.empresa_id, **datos.model_dump())
    db.commit()
    return extra_out(db, e)


# ── Recetas y costos ─────────────────────────────────────────
@router.put("/items/{item_id}/receta", response_model=RecetaOut)
def guardar(item_id: int, datos: RecetaIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """Crea o reemplaza la receta de un componente o un plato (valida unidades, duplicados y ciclos)."""
    guardar_receta(
        db, empresa_id=usuario.empresa_id, item_id=item_id, rendimiento=datos.rendimiento,
        rendimiento_unidad=datos.rendimiento_unidad, instrucciones=datos.instrucciones,
        lineas=[LineaReceta(l.ingrediente_id, l.cantidad, l.unidad, l.es_removible) for l in datos.lineas])
    db.commit()
    return receta_out(cargar_item(db, usuario.empresa_id, item_id))


@router.get("/items/{item_id}/receta", response_model=RecetaOut)
def ver_receta(item_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(admin_o_cocina)):
    """El cocinero ve la receta (ingredientes y cantidades), sin costos."""
    item = cargar_item(db, usuario.empresa_id, item_id)
    if item.receta is None:
        raise ErrorNegocio(f"'{item.nombre}' no tiene receta.")
    return receta_out(item)


@router.get("/items/{item_id}/costo", response_model=CostoRecetaOut)
def costo(item_id: int, sin: list[int] = Query(default=[]), db: Session = Depends(get_db),
          usuario: Usuario = Depends(solo_admin)):
    """
    Costo de fabricación de un plato o componente, bajando por los componentes hasta la materia prima,
    con su margen contra el precio de venta. `sin` quita ingredientes removibles (costo real de "sin cebolla").
    """
    item = cargar_item(db, usuario.empresa_id, item_id)
    c = calcular_costo_receta(db, empresa_id=usuario.empresa_id, item_id=item.id, sin_ingredientes=sin)
    margen = None
    if item.precio_venta and item.precio_venta > 0:
        margen = (item.precio_venta - c.costo_unitario) / item.precio_venta * 100
    return CostoRecetaOut(
        item_id=item.id, nombre=item.nombre, rendimiento=c.rendimiento, costo_total=c.costo_total,
        costo_unitario=c.costo_unitario, precio_venta=item.precio_venta, margen_pct=margen,
        lineas=[CostoLineaOut(ingrediente_id=l.ingrediente_id, nombre=l.nombre, cantidad=l.cantidad,
                              costo_unitario=l.costo_unitario, costo_linea=l.costo_linea) for l in c.lineas])
