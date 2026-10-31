# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_disponibilidad.py
# Pruebas de disponibilidad para el mesero, alertas y lista de compras.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest

from errores import ErrorNegocio
from models import Extra, ItemPresentacion, StockSucursal, TipoItem
from servicios.compras import ingresar_compra
from servicios.disponibilidad import (alertas_stock_bajo, catalogo_mesero,
                                      lista_compras_sugerida, revisar_disponibilidad)
from servicios.recetas import LineaReceta, guardar_receta
from servicios.reservas import reservar_linea


def comprar(db, empresa, sucursal, item, cantidad, costo="1"):
    ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=item.id,
                    cantidad=cantidad, costo_unitario_base=costo)


@pytest.fixture()
def cocina(db, u, local, nuevo_item):
    """Hamburguesa = pan + carne 150 g + cebolla 30 g (removible); más una cola de reventa."""
    empresa, sucursal = local
    pan = nuevo_item(empresa, u["und"], "Pan", stock_minimo=Decimal("10"), costo_ultimo=Decimal("300"))
    carne = nuevo_item(empresa, u["g"], "Carne", stock_minimo=Decimal("1000"), costo_ultimo=Decimal("8"))
    cebolla = nuevo_item(empresa, u["g"], "Cebolla")
    cola = nuevo_item(empresa, u["und"], "Cola lata", tipo=TipoItem.vendible_reventa,
                      stock_minimo=Decimal("6"), costo_ultimo=Decimal("500"))
    burger = nuevo_item(empresa, u["und"], "Hamburguesa", tipo=TipoItem.vendible_preparado)
    sin_receta = nuevo_item(empresa, u["und"], "Plato nuevo", tipo=TipoItem.vendible_preparado)
    guardar_receta(db, empresa_id=empresa.id, item_id=burger.id, rendimiento=1, lineas=[
        LineaReceta(pan.id, 1), LineaReceta(carne.id, 150), LineaReceta(cebolla.id, 30, es_removible=True)])
    for item, cant, costo in ((pan, 20, "300"), (carne, 3000, "8"), (cebolla, 500, "1"), (cola, 24, "500")):
        comprar(db, empresa, sucursal, item, cant, costo)
    db.commit()
    return dict(empresa=empresa, sucursal=sucursal, pan=pan, carne=carne, cebolla=cebolla, cola=cola,
                burger=burger, sin_receta=sin_receta)


def revisar(db, c, **datos):
    return revisar_disponibilidad(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, **datos)


# ── Mesero ───────────────────────────────────────────────────
def test_alcanza_cuando_hay_de_todo(db, cocina):
    d = revisar(db, cocina, item_id=cocina["burger"].id, cantidad=5)
    assert d.alcanza and d.faltas == []


def test_avisa_que_falta_y_cuanto(db, cocina):
    d = revisar(db, cocina, item_id=cocina["burger"].id, cantidad=25)    # pan 20 de 25; carne 3000 de 3750; cebolla 500 de 750
    assert not d.alcanza
    assert {f.nombre: f.falta for f in d.faltas} == {"Pan": Decimal("5.000"), "Carne": Decimal("750.000"),
                                                      "Cebolla": Decimal("250.000")}


def test_sin_cebolla_puede_salvar_el_pedido(db, cocina, u):
    c = cocina
    # 20 hamburguesas piden 600 g de cebolla y hay 500: falta; sin cebolla alcanza.
    assert not revisar(db, c, item_id=c["burger"].id, cantidad=20).alcanza
    assert revisar(db, c, item_id=c["burger"].id, cantidad=20, sin_ingredientes=[c["cebolla"].id]).alcanza


def test_lo_reservado_en_cocina_ya_no_esta_disponible(db, cocina):
    c = cocina
    reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=1,
                   item_id=c["burger"].id, cantidad=18)
    d = revisar(db, c, item_id=c["burger"].id, cantidad=3)    # quedan: pan 2, carne 300, cebolla −40
    assert {f.nombre: f.falta for f in d.faltas} == {"Pan": Decimal("1.000"), "Carne": Decimal("150.000"),
                                                      "Cebolla": Decimal("130.000")}


def test_agotado_manual_marca_el_plato_aunque_el_sistema_crea_que_hay(db, cocina):
    c = cocina
    c["carne"].agotado_manual = True
    db.commit()
    d = revisar(db, c, item_id=c["burger"].id)
    assert not d.alcanza
    assert d.faltas[0].nombre == "Carne" and d.faltas[0].agotado_manual


def test_ingrediente_sin_fila_de_stock_cuenta_como_cero_y_no_crea_filas(db, cocina, u):
    c = cocina
    queso = db.query(type(c["pan"])).filter_by(nombre="Pan").one()    # solo para tener la clase Item
    nuevo = type(queso)(empresa_id=c["empresa"].id, tipo=TipoItem.materia_prima, nombre="Queso",
                        unidad_base_id=u["g"].id)
    db.add(nuevo)
    db.flush()
    guardar_receta(db, empresa_id=c["empresa"].id, item_id=c["sin_receta"].id, rendimiento=1,
                   lineas=[LineaReceta(nuevo.id, 50)])
    filas_antes = db.query(StockSucursal).count()
    d = revisar(db, c, item_id=c["sin_receta"].id)
    assert [(f.nombre, f.falta) for f in d.faltas] == [("Queso", Decimal("50.000"))]
    assert db.query(StockSucursal).count() == filas_antes


def test_catalogo_del_mesero_solo_muestra_vendibles_con_receta(db, cocina):
    c = cocina
    nombres = {x.nombre: x.alcanza for x in catalogo_mesero(db, empresa_id=c["empresa"].id,
                                                            sucursal_id=c["sucursal"].id)}
    assert nombres == {"Cola lata": True, "Hamburguesa": True}     # sin Pan/Carne ni el plato sin receta


def test_catalogo_oculta_items_inactivos_y_marca_los_que_no_alcanzan(db, cocina):
    c = cocina
    c["cola"].activo = False
    c["pan"].agotado_manual = True
    db.commit()
    catalogo = catalogo_mesero(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id)
    assert [(x.nombre, x.alcanza) for x in catalogo] == [("Hamburguesa", False)]


def test_no_se_ve_el_catalogo_de_otro_cliente(db, cocina, otro_local):
    _, sucursal_ajena = otro_local
    with pytest.raises(ErrorNegocio, match="no existe"):
        catalogo_mesero(db, empresa_id=cocina["empresa"].id, sucursal_id=sucursal_ajena.id)


# ── Administrador ────────────────────────────────────────────
def test_alertas_solo_de_lo_que_esta_bajo_su_minimo(db, cocina):
    c = cocina
    reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=1,
                   item_id=c["burger"].id, cantidad=15)          # pan: 5 disponibles (< 10); carne 750 (< 1000)
    alertas = alertas_stock_bajo(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id)
    assert {a.nombre: a.disponible for a in alertas} == {"Pan": Decimal("5.000"), "Carne": Decimal("750.000")}
    # La cebolla no tiene mínimo definido: nunca alerta. La cola (24 ≥ 6) tampoco.


def test_alertas_ordenadas_de_la_mas_critica_a_la_menos(db, cocina):
    c = cocina
    reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=1,
                   item_id=c["burger"].id, cantidad=15)
    alertas = alertas_stock_bajo(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id)
    assert [a.nombre for a in alertas] == ["Carne", "Pan"]        # faltan 250 vs 5


def test_item_sin_stock_alguno_alerta_con_disponible_cero(db, cocina, u):
    c = cocina
    sal = type(c["pan"])(empresa_id=c["empresa"].id, tipo=TipoItem.materia_prima, nombre="Sal",
                         unidad_base_id=u["g"].id, stock_minimo=Decimal("500"))
    db.add(sal)
    db.commit()
    alertas = alertas_stock_bajo(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id)
    assert [(a.nombre, a.disponible) for a in alertas] == [("Sal", Decimal("0"))]


def test_componente_bajo_alerta_pero_no_va_a_la_lista_de_compras(db, cocina, u):
    c = cocina
    salsa = type(c["pan"])(empresa_id=c["empresa"].id, tipo=TipoItem.componente, nombre="Salsa",
                           unidad_base_id=u["g"].id, stock_minimo=Decimal("300"))
    db.add(salsa)
    db.commit()
    alertas = alertas_stock_bajo(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id)
    assert [(a.nombre, a.se_produce) for a in alertas] == [("Salsa", True)]
    assert lista_compras_sugerida(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id).lineas == []


def test_lista_de_compras_repone_hasta_el_doble_del_minimo_con_costo(db, cocina):
    c = cocina
    reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=1,
                   item_id=c["burger"].id, cantidad=15)
    lista = lista_compras_sugerida(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id)
    por_nombre = {l.nombre: l for l in lista.lineas}
    assert por_nombre["Carne"].cantidad_base == Decimal("1250.000")       # 2×1000 − 750
    assert por_nombre["Carne"].unidad == "g"
    assert por_nombre["Carne"].costo_estimado == Decimal("10000.00")      # 1250 × $8
    assert por_nombre["Pan"].cantidad_base == Decimal("15.000")           # 2×10 − 5
    assert por_nombre["Pan"].costo_estimado == Decimal("4500.00")         # 15 × $300
    assert lista.costo_total_estimado == Decimal("14500.00")


def test_lista_de_compras_sugiere_en_cajas_redondeando_hacia_arriba(db, cocina):
    c = cocina
    caja = ItemPresentacion(item_id=c["cola"].id, nombre="Caja 12 un", cantidad_en_base=Decimal("12"),
                            es_defecto=True)
    db.add(caja)
    db.commit()
    # Se bebe casi toda la cola: quedan 2 de 24 (mínimo 6) → repone hasta 12: 10 latas = 1 caja.
    stock = db.query(StockSucursal).filter_by(item_id=c["cola"].id).one()
    stock.cantidad_fisica = Decimal("2")
    db.commit()
    lista = lista_compras_sugerida(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id)
    cola = next(l for l in lista.lineas if l.nombre == "Cola lata")
    assert cola.cantidad_base == Decimal("10.000")
    assert (cola.presentacion, cola.cantidad_presentacion) == ("Caja 12 un", 1)
    stock.cantidad_fisica = Decimal("-3")          # más faltante: 15 latas → 2 cajas
    db.commit()
    cola = next(l for l in lista_compras_sugerida(db, empresa_id=c["empresa"].id,
                                                  sucursal_id=c["sucursal"].id).lineas if l.nombre == "Cola lata")
    assert cola.cantidad_presentacion == 2
