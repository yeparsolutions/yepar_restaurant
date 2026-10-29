# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_cocina.py
# Pruebas de cocina y barra (servicios/cocina.py).
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest

from errores import ErrorNegocio
from models import (EstacionCocina, EstadoLinea, EstadoReserva, MovimientoStock, ReservaStock,
                    RolUsuario, TipoMovimientoStock)
from servicios.cocina import (comandas_pendientes, iniciar_preparacion, marcar_agotado,
                              marcar_entregada, marcar_lista, reponer_agotado, retiros_pendientes)
from servicios.disponibilidad import catalogo_mesero
from servicios.mesas import estado_mesas
from servicios.pedidos import abrir_pedido, cancelar_linea, enviar_pedido, pedir_cuenta, tomar_linea
from servicios.stock import obtener_stock


def abrir(db, s, mesa="m1", mesero="ana"):
    return abrir_pedido(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id, mesa_id=s[mesa].id,
                        mesero_id=s[mesero].id)


def tomar(db, s, pedido, item="burger", **datos):
    return tomar_linea(db, empresa_id=s["empresa"].id, pedido_id=pedido.id, item_id=s[item].id, **datos).linea


def enviar(db, s, pedido):
    return enviar_pedido(db, empresa_id=s["empresa"].id, pedido_id=pedido.id)


def fisico(db, s, item):
    return obtener_stock(db, s["empresa"].id, s[item].id, s["sucursal"].id).cantidad_fisica


@pytest.fixture()
def equipo(db, salon, nuevo_usuario):
    """Un cocinero de cocina, un barman y un administrador."""
    e = salon["empresa"]
    salon["chef"] = nuevo_usuario(e, "Chef", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.cocina)
    salon["barman"] = nuevo_usuario(e, "Barman", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.barra)
    salon["admin"] = nuevo_usuario(e, "Admin", roles=(RolUsuario.administrador,))
    return salon


def preparar(db, s, usuario="chef", **kw):
    """Abre mesa, toma una hamburguesa, la envía y devuelve (pedido, línea)."""
    pedido = abrir(db, s)
    linea = tomar(db, s, pedido, **kw)
    enviar(db, s, pedido)
    return pedido, linea


# ── Cambios de estado ────────────────────────────────────────
def test_flujo_completo_nuevo_preparacion_lista_entregada(db, equipo):
    s = equipo
    pedido, linea = preparar(db, s, cantidad=2)
    e = s["empresa"].id

    iniciar_preparacion(db, empresa_id=e, linea_id=linea.id, usuario_id=s["chef"].id)
    assert linea.estado == EstadoLinea.en_preparacion and linea.preparacion_en is not None
    assert fisico(db, s, "carne") == Decimal("3000")                 # aún no sale de la bodega

    r = marcar_lista(db, empresa_id=e, linea_id=linea.id, usuario_id=s["chef"].id)
    assert linea.estado == EstadoLinea.lista and linea.lista_en is not None
    assert r.sin_stock == []
    assert fisico(db, s, "carne") == Decimal("2700")                 # ahora sí se descuenta
    assert obtener_stock(db, e, s["carne"].id, s["sucursal"].id).cantidad_reservada == Decimal("0")
    assert {x.estado for x in db.query(ReservaStock)} == {EstadoReserva.consumida}

    marcar_entregada(db, empresa_id=e, linea_id=linea.id)
    assert linea.estado == EstadoLinea.entregada and linea.entregada_en is not None


def test_se_puede_marcar_lista_sin_pasar_por_preparacion(db, equipo):
    s = equipo
    _, linea = preparar(db, s)
    marcar_lista(db, empresa_id=s["empresa"].id, linea_id=linea.id, usuario_id=s["chef"].id)
    assert linea.estado == EstadoLinea.lista


def test_listo_descuenta_con_el_costo_y_el_usuario(db, equipo):
    s = equipo
    _, linea = preparar(db, s)
    marcar_lista(db, empresa_id=s["empresa"].id, linea_id=linea.id, usuario_id=s["chef"].id)
    movs = db.query(MovimientoStock).filter_by(tipo=TipoMovimientoStock.consumo_venta).all()
    assert len(movs) == 3 and {m.usuario_id for m in movs} == {s["chef"].id}


def test_marcar_lista_avisa_los_ingredientes_que_quedaron_en_negativo(db, equipo):
    s = equipo
    pedido = abrir(db, s)
    linea = tomar(db, s, pedido, cantidad=60)                        # pan: hay 50
    enviar(db, s, pedido)
    r = marcar_lista(db, empresa_id=s["empresa"].id, linea_id=linea.id, usuario_id=s["chef"].id)
    assert "Pan" in r.sin_stock and fisico(db, s, "pan") == Decimal("-10")


def test_transiciones_invalidas(db, equipo):
    s = equipo
    e = s["empresa"].id
    _, linea = preparar(db, s)
    with pytest.raises(ErrorNegocio, match="solo se entrega uno que ya está listo"):
        marcar_entregada(db, empresa_id=e, linea_id=linea.id)
    iniciar_preparacion(db, empresa_id=e, linea_id=linea.id, usuario_id=s["chef"].id)
    with pytest.raises(ErrorNegocio, match="recién enviado"):
        iniciar_preparacion(db, empresa_id=e, linea_id=linea.id, usuario_id=s["chef"].id)
    marcar_lista(db, empresa_id=e, linea_id=linea.id, usuario_id=s["chef"].id)
    with pytest.raises(ErrorNegocio, match="no se puede marcar como listo"):
        marcar_lista(db, empresa_id=e, linea_id=linea.id, usuario_id=s["chef"].id)


def test_un_plato_solo_anotado_no_llega_a_cocina(db, equipo):
    s = equipo
    pedido = abrir(db, s)
    linea = tomar(db, s, pedido)                                    # tomada, sin enviar
    with pytest.raises(ErrorNegocio, match="recién enviado"):
        iniciar_preparacion(db, empresa_id=s["empresa"].id, linea_id=linea.id, usuario_id=s["chef"].id)


def test_la_estacion_manda_cada_plato_a_su_cocinero(db, equipo):
    s = equipo
    e = s["empresa"].id
    pedido = abrir(db, s)
    plato = tomar(db, s, pedido)
    trago = tomar(db, s, pedido, item="cola")                       # barra
    enviar(db, s, pedido)
    with pytest.raises(ErrorNegocio, match="atiende la barra"):
        iniciar_preparacion(db, empresa_id=e, linea_id=plato.id, usuario_id=s["barman"].id)
    with pytest.raises(ErrorNegocio, match="atiende la cocina"):
        marcar_lista(db, empresa_id=e, linea_id=trago.id, usuario_id=s["chef"].id)
    marcar_lista(db, empresa_id=e, linea_id=trago.id, usuario_id=s["barman"].id)
    marcar_lista(db, empresa_id=e, linea_id=plato.id, usuario_id=s["admin"].id)     # el admin puede todo


def test_un_mesero_no_maneja_la_cocina(db, equipo):
    s = equipo
    _, linea = preparar(db, s)
    with pytest.raises(ErrorNegocio, match="no trabaja en cocina"):
        marcar_lista(db, empresa_id=s["empresa"].id, linea_id=linea.id, usuario_id=s["ana"].id)


def test_otro_cliente_no_toca_mis_comandas(db, equipo, otro_local, nuevo_usuario):
    ajena, _ = otro_local
    chef_ajeno = nuevo_usuario(ajena, "Chef ajeno", roles=(RolUsuario.cocinero,))
    _, linea = preparar(db, equipo)
    with pytest.raises(ErrorNegocio, match="no existe"):
        marcar_lista(db, empresa_id=ajena.id, linea_id=linea.id, usuario_id=chef_ajeno.id)


def test_un_plato_cancelado_ya_no_se_prepara(db, equipo):
    s = equipo
    _, linea = preparar(db, s)
    cancelar_linea(db, empresa_id=s["empresa"].id, linea_id=linea.id)
    with pytest.raises(ErrorNegocio, match="recién enviado"):
        iniciar_preparacion(db, empresa_id=s["empresa"].id, linea_id=linea.id, usuario_id=s["chef"].id)


def test_cancelar_en_preparacion_con_el_flujo_real_pasa_a_merma(db, equipo):
    s = equipo
    e = s["empresa"].id
    _, linea = preparar(db, s)
    iniciar_preparacion(db, empresa_id=e, linea_id=linea.id, usuario_id=s["chef"].id)
    cancelar_linea(db, empresa_id=e, linea_id=linea.id)
    assert fisico(db, s, "carne") == Decimal("2850")
    assert db.query(MovimientoStock).filter_by(tipo=TipoMovimientoStock.merma).count() == 3


def test_con_la_cuenta_pedida_cocina_igual_termina_lo_que_falta(db, equipo):
    s = equipo
    pedido, linea = preparar(db, s)
    pedir_cuenta(db, empresa_id=s["empresa"].id, pedido_id=pedido.id)
    marcar_lista(db, empresa_id=s["empresa"].id, linea_id=linea.id, usuario_id=s["chef"].id)
    assert linea.estado == EstadoLinea.lista


# ── Pantallas ────────────────────────────────────────────────
def test_pantalla_de_comandas_por_estacion_y_en_orden_de_llegada(db, equipo):
    s = equipo
    e, suc = s["empresa"].id, s["sucursal"].id
    p1 = abrir(db, s, mesa="m1")
    tomar(db, s, p1, sin_ingredientes=[s["cebolla"].id], extra_ids=[s["extra"].id], comensal=2, nota="bien cocida")
    enviar(db, s, p1)
    p2 = abrir(db, s, mesa="m2", mesero="beto")
    tomar(db, s, p2, item="cola", cantidad=2)
    enviar(db, s, p2)

    cocina = comandas_pendientes(db, empresa_id=e, sucursal_id=suc, estacion=EstacionCocina.cocina)
    assert len(cocina) == 1
    c = cocina[0]
    assert (c.mesa, c.plato, c.cantidad, c.comensal, c.nota) == ("Mesa 1", "Hamburguesa", 1, 2, "bien cocida")
    assert c.sin == ["Cebolla"] and c.extras == ["Extra tocineta"] and c.receta_id is not None
    assert c.mesero_id == s["ana"].id

    barra = comandas_pendientes(db, empresa_id=e, sucursal_id=suc, estacion=EstacionCocina.barra)
    assert [(x.mesa, x.plato, x.cantidad) for x in barra] == [("Mesa 2", "Cola lata", 2)]
    assert len(comandas_pendientes(db, empresa_id=e, sucursal_id=suc)) == 2          # sin filtro: todo


def test_lo_listo_sale_de_comandas_y_aparece_como_retiro_para_su_mesero(db, equipo):
    s = equipo
    e, suc = s["empresa"].id, s["sucursal"].id
    _, linea = preparar(db, s)
    marcar_lista(db, empresa_id=e, linea_id=linea.id, usuario_id=s["chef"].id)
    assert comandas_pendientes(db, empresa_id=e, sucursal_id=suc) == []
    retiros = retiros_pendientes(db, empresa_id=e, sucursal_id=suc, mesero_id=s["ana"].id)
    assert [(r.mesa, r.plato, r.estacion) for r in retiros] == [("Mesa 1", "Hamburguesa", "cocina")]
    assert retiros_pendientes(db, empresa_id=e, sucursal_id=suc, mesero_id=s["beto"].id) == []
    marcar_entregada(db, empresa_id=e, linea_id=linea.id)
    assert retiros_pendientes(db, empresa_id=e, sucursal_id=suc) == []


def test_la_mesa_se_enciende_cuando_cocina_marca_listo(db, equipo):
    s = equipo
    _, linea = preparar(db, s)
    marcar_lista(db, empresa_id=s["empresa"].id, linea_id=linea.id, usuario_id=s["chef"].id)
    plano = {m.nombre: m for m in estado_mesas(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id)}
    assert plano["Mesa 1"].estado == "lista" and plano["Mesa 1"].lineas_listas == 1
    marcar_entregada(db, empresa_id=s["empresa"].id, linea_id=linea.id)
    plano = {m.nombre: m for m in estado_mesas(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id)}
    assert plano["Mesa 1"].estado == "ocupada"


# ── Se acabó ─────────────────────────────────────────────────
def test_se_acabo_un_ingrediente_deja_agotados_los_platos_que_lo_usan(db, equipo):
    s = equipo
    e = s["empresa"].id
    platos = marcar_agotado(db, empresa_id=e, item_id=s["carne"].id, usuario_id=s["chef"].id)
    assert platos == ["Hamburguesa"]
    catalogo = {x.nombre: x.alcanza for x in catalogo_mesero(db, empresa_id=e, sucursal_id=s["sucursal"].id)}
    assert catalogo == {"Hamburguesa": False, "Cola lata": True}
    reponer_agotado(db, empresa_id=e, item_id=s["carne"].id, usuario_id=s["chef"].id)
    catalogo = {x.nombre: x.alcanza for x in catalogo_mesero(db, empresa_id=e, sucursal_id=s["sucursal"].id)}
    assert catalogo["Hamburguesa"] is True


def test_se_acabo_una_bebida_se_agota_ella_misma(db, equipo):
    s = equipo
    assert marcar_agotado(db, empresa_id=s["empresa"].id, item_id=s["cola"].id,
                          usuario_id=s["barman"].id) == ["Cola lata"]


def test_solo_cocina_marca_agotado_y_dentro_de_su_cliente(db, equipo, otro_local, nuevo_item, u):
    s = equipo
    with pytest.raises(ErrorNegocio, match="no trabaja en cocina"):
        marcar_agotado(db, empresa_id=s["empresa"].id, item_id=s["carne"].id, usuario_id=s["ana"].id)
    ajena, _ = otro_local
    ajeno = nuevo_item(ajena, u["g"], "Harina ajena")
    with pytest.raises(ErrorNegocio, match="no existe"):
        marcar_agotado(db, empresa_id=s["empresa"].id, item_id=ajeno.id, usuario_id=s["chef"].id)
