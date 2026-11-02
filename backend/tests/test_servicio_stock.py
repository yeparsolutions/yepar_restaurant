# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_stock.py
# Pruebas del libro de movimientos de stock (servicios/stock.py).
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest

from errores import ErrorNegocio
from models import MotivoMerma, TipoMovimientoStock
from servicios.stock import (aplicar_movimiento, cargar_item, obtener_stock,
                             total_fisico_item, validar_sucursal)


def test_obtener_stock_crea_la_fila_en_cero_y_la_reutiliza(db, u, local, nuevo_item):
    empresa, sucursal = local
    carne = nuevo_item(empresa, u["g"], "Carne")
    primero = obtener_stock(db, empresa.id, carne.id, sucursal.id)
    segundo = obtener_stock(db, empresa.id, carne.id, sucursal.id)
    assert primero.id == segundo.id
    assert primero.cantidad_fisica == Decimal("0")


def test_movimiento_actualiza_saldo_y_deja_anterior_y_nuevo(db, u, local, nuevo_item):
    empresa, sucursal = local
    carne = nuevo_item(empresa, u["g"], "Carne")
    stock = obtener_stock(db, empresa.id, carne.id, sucursal.id)

    entrada = aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.compra, cantidad=1000)
    salida = aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.consumo_venta, cantidad=-150)

    assert (entrada.stock_anterior, entrada.stock_nuevo) == (Decimal("0"), Decimal("1000"))
    assert (salida.stock_anterior, salida.stock_nuevo) == (Decimal("1000"), Decimal("850"))
    assert stock.cantidad_fisica == Decimal("850")


def test_el_saldo_puede_quedar_negativo(db, u, local, nuevo_item):
    """Faltar un ingrediente solo alerta: el movimiento no se bloquea."""
    empresa, sucursal = local
    queso = nuevo_item(empresa, u["g"], "Queso")
    stock = obtener_stock(db, empresa.id, queso.id, sucursal.id)
    mov = aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.consumo_venta, cantidad=-40)
    assert mov.stock_nuevo == Decimal("-40")


def test_cantidad_cero_se_rechaza(db, u, local, nuevo_item):
    empresa, sucursal = local
    pan = nuevo_item(empresa, u["und"], "Pan")
    stock = obtener_stock(db, empresa.id, pan.id, sucursal.id)
    with pytest.raises(ErrorNegocio, match="cantidad cero"):
        aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.compra, cantidad=0)


def test_el_signo_debe_coincidir_con_el_tipo(db, u, local, nuevo_item):
    empresa, sucursal = local
    pan = nuevo_item(empresa, u["und"], "Pan")
    stock = obtener_stock(db, empresa.id, pan.id, sucursal.id)
    with pytest.raises(ErrorNegocio, match="entrada"):
        aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.compra, cantidad=-5)
    with pytest.raises(ErrorNegocio, match="salida"):
        aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.merma, cantidad=5,
                           motivo_merma=MotivoMerma.vencido)
    # El ajuste de inventario puede ir hacia cualquier lado.
    aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.ajuste_inventario, cantidad=-3)
    aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.ajuste_inventario, cantidad=8)
    assert stock.cantidad_fisica == Decimal("5")


def test_toda_merma_necesita_motivo_y_solo_ellas(db, u, local, nuevo_item):
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    stock = obtener_stock(db, empresa.id, tomate.id, sucursal.id)
    with pytest.raises(ErrorNegocio, match="necesita un motivo"):
        aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.merma, cantidad=-100)
    with pytest.raises(ErrorNegocio, match="Solo las mermas"):
        aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.compra, cantidad=100,
                           motivo_merma=MotivoMerma.vencido)
    mov = aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.merma, cantidad=-100,
                             motivo_merma=MotivoMerma.derrame)
    assert mov.motivo_merma == MotivoMerma.derrame


def test_referencia_se_guarda_como_texto(db, u, local, nuevo_item):
    empresa, sucursal = local
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    stock = obtener_stock(db, empresa.id, tomate.id, sucursal.id)
    mov = aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.compra, cantidad=10,
                             referencia_tipo="compra", referencia_id=42)
    assert mov.referencia_id == "42"


def test_total_fisico_suma_todas_las_sucursales(db, u, local, nuevo_item):
    from models import Sucursal
    empresa, sucursal = local
    otra = Sucursal(empresa_id=empresa.id, nombre="Segundo local")
    db.add(otra)
    db.commit()
    tomate = nuevo_item(empresa, u["g"], "Tomate")
    aplicar_movimiento(db, stock=obtener_stock(db, empresa.id, tomate.id, sucursal.id),
                       tipo=TipoMovimientoStock.compra, cantidad=1000)
    aplicar_movimiento(db, stock=obtener_stock(db, empresa.id, tomate.id, otra.id),
                       tipo=TipoMovimientoStock.compra, cantidad=500)
    assert total_fisico_item(db, tomate.id) == Decimal("1500")


def test_no_se_ve_el_item_ni_la_sucursal_de_otro_cliente(db, u, local, otro_local, nuevo_item):
    empresa, _ = local
    ajena, sucursal_ajena = otro_local
    item_ajeno = nuevo_item(ajena, u["g"], "Harina de la pizzería")
    with pytest.raises(ErrorNegocio, match="no existe"):
        cargar_item(db, empresa.id, item_ajeno.id)
    with pytest.raises(ErrorNegocio, match="no existe"):
        validar_sucursal(db, empresa.id, sucursal_ajena.id)
