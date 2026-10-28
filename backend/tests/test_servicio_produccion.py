# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_produccion.py
# Pruebas de la producción de componentes por lote.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest

from errores import ErrorNegocio
from models import TipoItem, TipoMovimientoStock
from servicios.compras import ingresar_compra
from servicios.produccion import producir_componente
from servicios.recetas import LineaReceta, guardar_receta
from servicios.stock import obtener_stock


def armar_salsa(db, u, empresa, sucursal, nuevo_item, mayo_g=5000, ajo_g=500):
    """Salsa de ajo: 1000 g = 900 g de mayonesa ($3/g) + 100 g de ajo ($10/g) → $3,7/g."""
    mayo = nuevo_item(empresa, u["g"], "Mayonesa")
    ajo = nuevo_item(empresa, u["g"], "Ajo")
    salsa = nuevo_item(empresa, u["g"], "Salsa de ajo", tipo=TipoItem.componente)
    guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1000,
                   lineas=[LineaReceta(mayo.id, 900), LineaReceta(ajo.id, 100)])
    for item, g, costo in ((mayo, mayo_g, "3"), (ajo, ajo_g, "10")):
        if g:
            ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=item.id,
                            cantidad=g, costo_unitario_base=costo)
    db.commit()
    return mayo, ajo, salsa


def saldo(db, empresa, sucursal, item):
    return obtener_stock(db, empresa.id, item.id, sucursal.id).cantidad_fisica


def test_producir_lote_completo_resta_insumos_y_suma_componente(db, u, local, nuevo_item):
    empresa, sucursal = local
    mayo, ajo, salsa = armar_salsa(db, u, empresa, sucursal, nuevo_item)

    r = producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=salsa.id,
                            usuario_id=None, nota="Lote del lunes")

    assert saldo(db, empresa, sucursal, mayo) == Decimal("4100")
    assert saldo(db, empresa, sucursal, ajo) == Decimal("400")
    assert saldo(db, empresa, sucursal, salsa) == Decimal("1000")
    assert r.lote.cantidad_producida == Decimal("1000.000")
    assert r.lote.costo_total == Decimal("3700.00")
    assert r.lote.costo_unitario == Decimal("3.700000")
    assert [m.tipo for m in r.consumos] == [TipoMovimientoStock.produccion_consumo] * 2
    assert r.entrada.tipo == TipoMovimientoStock.produccion_entrada
    assert r.entrada.referencia_tipo == "lote_produccion" and r.entrada.referencia_id == str(r.lote.id)
    assert r.faltantes == []
    assert salsa.costo_ultimo == Decimal("3.7") and salsa.costo_promedio == Decimal("3.7")


def test_produccion_parcial_consume_en_proporcion(db, u, local, nuevo_item):
    empresa, sucursal = local
    mayo, ajo, salsa = armar_salsa(db, u, empresa, sucursal, nuevo_item)
    r = producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=salsa.id,
                            cantidad_producida=500)
    assert saldo(db, empresa, sucursal, mayo) == Decimal("4550")    # gastó 450 g
    assert saldo(db, empresa, sucursal, ajo) == Decimal("450")      # gastó 50 g
    assert saldo(db, empresa, sucursal, salsa) == Decimal("500")
    assert r.lote.costo_unitario == Decimal("3.700000")


def test_rendimiento_real_mayor_baja_el_costo_por_gramo(db, u, local, nuevo_item):
    """Si el mismo lote rindió más de lo teórico, cada gramo sale más barato."""
    empresa, sucursal = local
    mayo, ajo, salsa = armar_salsa(db, u, empresa, sucursal, nuevo_item)
    # Producir 2000 g gasta el doble de insumos (7.400) → mismo costo por gramo.
    r = producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=salsa.id,
                            cantidad_producida=2000)
    assert r.lote.costo_total == Decimal("7400.00")
    assert r.lote.costo_unitario == Decimal("3.700000")


def test_falta_de_insumo_no_bloquea_pero_avisa(db, u, local, nuevo_item):
    empresa, sucursal = local
    mayo, ajo, salsa = armar_salsa(db, u, empresa, sucursal, nuevo_item, mayo_g=5000, ajo_g=60)
    r = producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=salsa.id)
    assert r.faltantes == ["Ajo"]
    assert saldo(db, empresa, sucursal, ajo) == Decimal("-40")
    assert saldo(db, empresa, sucursal, salsa) == Decimal("1000")


def test_el_promedio_del_componente_se_pondera_entre_lotes(db, u, local, nuevo_item):
    empresa, sucursal = local
    mayo, ajo, salsa = armar_salsa(db, u, empresa, sucursal, nuevo_item)
    producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=salsa.id)
    # Sube la mayonesa a $4/g: el segundo lote cuesta (900×4 + 100×10)/1000 = $4,6/g.
    mayo.costo_ultimo = Decimal("4")
    mayo.costo_promedio = Decimal("4")
    r = producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=salsa.id)
    assert r.lote.costo_unitario == Decimal("4.600000")
    assert salsa.costo_promedio == Decimal("4.150000")      # (1000×3,7 + 1000×4,6) / 2000
    assert salsa.costo_ultimo == Decimal("4.6")


def test_un_componente_puede_usar_otro_componente_como_insumo(db, u, local, nuevo_item):
    empresa, sucursal = local
    mayo, ajo, salsa = armar_salsa(db, u, empresa, sucursal, nuevo_item)
    aderezo = nuevo_item(empresa, u["g"], "Aderezo", tipo=TipoItem.componente)
    guardar_receta(db, empresa_id=empresa.id, item_id=aderezo.id, rendimiento=500,
                   lineas=[LineaReceta(salsa.id, 500)])
    producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=salsa.id)
    r = producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=aderezo.id)
    assert saldo(db, empresa, sucursal, salsa) == Decimal("500")
    assert saldo(db, empresa, sucursal, aderezo) == Decimal("500")
    assert r.lote.costo_unitario == Decimal("3.700000")


def test_solo_se_producen_componentes_con_receta(db, u, local, otro_local, nuevo_item):
    empresa, sucursal = local
    ajena, sucursal_ajena = otro_local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    sin_receta = nuevo_item(empresa, u["g"], "Salsa sin receta", tipo=TipoItem.componente)
    ajeno = nuevo_item(ajena, u["g"], "Salsa ajena", tipo=TipoItem.componente)
    with pytest.raises(ErrorNegocio, match="no es un componente"):
        producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=tomate.id)
    with pytest.raises(ErrorNegocio, match="no tiene receta"):
        producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=sin_receta.id)
    with pytest.raises(ErrorNegocio, match="no existe"):
        producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=ajeno.id)
    with pytest.raises(ErrorNegocio, match="no existe"):
        producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal_ajena.id, item_id=sin_receta.id)


@pytest.mark.parametrize("cantidad", [0, -10])
def test_cantidad_producida_debe_ser_positiva(db, u, local, nuevo_item, cantidad):
    empresa, sucursal = local
    mayo, ajo, salsa = armar_salsa(db, u, empresa, sucursal, nuevo_item)
    with pytest.raises(ErrorNegocio, match="mayor que cero"):
        producir_componente(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=salsa.id,
                            cantidad_producida=cantidad)
