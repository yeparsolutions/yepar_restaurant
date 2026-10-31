# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_reservas.py
# Pruebas de reservar / consumir / liberar / mermar el stock de un pedido.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest

from errores import ErrorNegocio
from models import (EstadoReserva, Extra, ExtraPlato, MotivoMerma, MovimientoStock,
                    TipoItem, TipoMovimientoStock)
from servicios.compras import ingresar_compra
from servicios.recetas import LineaReceta, guardar_receta
from servicios.reservas import (calcular_necesidad, consumir_reserva, liberar_reserva,
                                mermar_reserva, reservar_linea)
from servicios.stock import aplicar_movimiento, obtener_stock


def comprar(db, empresa, sucursal, item, cantidad, costo="1"):
    ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=item.id,
                    cantidad=cantidad, costo_unitario_base=costo)


def stock(db, empresa, sucursal, item):
    return obtener_stock(db, empresa.id, item.id, sucursal.id)


@pytest.fixture()
def cocina(db, u, local, nuevo_item):
    """Hamburguesa = pan + carne 150 g + salsa de ajo 20 g (componente) + cebolla 30 g (removible)."""
    empresa, sucursal = local
    pan = nuevo_item(empresa, u["und"], "Pan")
    carne = nuevo_item(empresa, u["g"], "Carne")
    cebolla = nuevo_item(empresa, u["g"], "Cebolla")
    salsa = nuevo_item(empresa, u["g"], "Salsa de ajo", tipo=TipoItem.componente)
    tocineta = nuevo_item(empresa, u["g"], "Tocineta")
    cola = nuevo_item(empresa, u["und"], "Cola lata", tipo=TipoItem.vendible_reventa)
    burger = nuevo_item(empresa, u["und"], "Hamburguesa", tipo=TipoItem.vendible_preparado)
    guardar_receta(db, empresa_id=empresa.id, item_id=burger.id, rendimiento=1, lineas=[
        LineaReceta(pan.id, 1), LineaReceta(carne.id, 150), LineaReceta(salsa.id, 20),
        LineaReceta(cebolla.id, 30, es_removible=True)])
    extra = Extra(empresa_id=empresa.id, nombre="Extra tocineta", precio=Decimal("1000"),
                  ingrediente_id=tocineta.id, cantidad=Decimal("25"), aplica_a_todos=False)
    db.add(extra)
    db.flush()
    db.add(ExtraPlato(extra_id=extra.id, item_id=burger.id))
    for item, cant in ((pan, 50), (carne, 3000), (cebolla, 1000), (tocineta, 500), (cola, 24)):
        comprar(db, empresa, sucursal, item, cant)
    # La salsa no se compra: entra como si ya se hubiera producido un lote.
    aplicar_movimiento(db, stock=obtener_stock(db, empresa.id, salsa.id, sucursal.id),
                       tipo=TipoMovimientoStock.produccion_entrada, cantidad=500)
    db.commit()
    return dict(empresa=empresa, sucursal=sucursal, pan=pan, carne=carne, cebolla=cebolla, salsa=salsa,
                tocineta=tocineta, cola=cola, burger=burger, extra=extra)


def test_necesidad_baja_solo_un_nivel_y_multiplica_por_cantidad(db, cocina):
    c = cocina
    n = calcular_necesidad(db, empresa_id=c["empresa"].id, item_id=c["burger"].id, cantidad=2)
    assert n == {c["pan"].id: Decimal("2.000"), c["carne"].id: Decimal("300.000"),
                 c["salsa"].id: Decimal("40.000"), c["cebolla"].id: Decimal("60.000")}


def test_sin_cebolla_no_reserva_cebolla_y_extra_suma_tocineta(db, cocina):
    c = cocina
    n = calcular_necesidad(db, empresa_id=c["empresa"].id, item_id=c["burger"].id, cantidad=2,
                           sin_ingredientes=[c["cebolla"].id], extra_ids=[c["extra"].id])
    assert c["cebolla"].id not in n
    assert n[c["tocineta"].id] == Decimal("50.000")


def test_bebida_de_reventa_reserva_la_propia_lata(db, cocina):
    c = cocina
    assert calcular_necesidad(db, empresa_id=c["empresa"].id, item_id=c["cola"].id, cantidad=3) == \
        {c["cola"].id: Decimal("3.000")}


def test_reglas_de_la_linea(db, cocina, u, otro_local, nuevo_item):
    c = cocina
    emp = c["empresa"].id
    with pytest.raises(ErrorNegocio, match="no son removibles"):
        calcular_necesidad(db, empresa_id=emp, item_id=c["burger"].id, sin_ingredientes=[c["carne"].id])
    with pytest.raises(ErrorNegocio, match="no se vende"):
        calcular_necesidad(db, empresa_id=emp, item_id=c["carne"].id)
    with pytest.raises(ErrorNegocio, match="mayor que cero"):
        calcular_necesidad(db, empresa_id=emp, item_id=c["burger"].id, cantidad=0)
    with pytest.raises(ErrorNegocio, match="no existe"):
        calcular_necesidad(db, empresa_id=emp, item_id=c["burger"].id, extra_ids=[9999])
    with pytest.raises(ErrorNegocio, match="no tiene ingredientes que quitar"):
        calcular_necesidad(db, empresa_id=emp, item_id=c["cola"].id, sin_ingredientes=[c["pan"].id])
    # Un extra que solo aplica a la hamburguesa no se ofrece en la cola.
    with pytest.raises(ErrorNegocio, match="no se ofrece"):
        calcular_necesidad(db, empresa_id=emp, item_id=c["cola"].id, extra_ids=[c["extra"].id])
    ajena, _ = otro_local
    ajeno = nuevo_item(ajena, u["und"], "Cola ajena", tipo=TipoItem.vendible_reventa)
    with pytest.raises(ErrorNegocio, match="no existe"):
        calcular_necesidad(db, empresa_id=emp, item_id=ajeno.id)


def test_reservar_aparta_sin_tocar_el_stock_fisico(db, cocina):
    c = cocina
    r = reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id,
                       referencia_id=101, item_id=c["burger"].id, cantidad=2)
    carne = stock(db, c["empresa"], c["sucursal"], c["carne"])
    assert carne.cantidad_fisica == Decimal("3000")
    assert carne.cantidad_reservada == Decimal("300")
    assert carne.disponible == Decimal("2700")
    assert r.faltantes == []
    assert {x.estado for x in r.reservas} == {EstadoReserva.activa}


def test_si_falta_stock_no_bloquea_pero_avisa_cuanto_falta(db, cocina):
    c = cocina
    r = reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id,
                       referencia_id=102, item_id=c["burger"].id, cantidad=60)   # pan: hay 50
    # 60 hamburguesas necesitan más de lo que hay: pan (50), carne (3000 de 9000), salsa y cebolla.
    faltas = {f.nombre: f.falta for f in r.faltantes}
    assert faltas == {"Pan": Decimal("10.000"), "Carne": Decimal("6000.000"),
                      "Salsa de ajo": Decimal("700.000"), "Cebolla": Decimal("800.000")}
    assert stock(db, c["empresa"], c["sucursal"], c["pan"]).cantidad_reservada == Decimal("60")


def test_no_se_reserva_dos_veces_la_misma_linea(db, cocina):
    c = cocina
    datos = dict(empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=103,
                 item_id=c["burger"].id)
    reservar_linea(db, **datos)
    with pytest.raises(ErrorNegocio, match="ya tiene reservas"):
        reservar_linea(db, **datos)


def test_listo_consume_stock_fisico_y_libera_la_reserva(db, cocina):
    c = cocina
    reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=104,
                   item_id=c["burger"].id, cantidad=2, sin_ingredientes=[c["cebolla"].id])
    consumir_reserva(db, empresa_id=c["empresa"].id, referencia_id=104, usuario_id=None)

    carne = stock(db, c["empresa"], c["sucursal"], c["carne"])
    assert (carne.cantidad_fisica, carne.cantidad_reservada) == (Decimal("2700"), Decimal("0"))
    assert stock(db, c["empresa"], c["sucursal"], c["cebolla"]).cantidad_fisica == Decimal("1000")  # sin cebolla
    assert stock(db, c["empresa"], c["sucursal"], c["salsa"]).cantidad_fisica == Decimal("460")      # componente
    mov = db.query(MovimientoStock).filter_by(referencia_id="104", tipo=TipoMovimientoStock.consumo_venta).all()
    assert len(mov) == 3
    assert all(m.referencia_tipo == "linea_pedido" for m in mov)


def test_cancelar_antes_de_cocinar_libera_sin_mover_stock(db, cocina):
    c = cocina
    reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=105,
                   item_id=c["burger"].id)
    liberar_reserva(db, empresa_id=c["empresa"].id, referencia_id=105)
    carne = stock(db, c["empresa"], c["sucursal"], c["carne"])
    assert (carne.cantidad_fisica, carne.cantidad_reservada) == (Decimal("3000"), Decimal("0"))
    assert db.query(MovimientoStock).filter_by(referencia_id="105").count() == 0


def test_cancelar_en_preparacion_descuenta_y_anota_merma(db, cocina):
    c = cocina
    reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=106,
                   item_id=c["burger"].id)
    mermar_reserva(db, empresa_id=c["empresa"].id, referencia_id=106)
    carne = stock(db, c["empresa"], c["sucursal"], c["carne"])
    assert (carne.cantidad_fisica, carne.cantidad_reservada) == (Decimal("2850"), Decimal("0"))
    mermas = db.query(MovimientoStock).filter_by(referencia_id="106", tipo=TipoMovimientoStock.merma).all()
    assert len(mermas) == 4
    assert {m.motivo_merma for m in mermas} == {MotivoMerma.cancelacion_en_preparacion}


def test_una_reserva_cerrada_no_se_vuelve_a_cerrar(db, cocina):
    c = cocina
    reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=107,
                   item_id=c["burger"].id)
    consumir_reserva(db, empresa_id=c["empresa"].id, referencia_id=107)
    for cerrar in (consumir_reserva, liberar_reserva, mermar_reserva):
        with pytest.raises(ErrorNegocio, match="No hay reservas activas"):
            cerrar(db, empresa_id=c["empresa"].id, referencia_id=107)


def test_dos_clientes_con_la_misma_referencia_no_se_mezclan(db, cocina, otro_local):
    c = cocina
    ajena, _ = otro_local
    reservar_linea(db, empresa_id=c["empresa"].id, sucursal_id=c["sucursal"].id, referencia_id=1,
                   item_id=c["burger"].id)
    with pytest.raises(ErrorNegocio, match="No hay reservas activas"):
        consumir_reserva(db, empresa_id=ajena.id, referencia_id=1)
