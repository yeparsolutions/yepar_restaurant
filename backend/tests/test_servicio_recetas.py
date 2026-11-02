# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_recetas.py
# Pruebas de guardar recetas y calcular su costo (servicios/recetas.py).
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest

from errores import ErrorNegocio
from models import TipoItem
from servicios.recetas import LineaReceta, calcular_costo_receta, guardar_receta
from unidades import ErrorUnidades


# ============================================================
# GUARDAR RECETAS
# ============================================================
def test_guarda_receta_y_pasa_las_cantidades_a_unidad_base(db, u, local, nuevo_item):
    empresa, _ = local
    carne   = nuevo_item(empresa, u["g"], "Carne molida")
    tomate  = nuevo_item(empresa, u["g"], "Tomate")
    burger  = nuevo_item(empresa, u["und"], "Hamburguesa", tipo=TipoItem.vendible_preparado,
                         precio_venta=Decimal("6500"))

    receta = guardar_receta(
        db, empresa_id=empresa.id, item_id=burger.id, rendimiento=1,
        instrucciones="Sellar 3 min por lado.",
        lineas=[LineaReceta(carne.id, 150),                       # ya viene en gramos
                LineaReceta(tomate.id, "0.08", unidad="kg",       # 0,08 kg → 80 g
                            es_removible=True)])

    assert receta.rendimiento == Decimal("1.000")
    assert [l.cantidad for l in receta.lineas] == [Decimal("150.000"), Decimal("80.000")]
    assert [l.es_removible for l in receta.lineas] == [False, True]
    assert burger.receta is receta


def test_rendimiento_puede_darse_en_otra_unidad(db, u, local, nuevo_item):
    empresa, _ = local
    mayo  = nuevo_item(empresa, u["g"], "Mayonesa")
    salsa = nuevo_item(empresa, u["g"], "Salsa de ajo", tipo=TipoItem.componente)
    receta = guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id,
                            rendimiento=1, rendimiento_unidad="kg",
                            lineas=[LineaReceta(mayo.id, 1, unidad="kg")])
    assert receta.rendimiento == Decimal("1000.000")


def test_un_ingrediente_en_litros_no_sirve_para_un_item_en_gramos(db, u, local, nuevo_item):
    empresa, _ = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    salsa  = nuevo_item(empresa, u["g"], "Salsa", tipo=TipoItem.componente)
    with pytest.raises(ErrorUnidades, match="familias distintas"):
        guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1000,
                       lineas=[LineaReceta(tomate.id, 1, unidad="l")])


def test_solo_llevan_receta_componentes_y_vendibles_preparados(db, u, local, nuevo_item):
    empresa, _ = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    with pytest.raises(ErrorNegocio, match="no lleva receta"):
        guardar_receta(db, empresa_id=empresa.id, item_id=tomate.id, rendimiento=1,
                       lineas=[LineaReceta(tomate.id, 1)])


def test_receta_sin_ingredientes_se_rechaza(db, u, local, nuevo_item):
    empresa, _ = local
    salsa = nuevo_item(empresa, u["g"], "Salsa", tipo=TipoItem.componente)
    with pytest.raises(ErrorNegocio, match="al menos un ingrediente"):
        guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1, lineas=[])


def test_ingrediente_repetido_se_rechaza(db, u, local, nuevo_item):
    empresa, _ = local
    mayo  = nuevo_item(empresa, u["g"], "Mayonesa")
    salsa = nuevo_item(empresa, u["g"], "Salsa", tipo=TipoItem.componente)
    with pytest.raises(ErrorNegocio, match="repetirse"):
        guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1000,
                       lineas=[LineaReceta(mayo.id, 500), LineaReceta(mayo.id, 400)])


@pytest.mark.parametrize("cantidad", [0, -5])
def test_cantidad_cero_o_negativa_se_rechaza(db, u, local, nuevo_item, cantidad):
    empresa, _ = local
    mayo  = nuevo_item(empresa, u["g"], "Mayonesa")
    salsa = nuevo_item(empresa, u["g"], "Salsa", tipo=TipoItem.componente)
    with pytest.raises(ErrorNegocio, match="mayor que cero"):
        guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1000,
                       lineas=[LineaReceta(mayo.id, cantidad)])


def test_no_se_puede_usar_un_ingrediente_de_otro_cliente(db, u, local, otro_local, nuevo_item):
    empresa, _ = local
    ajena, _ = otro_local
    harina_ajena = nuevo_item(ajena, u["g"], "Harina ajena")
    masa = nuevo_item(empresa, u["g"], "Masa", tipo=TipoItem.componente)
    with pytest.raises(ErrorNegocio, match="no existe"):
        guardar_receta(db, empresa_id=empresa.id, item_id=masa.id, rendimiento=1000,
                       lineas=[LineaReceta(harina_ajena.id, 500)])


def test_un_item_no_puede_ser_ingrediente_de_si_mismo(db, u, local, nuevo_item):
    empresa, _ = local
    salsa = nuevo_item(empresa, u["g"], "Salsa", tipo=TipoItem.componente)
    with pytest.raises(ErrorNegocio, match="de sí mismo"):
        guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1000,
                       lineas=[LineaReceta(salsa.id, 100)])


def test_un_plato_terminado_no_puede_ser_ingrediente(db, u, local, nuevo_item):
    empresa, _ = local
    burger = nuevo_item(empresa, u["und"], "Hamburguesa", tipo=TipoItem.vendible_preparado)
    combo  = nuevo_item(empresa, u["und"], "Plato raro", tipo=TipoItem.vendible_preparado)
    with pytest.raises(ErrorNegocio, match="no puede ser ingrediente"):
        guardar_receta(db, empresa_id=empresa.id, item_id=combo.id, rendimiento=1,
                       lineas=[LineaReceta(burger.id, 1)])


def test_una_bebida_de_reventa_si_puede_ser_ingrediente_de_un_trago(db, u, local, nuevo_item):
    empresa, _ = local
    ron  = nuevo_item(empresa, u["ml"], "Ron")
    cola = nuevo_item(empresa, u["und"], "Cola en lata", tipo=TipoItem.vendible_reventa)
    trago = nuevo_item(empresa, u["und"], "Cuba libre", tipo=TipoItem.vendible_preparado)
    receta = guardar_receta(db, empresa_id=empresa.id, item_id=trago.id, rendimiento=1,
                            lineas=[LineaReceta(ron.id, 45), LineaReceta(cola.id, 1)])
    assert len(receta.lineas) == 2


# ── Ciclos ───────────────────────────────────────────────────
def test_ciclo_directo_a_usa_b_y_b_usa_a(db, u, local, nuevo_item):
    empresa, _ = local
    harina = nuevo_item(empresa, u["g"], "Harina")
    a = nuevo_item(empresa, u["g"], "Masa A", tipo=TipoItem.componente)
    b = nuevo_item(empresa, u["g"], "Masa B", tipo=TipoItem.componente)
    guardar_receta(db, empresa_id=empresa.id, item_id=a.id, rendimiento=1000,
                   lineas=[LineaReceta(b.id, 500), LineaReceta(harina.id, 500)])
    with pytest.raises(ErrorNegocio, match="circular"):
        guardar_receta(db, empresa_id=empresa.id, item_id=b.id, rendimiento=1000,
                       lineas=[LineaReceta(a.id, 500)])


def test_ciclo_indirecto_a_b_c_a(db, u, local, nuevo_item):
    empresa, _ = local
    harina = nuevo_item(empresa, u["g"], "Harina")
    a = nuevo_item(empresa, u["g"], "A", tipo=TipoItem.componente)
    b = nuevo_item(empresa, u["g"], "B", tipo=TipoItem.componente)
    c = nuevo_item(empresa, u["g"], "C", tipo=TipoItem.componente)
    guardar_receta(db, empresa_id=empresa.id, item_id=a.id, rendimiento=1000, lineas=[LineaReceta(b.id, 100)])
    guardar_receta(db, empresa_id=empresa.id, item_id=b.id, rendimiento=1000, lineas=[LineaReceta(c.id, 100)])
    guardar_receta(db, empresa_id=empresa.id, item_id=c.id, rendimiento=1000, lineas=[LineaReceta(harina.id, 100)])
    with pytest.raises(ErrorNegocio, match="circular"):
        guardar_receta(db, empresa_id=empresa.id, item_id=c.id, rendimiento=1000,
                       lineas=[LineaReceta(a.id, 100)])


def test_un_componente_compartido_por_dos_platos_no_es_ciclo(db, u, local, nuevo_item):
    """Dos recetas pueden usar la misma salsa: eso es un 'diamante', no un ciclo."""
    empresa, _ = local
    mayo  = nuevo_item(empresa, u["g"], "Mayonesa")
    salsa = nuevo_item(empresa, u["g"], "Salsa", tipo=TipoItem.componente)
    p1    = nuevo_item(empresa, u["und"], "Plato 1", tipo=TipoItem.vendible_preparado)
    p2    = nuevo_item(empresa, u["und"], "Plato 2", tipo=TipoItem.vendible_preparado)
    guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1000, lineas=[LineaReceta(mayo.id, 900)])
    guardar_receta(db, empresa_id=empresa.id, item_id=p1.id, rendimiento=1, lineas=[LineaReceta(salsa.id, 20)])
    guardar_receta(db, empresa_id=empresa.id, item_id=p2.id, rendimiento=1, lineas=[LineaReceta(salsa.id, 30)])


# ── Reemplazar una receta ────────────────────────────────────
def test_reemplazar_receta_con_el_mismo_ingrediente(db, u, local, nuevo_item):
    """Editar la receta no debe chocar con la regla de no repetir ingrediente."""
    empresa, _ = local
    mayo  = nuevo_item(empresa, u["g"], "Mayonesa")
    ajo   = nuevo_item(empresa, u["g"], "Ajo")
    salsa = nuevo_item(empresa, u["g"], "Salsa de ajo", tipo=TipoItem.componente)

    primera = guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1000,
                             lineas=[LineaReceta(mayo.id, 900), LineaReceta(ajo.id, 100)])
    db.commit()
    segunda = guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1200,
                             instrucciones="Licuar 2 minutos.",
                             lineas=[LineaReceta(mayo.id, 1000), LineaReceta(ajo.id, 200)])
    db.commit()

    assert segunda.id == primera.id                      # misma receta, no una nueva
    assert segunda.rendimiento == Decimal("1200.000")
    assert [l.cantidad for l in segunda.lineas] == [Decimal("1000.000"), Decimal("200.000")]
    assert segunda.instrucciones == "Licuar 2 minutos."


# ============================================================
# COSTO TEÓRICO
# ============================================================
def armar_hamburguesa(db, u, empresa, nuevo_item):
    """pan + carne + salsa de ajo (componente) + cebolla (removible)."""
    pan     = nuevo_item(empresa, u["und"], "Pan", costo_ultimo=Decimal("300"))
    carne   = nuevo_item(empresa, u["g"], "Carne molida", costo_ultimo=Decimal("8"))
    cebolla = nuevo_item(empresa, u["g"], "Cebolla", costo_ultimo=Decimal("1"))
    mayo    = nuevo_item(empresa, u["g"], "Mayonesa", costo_ultimo=Decimal("3"))
    ajo     = nuevo_item(empresa, u["g"], "Ajo", costo_ultimo=Decimal("10"))
    salsa   = nuevo_item(empresa, u["g"], "Salsa de ajo", tipo=TipoItem.componente)
    burger  = nuevo_item(empresa, u["und"], "Hamburguesa", tipo=TipoItem.vendible_preparado,
                         precio_venta=Decimal("6500"))

    # 1 lote = 1000 g de salsa: 900 g de mayonesa ($3/g) + 100 g de ajo ($10/g) = $3.700 → $3,7/g
    guardar_receta(db, empresa_id=empresa.id, item_id=salsa.id, rendimiento=1000,
                   lineas=[LineaReceta(mayo.id, 900), LineaReceta(ajo.id, 100)])
    guardar_receta(db, empresa_id=empresa.id, item_id=burger.id, rendimiento=1,
                   lineas=[LineaReceta(pan.id, 1),
                           LineaReceta(carne.id, 150),
                           LineaReceta(salsa.id, 20),
                           LineaReceta(cebolla.id, 30, es_removible=True)])
    db.commit()
    return burger, salsa, carne, cebolla


def test_costo_del_plato_baja_por_los_componentes(db, u, local, nuevo_item):
    empresa, _ = local
    burger, salsa, _, _ = armar_hamburguesa(db, u, empresa, nuevo_item)

    # El costo de la salsa se calcula desde su receta: (900×3 + 100×10) / 1000 = 3,7 por g.
    assert calcular_costo_receta(db, empresa_id=empresa.id, item_id=salsa.id).costo_unitario == Decimal("3.7")

    # Plato = pan 300 + carne 150×8 (1.200) + salsa 20×3,7 (74) + cebolla 30×1 (30) = 1.604
    costo = calcular_costo_receta(db, empresa_id=empresa.id, item_id=burger.id)
    assert costo.costo_total == Decimal("1604")
    assert costo.costo_unitario == Decimal("1604")
    assert {l.nombre: l.costo_linea for l in costo.lineas}["Salsa de ajo"] == Decimal("74.0")


def test_el_costo_del_componente_sale_de_su_receta_no_de_un_costo_guardado(db, u, local, nuevo_item):
    empresa, _ = local
    burger, salsa, _, _ = armar_hamburguesa(db, u, empresa, nuevo_item)
    salsa.costo_ultimo = Decimal("99")      # un valor viejo o equivocado en el ítem
    db.commit()
    assert calcular_costo_receta(db, empresa_id=empresa.id, item_id=burger.id).costo_total == Decimal("1604")


def test_costo_real_sin_cebolla(db, u, local, nuevo_item):
    empresa, _ = local
    burger, _, _, cebolla = armar_hamburguesa(db, u, empresa, nuevo_item)
    sin = calcular_costo_receta(db, empresa_id=empresa.id, item_id=burger.id, sin_ingredientes=[cebolla.id])
    assert sin.costo_total == Decimal("1574")          # 1.604 − 30
    assert "Cebolla" not in [l.nombre for l in sin.lineas]


def test_no_se_puede_quitar_un_ingrediente_que_no_es_removible(db, u, local, nuevo_item):
    empresa, _ = local
    burger, _, carne, _ = armar_hamburguesa(db, u, empresa, nuevo_item)
    with pytest.raises(ErrorNegocio, match="no son removibles"):
        calcular_costo_receta(db, empresa_id=empresa.id, item_id=burger.id, sin_ingredientes=[carne.id])


def test_el_costo_usa_el_mayor_entre_promedio_y_ultimo(db, u, local, nuevo_item):
    empresa, _ = local
    harina = nuevo_item(empresa, u["g"], "Harina",
                        costo_promedio=Decimal("2"), costo_ultimo=Decimal("1.5"))
    masa = nuevo_item(empresa, u["g"], "Masa", tipo=TipoItem.componente)
    guardar_receta(db, empresa_id=empresa.id, item_id=masa.id, rendimiento=1000,
                   lineas=[LineaReceta(harina.id, 1000)])
    assert calcular_costo_receta(db, empresa_id=empresa.id, item_id=masa.id).costo_unitario == Decimal("2")


def test_costo_de_un_item_sin_receta_o_ajeno_falla(db, u, local, otro_local, nuevo_item):
    empresa, _ = local
    ajena, _ = otro_local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    plato_ajeno = nuevo_item(ajena, u["und"], "Plato ajeno", tipo=TipoItem.vendible_preparado)
    with pytest.raises(ErrorNegocio, match="no tiene receta"):
        calcular_costo_receta(db, empresa_id=empresa.id, item_id=tomate.id)
    with pytest.raises(ErrorNegocio, match="no existe"):
        calcular_costo_receta(db, empresa_id=empresa.id, item_id=plato_ajeno.id)
