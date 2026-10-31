# ============================================================
# YEPAR RESTAURANT — backend/tests/test_nucleo_inventario.py
# Pruebas del núcleo de inventario: unidades, recetas, stock y costos.
#
# Cada prueba usa una base SQLite en memoria, nueva y vacía, así que
# no dependen una de otra ni tocan datos reales.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from models import (Empresa, Extra, Item, ItemPresentacion, MotivoMerma,
                    MovimientoStock, Receta, RecetaLinea, StockSucursal,
                    Sucursal, TipoItem, TipoMovimientoStock, Unidad, Usuario,
                    UsuarioRol, RolUsuario)
from semilla import sembrar_unidades
from unidades import (ErrorUnidades, a_decimal, convertir_a_unidad_base,
                      costo_de_referencia, costo_por_unidad_base,
                      costo_promedio_ponderado, exigir_unidad_base)


# Los fixtures db, u y local viven en conftest.py (compartidos por todas las pruebas).


def crear_item(db, empresa, unidad_base, nombre, tipo=TipoItem.materia_prima, **extra):
    item = Item(empresa_id=empresa.id, tipo=tipo, nombre=nombre,
                unidad_base_id=unidad_base.id, **extra)
    db.add(item)
    db.commit()
    return item


# ============================================================
# UNIDADES Y CONVERSIONES
# ============================================================
def test_semilla_es_idempotente(db):
    sembrar_unidades(db)
    sembrar_unidades(db)
    assert db.query(Unidad).count() == 7


def test_comprar_kilo_de_tomate_suma_mil_gramos(db, u, local):
    empresa, _ = local
    tomate = crear_item(db, empresa, u["g"], "Tomate")
    assert convertir_a_unidad_base(tomate, 1, unidad=u["kg"]) == Decimal("1000.000")
    assert convertir_a_unidad_base(tomate, "2.5", unidad=u["kg"]) == Decimal("2500.000")


def test_cc_y_litro_convierten_a_ml(db, u, local):
    empresa, _ = local
    jugo = crear_item(db, empresa, u["ml"], "Jugo de naranja")
    assert convertir_a_unidad_base(jugo, 300, unidad=u["cc"]) == Decimal("300.000")
    assert convertir_a_unidad_base(jugo, "1.5", unidad=u["l"]) == Decimal("1500.000")


def test_no_se_mezcla_peso_con_volumen(db, u, local):
    empresa, _ = local
    tomate = crear_item(db, empresa, u["g"], "Tomate")
    with pytest.raises(ErrorUnidades, match="familias distintas"):
        convertir_a_unidad_base(tomate, 1, unidad=u["l"])


def test_presentacion_caja_de_12(db, u, local):
    empresa, _ = local
    lata = crear_item(db, empresa, u["und"], "Bebida lata", tipo=TipoItem.vendible_reventa)
    caja = ItemPresentacion(item_id=lata.id, nombre="Caja 12 un", cantidad_en_base=Decimal("12"))
    db.add(caja)
    db.commit()
    assert convertir_a_unidad_base(lata, 3, presentacion=caja) == Decimal("36.000")


def test_exige_una_sola_forma_de_origen(db, u, local):
    empresa, _ = local
    tomate = crear_item(db, empresa, u["g"], "Tomate")
    with pytest.raises(ErrorUnidades):
        convertir_a_unidad_base(tomate, 1)                          # ni unidad ni presentación
    with pytest.raises(ErrorUnidades):
        convertir_a_unidad_base(tomate, 0, unidad=u["kg"])          # cantidad cero


def test_kilo_no_puede_ser_unidad_base(u):
    exigir_unidad_base(u["g"])               # ok
    with pytest.raises(ErrorUnidades):
        exigir_unidad_base(u["kg"])


def test_float_no_arrastra_errores_binarios():
    # 0.1 + 0.2 en float da 0.30000000000000004; con a_decimal es exacto.
    assert a_decimal(0.1) + a_decimal(0.2) == Decimal("0.3")


# ============================================================
# COSTOS
# ============================================================
def test_costo_por_gramo():
    assert costo_por_unidad_base(1500, 1000) == Decimal("1.500000")


def test_promedio_ponderado_y_referencia_al_mas_alto():
    # Había 1000 g a $1,5/g y se compran otros 1000 g a $1,8/g.
    promedio = costo_promedio_ponderado(1000, "1.5", 1000, "1.8")
    assert promedio == Decimal("1.650000")
    # La referencia apunta al más alto: el último precio ($1,8) gana al promedio.
    assert costo_de_referencia(promedio, "1.8") == Decimal("1.8")
    # Si el último precio fuera más bajo que el promedio, gana el promedio.
    assert costo_de_referencia("1.65", "1.2") == Decimal("1.65")


def test_promedio_con_stock_negativo_toma_costo_nuevo():
    # Se vendió de más antes de comprar: no hay nada que promediar.
    assert costo_promedio_ponderado(-50, "1.5", 1000, "1.8") == Decimal("1.800000")


def test_item_costo_referencia(db, u, local):
    empresa, _ = local
    tomate = crear_item(db, empresa, u["g"], "Tomate",
                        costo_promedio=Decimal("1.65"), costo_ultimo=Decimal("1.8"))
    assert tomate.costo_referencia == Decimal("1.8")


# ============================================================
# RECETAS
# ============================================================
def armar_hamburguesa(db, u, empresa):
    """Hamburguesa = pan + carne + salsa de ajo (componente) + cebolla (removible)."""
    pan    = crear_item(db, empresa, u["und"], "Pan de hamburguesa")
    carne  = crear_item(db, empresa, u["g"], "Carne molida")
    cebolla = crear_item(db, empresa, u["g"], "Cebolla")
    mayo   = crear_item(db, empresa, u["g"], "Mayonesa")
    ajo    = crear_item(db, empresa, u["g"], "Ajo")

    # Componente: 1 lote rinde 1000 g de salsa de ajo (900 g mayonesa + 100 g ajo).
    salsa = crear_item(db, empresa, u["g"], "Salsa de ajo", tipo=TipoItem.componente)
    r_salsa = Receta(empresa_id=empresa.id, item_id=salsa.id, rendimiento=Decimal("1000"))
    r_salsa.lineas = [
        RecetaLinea(ingrediente_id=mayo.id, cantidad=Decimal("900"), orden=1),
        RecetaLinea(ingrediente_id=ajo.id,  cantidad=Decimal("100"), orden=2),
    ]
    db.add(r_salsa)

    # Vendible preparado: rinde 1 und.
    burger = crear_item(db, empresa, u["und"], "Hamburguesa especial",
                        tipo=TipoItem.vendible_preparado, precio_venta=Decimal("6500"))
    r_burger = Receta(empresa_id=empresa.id, item_id=burger.id, rendimiento=Decimal("1"),
                      instrucciones="Sellar la carne 3 min por lado.")
    r_burger.lineas = [
        RecetaLinea(ingrediente_id=pan.id,     cantidad=Decimal("1"),   orden=1),
        RecetaLinea(ingrediente_id=carne.id,   cantidad=Decimal("150"), orden=2),
        RecetaLinea(ingrediente_id=salsa.id,   cantidad=Decimal("20"),  orden=3),
        RecetaLinea(ingrediente_id=cebolla.id, cantidad=Decimal("30"),  orden=4, es_removible=True),
    ]
    db.add(r_burger)
    db.commit()
    return burger, salsa, cebolla


def test_receta_con_componente_y_removible(db, u, local):
    empresa, _ = local
    burger, salsa, cebolla = armar_hamburguesa(db, u, empresa)

    assert burger.es_vendible and burger.lleva_receta
    assert salsa.lleva_receta and not salsa.es_vendible
    assert len(burger.receta.lineas) == 4

    removibles = [l.ingrediente.nombre for l in burger.receta.lineas if l.es_removible]
    assert removibles == ["Cebolla"]
    # Un componente puede ser ingrediente de un plato.
    assert salsa.id in [l.ingrediente_id for l in burger.receta.lineas]


def test_costo_teorico_del_plato(db, u, local):
    """Costo del plato = suma(cantidad × costo de referencia) / rendimiento."""
    empresa, _ = local
    burger, salsa, _ = armar_hamburguesa(db, u, empresa)

    # Costos por gramo/unidad (valores de ejemplo).
    costos = {"Pan de hamburguesa": "300", "Carne molida": "8", "Cebolla": "1",
              "Mayonesa": "3", "Ajo": "10"}
    for linea in burger.receta.lineas + salsa.receta.lineas:
        if linea.ingrediente.nombre in costos:
            linea.ingrediente.costo_ultimo = Decimal(costos[linea.ingrediente.nombre])
    db.commit()

    # Costo por gramo de salsa = (900×3 + 100×10) / 1000 = 3,7
    costo_lote = sum(l.cantidad * l.ingrediente.costo_referencia for l in salsa.receta.lineas)
    costo_salsa = costo_lote / salsa.receta.rendimiento
    assert costo_salsa == Decimal("3.7")
    salsa.costo_ultimo = costo_salsa

    # Plato = pan 300 + carne 150×8 + salsa 20×3,7 + cebolla 30×1 = 1604
    total = sum(l.cantidad * l.ingrediente.costo_referencia for l in burger.receta.lineas)
    assert total / burger.receta.rendimiento == Decimal("1604.0")


def test_una_sola_receta_por_item(db, u, local):
    empresa, _ = local
    burger, _, _ = armar_hamburguesa(db, u, empresa)
    db.add(Receta(empresa_id=empresa.id, item_id=burger.id, rendimiento=Decimal("1")))
    with pytest.raises(IntegrityError):
        db.commit()


def test_ingrediente_no_se_repite_en_la_misma_receta(db, u, local):
    empresa, _ = local
    burger, _, cebolla = armar_hamburguesa(db, u, empresa)
    db.add(RecetaLinea(receta_id=burger.receta.id, ingrediente_id=cebolla.id, cantidad=Decimal("5")))
    with pytest.raises(IntegrityError):
        db.commit()


def test_rendimiento_y_cantidades_deben_ser_positivos(db, u, local):
    empresa, _ = local
    plato = crear_item(db, empresa, u["und"], "Plato", tipo=TipoItem.vendible_preparado)
    db.add(Receta(empresa_id=empresa.id, item_id=plato.id, rendimiento=Decimal("0")))
    with pytest.raises(IntegrityError):
        db.commit()


# ============================================================
# EXTRAS
# ============================================================
def test_extra_tocineta(db, u, local):
    empresa, _ = local
    tocineta = crear_item(db, empresa, u["g"], "Tocineta")
    extra = Extra(empresa_id=empresa.id, nombre="Extra tocineta", precio=Decimal("1200"),
                  ingrediente_id=tocineta.id, cantidad=Decimal("30"))
    db.add(extra)
    db.commit()
    assert extra.aplica_a_todos is True and extra.activo is True


# ============================================================
# STOCK Y MOVIMIENTOS
# ============================================================
def test_disponible_es_fisico_menos_reservado(db, u, local):
    empresa, sucursal = local
    carne = crear_item(db, empresa, u["g"], "Carne molida")
    stock = StockSucursal(empresa_id=empresa.id, item_id=carne.id, sucursal_id=sucursal.id,
                          cantidad_fisica=Decimal("5000"), cantidad_reservada=Decimal("450"))
    db.add(stock)
    db.commit()
    assert stock.disponible == Decimal("4550")


def test_el_stock_puede_quedar_negativo(db, u, local):
    """Faltar un ingrediente solo alerta: no hay CHECK que lo impida."""
    empresa, sucursal = local
    queso = crear_item(db, empresa, u["g"], "Queso")
    stock = StockSucursal(empresa_id=empresa.id, item_id=queso.id, sucursal_id=sucursal.id,
                          cantidad_fisica=Decimal("-40"))
    db.add(stock)
    db.commit()
    assert stock.disponible == Decimal("-40")


def test_un_stock_por_item_y_sucursal(db, u, local):
    empresa, sucursal = local
    carne = crear_item(db, empresa, u["g"], "Carne molida")
    for _ in range(2):
        db.add(StockSucursal(empresa_id=empresa.id, item_id=carne.id, sucursal_id=sucursal.id))
    with pytest.raises(IntegrityError):
        db.commit()


def test_movimiento_compra_y_merma(db, u, local):
    empresa, sucursal = local
    tomate = crear_item(db, empresa, u["g"], "Tomate")
    entrada = MovimientoStock(
        empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=tomate.id,
        tipo=TipoMovimientoStock.compra, cantidad=Decimal("1000"),
        stock_anterior=Decimal("0"), stock_nuevo=Decimal("1000"),
        costo_unitario=Decimal("1.5"), referencia_tipo="compra", referencia_id="42")
    merma = MovimientoStock(
        empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=tomate.id,
        tipo=TipoMovimientoStock.merma, cantidad=Decimal("-200"),
        stock_anterior=Decimal("1000"), stock_nuevo=Decimal("800"),
        motivo_merma=MotivoMerma.vencido)
    db.add_all([entrada, merma])
    db.commit()
    assert merma.motivo_merma == MotivoMerma.vencido


# ============================================================
# ENUMS COMO TEXTO Y ROLES
# ============================================================
def test_enums_se_guardan_como_texto_simple(db, u, local):
    """Lección de Carora: nada de tipos nativos de PostgreSQL para los Enum."""
    empresa, _ = local
    crear_item(db, empresa, u["g"], "Tomate", tipo=TipoItem.materia_prima)
    valor = db.execute(text("SELECT tipo FROM items")).scalar()
    assert valor == "materia_prima"


def test_texto_invalido_en_enum_se_rechaza(db, u, local):
    empresa, _ = local
    item = Item(empresa_id=empresa.id, tipo="inventado", nombre="X", unidad_base_id=u["g"].id)
    db.add(item)
    with pytest.raises(Exception):
        db.commit()


def test_un_usuario_puede_tener_varios_roles(db, local):
    empresa, sucursal = local
    dueno = Usuario(empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Dueño",
                    username="dueno", password_hash="x")
    dueno.roles = [UsuarioRol(rol=RolUsuario.administrador), UsuarioRol(rol=RolUsuario.cajero)]
    db.add(dueno)
    db.commit()
    assert {r.rol for r in dueno.roles} == {RolUsuario.administrador, RolUsuario.cajero}

    dueno.roles.append(UsuarioRol(rol=RolUsuario.cajero))     # repetido
    with pytest.raises(IntegrityError):
        db.commit()


def test_unidad_base_siempre_vale_uno(db):
    from models.enums import FamiliaUnidad
    db.add(Unidad(codigo="kgx", nombre="Falsa", familia=FamiliaUnidad.peso,
                  factor_a_base=Decimal("1000"), es_base=True))
    with pytest.raises(IntegrityError):
        db.commit()
