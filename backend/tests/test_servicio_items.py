# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_items.py
# Pruebas del catálogo (servicios/items.py).
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest

from errores import ErrorNegocio, ErrorNoEncontrado
from models import EstacionCocina, TipoItem
from servicios.items import (actualizar_item, crear_categoria, crear_extra, crear_item, crear_presentacion,
                             listar_categorias, listar_extras, listar_items, platos_del_extra)
from unidades import ErrorUnidades

D = Decimal


def nuevo(db, empresa, nombre="Tomate", tipo=TipoItem.materia_prima, unidad="g", **datos):
    return crear_item(db, empresa_id=empresa.id, tipo=tipo, nombre=nombre, unidad_base=unidad, **datos)


# ── Crear ítems ──────────────────────────────────────────────
def test_crear_materia_prima_en_gramos(db, u, local):
    empresa, _ = local
    item = nuevo(db, empresa, stock_minimo=1000)
    assert (item.tipo, item.nombre, item.unidad_base.codigo, item.stock_minimo) == \
        (TipoItem.materia_prima, "Tomate", "g", D("1000.000"))
    assert item.costo_promedio == 0 and item.activo and item.precio_venta is None


def test_crear_un_plato_con_precio_y_estacion(db, u, local):
    empresa, _ = local
    cat = crear_categoria(db, empresa_id=empresa.id, nombre="Hamburguesas")
    plato = nuevo(db, empresa, "Hamburguesa", TipoItem.vendible_preparado, "und", precio_venta="6500",
                  estacion="cocina", categoria_id=cat.id, foto_url="  https://x/h.jpg ")
    assert (plato.precio_venta, plato.estacion, plato.categoria_id, plato.foto_url) == \
        (D("6500.00"), EstacionCocina.cocina, cat.id, "https://x/h.jpg")


def test_la_unidad_base_debe_ser_base_y_existir(db, u, local):
    empresa, _ = local
    with pytest.raises(ErrorUnidades, match="no es una unidad base"):
        nuevo(db, empresa, unidad="kg")
    with pytest.raises(ErrorNegocio, match="no existe en el catálogo"):
        nuevo(db, empresa, unidad="arroba")


def test_el_nombre_no_se_repite_ni_con_otras_mayusculas_pero_si_en_otro_cliente(db, u, local, otro_local):
    empresa, _ = local
    ajena, _ = otro_local
    nuevo(db, empresa, "Tomate")
    with pytest.raises(ErrorNegocio, match="Ya existe un ítem llamado"):
        nuevo(db, empresa, " tomate ")
    with pytest.raises(ErrorNegocio, match="necesita un nombre"):
        nuevo(db, empresa, "   ")
    nuevo(db, ajena, "Tomate")                                              # otro restaurante: sin problema


def test_precio_y_estacion_solo_para_vendibles(db, u, local):
    empresa, _ = local
    with pytest.raises(ErrorNegocio, match="Solo los ítems vendibles llevan precio"):
        nuevo(db, empresa, precio_venta=100)
    with pytest.raises(ErrorNegocio, match="se envían a una estación"):
        nuevo(db, empresa, estacion="cocina")
    with pytest.raises(ErrorNegocio, match="no puede ser negativo"):
        nuevo(db, empresa, "Cola", TipoItem.vendible_reventa, "und", precio_venta=-1)


def test_stock_minimo_no_negativo_y_codigo_de_barra_unico(db, u, local):
    empresa, _ = local
    with pytest.raises(ErrorNegocio, match="stock mínimo no puede ser negativo"):
        nuevo(db, empresa, stock_minimo=-5)
    nuevo(db, empresa, "Cola", TipoItem.vendible_reventa, "und", codigo_barra="780123")
    with pytest.raises(ErrorNegocio, match="código de barra ya está"):
        nuevo(db, empresa, "Fanta", TipoItem.vendible_reventa, "und", codigo_barra="780123")


def test_la_categoria_de_otro_cliente_no_existe(db, u, local, otro_local):
    empresa, _ = local
    ajena, _ = otro_local
    cat_ajena = crear_categoria(db, empresa_id=ajena.id, nombre="Secreta")
    with pytest.raises(ErrorNoEncontrado):
        nuevo(db, empresa, categoria_id=cat_ajena.id)


# ── Editar ───────────────────────────────────────────────────
def test_editar_solo_lo_enviado(db, u, local):
    empresa, _ = local
    plato = nuevo(db, empresa, "Hamburguesa", TipoItem.vendible_preparado, "und", precio_venta=6500, estacion="cocina")
    actualizar_item(db, empresa_id=empresa.id, item_id=plato.id, precio_venta=7000)
    assert (plato.precio_venta, plato.nombre, plato.estacion) == (D("7000.00"), "Hamburguesa", EstacionCocina.cocina)
    actualizar_item(db, empresa_id=empresa.id, item_id=plato.id, precio_venta=None, activo=False)
    assert plato.precio_venta is None and plato.activo is False


def test_el_tipo_y_la_unidad_base_no_se_cambian(db, u, local):
    empresa, _ = local
    item = nuevo(db, empresa)
    for campo in ("tipo", "unidad_base_id", "costo_promedio"):
        with pytest.raises(ErrorNegocio, match="no se modifican"):
            actualizar_item(db, empresa_id=empresa.id, item_id=item.id, **{campo: 1})


def test_renombrar_respeta_la_regla_de_nombres(db, u, local):
    empresa, _ = local
    tomate = nuevo(db, empresa, "Tomate")
    nuevo(db, empresa, "Cebolla")
    actualizar_item(db, empresa_id=empresa.id, item_id=tomate.id, nombre="TOMATE")      # su propio nombre: sí
    with pytest.raises(ErrorNegocio, match="Ya existe un ítem llamado"):
        actualizar_item(db, empresa_id=empresa.id, item_id=tomate.id, nombre="cebolla")


def test_no_se_edita_un_item_de_otro_cliente(db, u, local, otro_local):
    ajena, _ = otro_local
    ajeno = nuevo(db, ajena, "Harina")
    with pytest.raises(ErrorNoEncontrado):
        actualizar_item(db, empresa_id=local[0].id, item_id=ajeno.id, nombre="Mía")


def test_listar_filtra_por_tipo_texto_categoria_y_activos(db, u, local, otro_local):
    empresa, _ = local
    ajena, _ = otro_local
    cat = crear_categoria(db, empresa_id=empresa.id, nombre="Verduras")
    tomate = nuevo(db, empresa, "Tomate", categoria_id=cat.id)
    nuevo(db, empresa, "Salsa de tomate", TipoItem.componente)
    viejo = nuevo(db, empresa, "Cebolla")
    nuevo(db, ajena, "Tomate ajeno")
    actualizar_item(db, empresa_id=empresa.id, item_id=viejo.id, activo=False)
    nombres = lambda **f: [i.nombre for i in listar_items(db, empresa_id=empresa.id, **f)]
    assert nombres() == ["Salsa de tomate", "Tomate"]
    assert nombres(solo_activos=False) == ["Cebolla", "Salsa de tomate", "Tomate"]
    assert nombres(tipo=TipoItem.componente) == ["Salsa de tomate"]
    assert nombres(texto="TOMA") == ["Salsa de tomate", "Tomate"]
    assert nombres(categoria_id=cat.id) == [tomate.nombre]


# ── Categorías ───────────────────────────────────────────────
def test_categorias_sin_repetir_y_ordenadas(db, u, local):
    empresa, _ = local
    crear_categoria(db, empresa_id=empresa.id, nombre="Congelados", orden=2)
    crear_categoria(db, empresa_id=empresa.id, nombre="Abarrotes", orden=1)
    with pytest.raises(ErrorNegocio, match="Ya existe la categoría"):
        crear_categoria(db, empresa_id=empresa.id, nombre="congelados")
    with pytest.raises(ErrorNegocio, match="necesita un nombre"):
        crear_categoria(db, empresa_id=empresa.id, nombre=" ")
    assert [c.nombre for c in listar_categorias(db, empresa.id)] == ["Abarrotes", "Congelados"]


# ── Presentaciones ───────────────────────────────────────────
def test_presentaciones_con_una_sola_por_defecto(db, u, local):
    empresa, _ = local
    cola = nuevo(db, empresa, "Cola", TipoItem.vendible_reventa, "und")
    caja = crear_presentacion(db, empresa_id=empresa.id, item_id=cola.id, nombre="Caja 12 un", cantidad_en_base=12,
                              es_defecto=True)
    pack = crear_presentacion(db, empresa_id=empresa.id, item_id=cola.id, nombre="Pack 6 un", cantidad_en_base=6,
                              es_defecto=True)
    assert caja.es_defecto is False and pack.es_defecto is True
    with pytest.raises(ErrorNegocio, match="ya tiene una presentación"):
        crear_presentacion(db, empresa_id=empresa.id, item_id=cola.id, nombre="caja 12 UN", cantidad_en_base=12)
    with pytest.raises(ErrorNegocio, match="mayor que cero"):
        crear_presentacion(db, empresa_id=empresa.id, item_id=cola.id, nombre="Vacía", cantidad_en_base=0)


# ── Extras ───────────────────────────────────────────────────
def test_extra_para_todos_y_extra_para_ciertos_platos(db, u, local):
    empresa, _ = local
    tocineta = nuevo(db, empresa, "Tocineta")
    burger = nuevo(db, empresa, "Hamburguesa", TipoItem.vendible_preparado, "und")
    todos = crear_extra(db, empresa_id=empresa.id, nombre="Extra queso", precio=800, ingrediente_id=tocineta.id,
                        cantidad=20)
    algunos = crear_extra(db, empresa_id=empresa.id, nombre="Extra tocineta", precio=1000, ingrediente_id=tocineta.id,
                          cantidad=25, aplica_a_todos=False, plato_ids=[burger.id])
    assert (todos.precio, todos.aplica_a_todos, platos_del_extra(db, todos.id)) == (D("800.00"), True, [])
    assert platos_del_extra(db, algunos.id) == [burger.id]
    assert [e.nombre for e in listar_extras(db, empresa.id)] == ["Extra queso", "Extra tocineta"]


def test_reglas_de_los_extras(db, u, local, otro_local):
    empresa, _ = local
    ajena, _ = otro_local
    tocineta = nuevo(db, empresa, "Tocineta")
    burger = nuevo(db, empresa, "Hamburguesa", TipoItem.vendible_preparado, "und")
    cola = nuevo(db, empresa, "Cola", TipoItem.vendible_reventa, "und")
    harina_ajena = nuevo(db, ajena, "Harina")
    base = dict(empresa_id=empresa.id, nombre="Extra", precio=500, ingrediente_id=tocineta.id, cantidad=10)
    with pytest.raises(ErrorNegocio, match="Indica en qué platos"):
        crear_extra(db, **base, aplica_a_todos=False)
    with pytest.raises(ErrorNegocio, match="no es un plato preparado"):
        crear_extra(db, **base, aplica_a_todos=False, plato_ids=[cola.id])
    with pytest.raises(ErrorNegocio, match="no es un ingrediente"):
        crear_extra(db, **{**base, "ingrediente_id": burger.id})
    with pytest.raises(ErrorNoEncontrado):
        crear_extra(db, **{**base, "ingrediente_id": harina_ajena.id})
    with pytest.raises(ErrorNegocio, match="mayor que cero"):
        crear_extra(db, **{**base, "cantidad": 0})
    crear_extra(db, **base)
    with pytest.raises(ErrorNegocio, match="Ya existe un extra"):
        crear_extra(db, **{**base, "nombre": "EXTRA"})
