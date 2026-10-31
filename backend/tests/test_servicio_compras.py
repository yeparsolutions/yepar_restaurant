# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_compras.py
# Pruebas del ingreso de mercadería (servicios/compras.py).
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest

from errores import ErrorNegocio
from models import (ItemPresentacion, StockSucursal, Sucursal, TipoItem,
                    TipoMovimientoStock)
from servicios.compras import ingresar_compra
from unidades import ErrorUnidades


def test_comprar_un_kilo_de_tomate_sube_mil_gramos(db, u, local, nuevo_item):
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")

    r = ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=tomate.id,
                        cantidad=1, unidad="kg", monto_neto=1500, usuario_id=None,
                        referencia_tipo="compra", referencia_id=7)

    assert r.cantidad_base == Decimal("1000.000")
    assert r.costo_unitario_base == Decimal("1.500000")           # $1,5 por gramo
    assert r.movimiento.tipo == TipoMovimientoStock.compra
    assert (r.movimiento.stock_anterior, r.movimiento.stock_nuevo) == (Decimal("0"), Decimal("1000"))
    assert r.movimiento.referencia_tipo == "compra" and r.movimiento.referencia_id == "7"
    assert tomate.costo_promedio == Decimal("1.5") and tomate.costo_ultimo == Decimal("1.5")


def test_segunda_compra_recalcula_promedio_y_apunta_al_mas_alto(db, u, local, nuevo_item):
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=tomate.id,
                    cantidad=1, unidad="kg", monto_neto=1500)
    r = ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=tomate.id,
                        cantidad=1, unidad="kg", monto_neto=1800)

    assert r.movimiento.stock_anterior == Decimal("1000")
    assert r.movimiento.stock_nuevo == Decimal("2000")
    assert r.costo_promedio == Decimal("1.650000")          # (1000×1,5 + 1000×1,8) / 2000
    assert r.costo_referencia == Decimal("1.8")             # el último gana al promedio


def test_compra_por_presentacion_caja_de_12(db, u, local, nuevo_item):
    empresa, sucursal = local
    lata = nuevo_item(empresa, u["und"], "Bebida lata", tipo=TipoItem.vendible_reventa)
    caja = ItemPresentacion(item_id=lata.id, nombre="Caja 12 un", cantidad_en_base=Decimal("12"))
    db.add(caja)
    db.commit()

    r = ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=lata.id,
                        cantidad=3, presentacion_id=caja.id, monto_neto=36000)   # 3 cajas = 36 latas

    assert r.cantidad_base == Decimal("36.000")
    assert r.costo_unitario_base == Decimal("1000.000000")    # $1.000 por lata
    assert r.movimiento.stock_nuevo == Decimal("36")


def test_cantidad_ya_en_base_y_costo_unitario_directo(db, u, local, nuevo_item):
    empresa, sucursal = local
    harina = nuevo_item(empresa, u["g"], "Harina")
    r = ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=harina.id,
                        cantidad=500, costo_unitario_base="0.9")
    assert r.cantidad_base == Decimal("500.000")
    assert r.costo_promedio == Decimal("0.9")


def test_el_promedio_pondera_con_el_stock_de_todas_las_sucursales(db, u, local, nuevo_item):
    empresa, sucursal = local
    otra = Sucursal(empresa_id=empresa.id, nombre="Segundo local")
    db.add(otra)
    db.commit()
    tomate = nuevo_item(empresa, u["g"], "Tomate")

    ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=tomate.id,
                    cantidad=1, unidad="kg", monto_neto=1500)
    r = ingresar_compra(db, empresa_id=empresa.id, sucursal_id=otra.id, item_id=tomate.id,
                        cantidad=1, unidad="kg", monto_neto=1800)

    assert r.costo_promedio == Decimal("1.650000")          # ponderó el kilo del OTRO local también
    saldos = {s.sucursal_id: s.cantidad_fisica
              for s in db.query(StockSucursal).filter_by(item_id=tomate.id)}
    assert saldos == {sucursal.id: Decimal("1000"), otra.id: Decimal("1000")}   # stocks separados


def test_con_stock_negativo_el_costo_nuevo_reemplaza_al_promedio(db, u, local, nuevo_item):
    empresa, sucursal = local
    queso = nuevo_item(empresa, u["g"], "Queso", costo_promedio=Decimal("5"), costo_ultimo=Decimal("5"))
    db.add(StockSucursal(empresa_id=empresa.id, item_id=queso.id, sucursal_id=sucursal.id,
                         cantidad_fisica=Decimal("-50")))
    db.commit()

    r = ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=queso.id,
                        cantidad=1, unidad="kg", monto_neto=8000)

    assert r.costo_promedio == Decimal("8.000000")
    assert r.movimiento.stock_nuevo == Decimal("950")          # −50 + 1000


def test_el_servicio_no_hace_commit(db, u, local, nuevo_item):
    """Quien llama decide confirmar o deshacer: un rollback lo deja todo como estaba."""
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=tomate.id,
                    cantidad=1, unidad="kg", monto_neto=1500)
    db.rollback()
    assert db.query(StockSucursal).count() == 0


# ── Validaciones ─────────────────────────────────────────────
def _comprar(db, empresa, sucursal, item, **datos):
    base = dict(empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=item.id)
    base.update(datos)
    return ingresar_compra(db, **base)


def test_exige_monto_o_costo_unitario_pero_no_ambos(db, u, local, nuevo_item):
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    with pytest.raises(ErrorNegocio, match="uno solo"):
        _comprar(db, empresa, sucursal, tomate, cantidad=1, unidad="kg")
    with pytest.raises(ErrorNegocio, match="uno solo"):
        _comprar(db, empresa, sucursal, tomate, cantidad=1, unidad="kg",
                 monto_neto=1500, costo_unitario_base="1.5")


def test_unidad_y_presentacion_no_se_mezclan(db, u, local, nuevo_item):
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    with pytest.raises(ErrorNegocio, match="no ambas"):
        _comprar(db, empresa, sucursal, tomate, cantidad=1, unidad="kg",
                 presentacion_id=1, monto_neto=1500)


def test_unidad_de_otra_familia_se_rechaza(db, u, local, nuevo_item):
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    with pytest.raises(ErrorUnidades, match="familias distintas"):
        _comprar(db, empresa, sucursal, tomate, cantidad=1, unidad="l", monto_neto=1500)


def test_unidad_inexistente_se_rechaza(db, u, local, nuevo_item):
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    with pytest.raises(ErrorNegocio, match="no existe en el catálogo"):
        _comprar(db, empresa, sucursal, tomate, cantidad=1, unidad="arroba", monto_neto=1500)


def test_cantidad_cero_se_rechaza(db, u, local, nuevo_item):
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    with pytest.raises(ErrorNegocio, match="mayor que cero"):
        _comprar(db, empresa, sucursal, tomate, cantidad=0, unidad="kg", monto_neto=1500)
    with pytest.raises(ErrorNegocio, match="mayor que cero"):
        _comprar(db, empresa, sucursal, tomate, cantidad=0, costo_unitario_base="1.5")


def test_componentes_y_platos_no_se_compran(db, u, local, nuevo_item):
    empresa, sucursal = local
    salsa = nuevo_item(empresa, u["g"], "Salsa", tipo=TipoItem.componente)
    plato = nuevo_item(empresa, u["und"], "Plato", tipo=TipoItem.vendible_preparado)
    for item in (salsa, plato):
        with pytest.raises(ErrorNegocio, match="no se compra"):
            _comprar(db, empresa, sucursal, item, cantidad=1, costo_unitario_base="10")


def test_presentacion_de_otro_item_se_rechaza(db, u, local, nuevo_item):
    empresa, sucursal = local
    lata = nuevo_item(empresa, u["und"], "Lata", tipo=TipoItem.vendible_reventa)
    jugo = nuevo_item(empresa, u["und"], "Jugo", tipo=TipoItem.vendible_reventa)
    caja_de_jugo = ItemPresentacion(item_id=jugo.id, nombre="Caja 6", cantidad_en_base=Decimal("6"))
    db.add(caja_de_jugo)
    db.commit()
    with pytest.raises(ErrorNegocio, match="no pertenece a este ítem"):
        _comprar(db, empresa, sucursal, lata, cantidad=1, presentacion_id=caja_de_jugo.id, monto_neto=6000)


def test_no_se_compra_con_datos_de_otro_cliente(db, u, local, otro_local, nuevo_item):
    empresa, sucursal = local
    ajena, sucursal_ajena = otro_local
    item_ajeno = nuevo_item(ajena, u["g"], "Harina ajena")
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    with pytest.raises(ErrorNegocio, match="no existe"):
        _comprar(db, empresa, sucursal, item_ajeno, cantidad=1, unidad="kg", monto_neto=1500)
    with pytest.raises(ErrorNegocio, match="no existe"):
        ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal_ajena.id, item_id=tomate.id,
                        cantidad=1, unidad="kg", monto_neto=1500)
