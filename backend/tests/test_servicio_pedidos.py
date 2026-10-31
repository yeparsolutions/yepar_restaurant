# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_pedidos.py
# Pruebas del pedido de una mesa (servicios/pedidos.py).
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from errores import ErrorNegocio
from models import (EstacionCocina, EstadoLinea, EstadoPedido, EstadoReserva, Extra,
                    ExtraPlato, MotivoMerma, MovimientoStock, Pedido, ReservaStock,
                    RolUsuario, TipoItem, TipoMovimientoStock)
from servicios.compras import ingresar_compra
from servicios.mesas import crear_mesa, estado_mesas
from servicios.pedidos import (abrir_pedido, anular_pedido, cancelar_linea, enviar_pedido,
                               pedir_cuenta, quitar_linea_tomada, tomar_linea, traspasar_mesero)
from servicios.recetas import LineaReceta, guardar_receta
from servicios.stock import obtener_stock


def abrir(db, s, mesa="m1", mesero="ana", **datos):
    return abrir_pedido(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id, mesa_id=s[mesa].id,
                        mesero_id=s[mesero].id, **datos)


def tomar(db, s, pedido, item="burger", **datos):
    return tomar_linea(db, empresa_id=s["empresa"].id, pedido_id=pedido.id, item_id=s[item].id, **datos)


def reservado(db, s, item):
    return obtener_stock(db, s["empresa"].id, s[item].id, s["sucursal"].id).cantidad_reservada


# ── Abrir ────────────────────────────────────────────────────
def test_abrir_pedido_ancla_la_mesa_al_mesero(db, salon):
    pedido = abrir(db, salon, comensales=4)
    assert (pedido.estado, pedido.mesero_id, pedido.comensales) == (EstadoPedido.abierto, salon["ana"].id, 4)


def test_una_mesa_ocupada_no_se_abre_otra_vez_pero_otra_mesa_si(db, salon):
    abrir(db, salon)
    with pytest.raises(ErrorNegocio, match="ya está ocupada"):
        abrir(db, salon, mesero="beto")
    abrir(db, salon, mesa="m2", mesero="beto")


def test_la_base_tambien_impide_dos_cuentas_abiertas_en_la_misma_mesa(db, salon):
    abrir(db, salon)
    db.add(Pedido(empresa_id=salon["empresa"].id, sucursal_id=salon["sucursal"].id, mesa_id=salon["m1"].id,
                  mesero_id=salon["ana"].id))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_una_mesa_se_puede_reabrir_cuando_la_cuenta_anterior_se_cerro(db, salon):
    pedido = abrir(db, salon)
    anular_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    abrir(db, salon, mesero="beto")


def test_solo_atiende_personal_de_salon_del_mismo_cliente(db, salon, otro_local, nuevo_usuario):
    ajena, _ = otro_local
    ajeno = nuevo_usuario(ajena, "Mesero ajeno")
    with pytest.raises(ErrorNegocio, match="no es mesero"):
        abrir(db, salon, mesero="cocinero")
    with pytest.raises(ErrorNegocio, match="no existe"):
        abrir_pedido(db, empresa_id=salon["empresa"].id, sucursal_id=salon["sucursal"].id,
                     mesa_id=salon["m1"].id, mesero_id=ajeno.id)


def test_pedido_con_uuid_generado_en_la_tablet_sin_conexion(db, salon):
    pedido = abrir(db, salon, pedido_id="11111111-2222-3333-4444-555555555555")
    assert pedido.id == "11111111-2222-3333-4444-555555555555"
    with pytest.raises(ErrorNegocio, match="ya existe"):
        abrir(db, salon, mesa="m2", pedido_id="11111111-2222-3333-4444-555555555555")


def test_no_se_abre_una_mesa_de_otro_cliente(db, salon, otro_local):
    ajena, sucursal_ajena = otro_local
    mesa_ajena = crear_mesa(db, empresa_id=ajena.id, sucursal_id=sucursal_ajena.id, nombre="Mesa X")
    with pytest.raises(ErrorNegocio, match="no existe"):
        abrir_pedido(db, empresa_id=salon["empresa"].id, sucursal_id=salon["sucursal"].id,
                     mesa_id=mesa_ajena.id, mesero_id=salon["ana"].id)


# ── Tomar ────────────────────────────────────────────────────
def test_tomar_un_plato_lo_deja_en_cola_sin_reservar(db, salon):
    pedido = abrir(db, salon)
    r = tomar(db, salon, pedido, cantidad=2, comensal=1)
    assert r.linea.estado == EstadoLinea.tomada
    assert r.disponibilidad.alcanza
    assert reservado(db, salon, "carne") == Decimal("0")
    assert db.query(ReservaStock).count() == 0


def test_el_total_cobra_extras_aparte_y_quitar_no_baja_el_precio(db, salon):
    pedido = abrir(db, salon)
    sin_cebolla = tomar(db, salon, pedido, sin_ingredientes=[salon["cebolla"].id]).linea
    con_extra = tomar(db, salon, pedido, cantidad=2, extra_ids=[salon["extra"].id]).linea
    assert sin_cebolla.total == Decimal("6500")                  # sin cebolla: mismo precio
    assert con_extra.total == Decimal("15000")                   # (6.500 + 1.000) × 2
    assert [q.ingrediente_id for q in sin_cebolla.quitados] == [salon["cebolla"].id]


def test_el_precio_queda_copiado_aunque_la_carta_suba_despues(db, salon):
    pedido = abrir(db, salon)
    linea = tomar(db, salon, pedido).linea
    salon["burger"].precio_venta = Decimal("9900")
    db.commit()
    assert linea.precio_unitario == Decimal("6500")


def test_la_bebida_se_enruta_a_la_barra_y_el_plato_a_la_cocina(db, salon):
    pedido = abrir(db, salon)
    assert tomar(db, salon, pedido, item="cola").linea.estacion == "barra"
    assert tomar(db, salon, pedido, item="burger").linea.estacion == "cocina"


def test_si_falta_stock_avisa_al_mesero_pero_no_bloquea(db, salon):
    pedido = abrir(db, salon)
    r = tomar(db, salon, pedido, cantidad=60)                    # pan: 50
    assert not r.disponibilidad.alcanza
    assert {f.nombre for f in r.disponibilidad.faltas} >= {"Pan"}
    assert r.linea.estado == EstadoLinea.tomada


def test_reglas_al_tomar(db, salon):
    pedido = abrir(db, salon)
    with pytest.raises(ErrorNegocio, match="entero mayor que cero"):
        tomar(db, salon, pedido, cantidad=0)
    with pytest.raises(ErrorNegocio, match="no está a la venta"):
        tomar(db, salon, pedido, item="carne")
    with pytest.raises(ErrorNegocio, match="no son removibles"):
        tomar(db, salon, pedido, sin_ingredientes=[salon["carne"].id])
    with pytest.raises(ErrorNegocio, match="no se ofrece"):
        tomar(db, salon, pedido, item="cola", extra_ids=[salon["extra"].id])
    salon["burger"].precio_venta = None
    with pytest.raises(ErrorNegocio, match="no tiene precio"):
        tomar(db, salon, pedido)
    assert db.query(ReservaStock).count() == 0 and len(pedido.lineas) == 0


def test_plato_desactivado_no_se_puede_tomar(db, salon):
    pedido = abrir(db, salon)
    salon["cola"].activo = False
    with pytest.raises(ErrorNegocio, match="no está a la venta"):
        tomar(db, salon, pedido, item="cola")


def test_linea_con_uuid_de_la_tablet_y_sincronizacion_doble(db, salon):
    pedido = abrir(db, salon)
    tomar(db, salon, pedido, linea_id="aaaaaaaa-0000-0000-0000-000000000001")
    with pytest.raises(ErrorNegocio, match="ya existe"):
        tomar(db, salon, pedido, linea_id="aaaaaaaa-0000-0000-0000-000000000001")


def test_quitar_un_plato_de_la_libreta_pero_no_uno_enviado(db, salon):
    pedido = abrir(db, salon)
    borrable = tomar(db, salon, pedido).linea
    quitar_linea_tomada(db, empresa_id=salon["empresa"].id, linea_id=borrable.id)
    db.refresh(pedido)
    assert pedido.lineas == []
    enviado = tomar(db, salon, pedido).linea
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    with pytest.raises(ErrorNegocio, match="ya se envió"):
        quitar_linea_tomada(db, empresa_id=salon["empresa"].id, linea_id=enviado.id)


# ── Enviar ───────────────────────────────────────────────────
def test_enviar_manda_todo_lo_tomado_y_aparta_los_ingredientes(db, salon):
    pedido = abrir(db, salon)
    tomar(db, salon, pedido, cantidad=2)
    tomar(db, salon, pedido, item="cola", cantidad=3)
    r = enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    assert {l.estado for l in r.lineas} == {EstadoLinea.enviada}
    assert all(l.enviada_en is not None for l in r.lineas)
    assert reservado(db, salon, "carne") == Decimal("300")
    assert reservado(db, salon, "cola") == Decimal("3")
    assert r.faltantes == []


def test_se_puede_enviar_varias_veces_con_la_mesa_abierta(db, salon):
    """Primero los pasapalos; después, cuando la familia está lista, el resto."""
    pedido = abrir(db, salon)
    entrada = tomar(db, salon, pedido, item="cola").linea
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    plato = tomar(db, salon, pedido).linea
    segundo = enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    assert segundo.lineas == [plato]                              # la primera no se reenvía
    assert entrada.estado == EstadoLinea.enviada and plato.estado == EstadoLinea.enviada


def test_enviar_sin_nada_tomado_falla(db, salon):
    pedido = abrir(db, salon)
    with pytest.raises(ErrorNegocio, match="No hay platos tomados"):
        enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)


def test_enviar_con_faltantes_no_bloquea_y_los_devuelve_para_el_admin(db, salon):
    pedido = abrir(db, salon)
    tomar(db, salon, pedido, cantidad=60)
    r = enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    assert r.lineas[0].estado == EstadoLinea.enviada
    assert "Pan" in {f.nombre for f in r.faltantes}


def test_enviar_respeta_los_quitados_y_los_extras(db, salon):
    pedido = abrir(db, salon)
    tomar(db, salon, pedido, sin_ingredientes=[salon["cebolla"].id], extra_ids=[salon["extra"].id])
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    assert reservado(db, salon, "cebolla") == Decimal("0")
    tocineta = db.query(ReservaStock).filter_by(cantidad=Decimal("25.000")).one()
    assert tocineta.item.nombre == "Tocineta"


# ── Cancelar ─────────────────────────────────────────────────
def test_cancelar_un_plato_solo_anotado(db, salon):
    pedido = abrir(db, salon)
    linea = tomar(db, salon, pedido).linea
    cancelar_linea(db, empresa_id=salon["empresa"].id, linea_id=linea.id)
    assert linea.estado == EstadoLinea.cancelada and linea.cancelada_en is not None


def test_cancelar_un_plato_nuevo_vuelve_a_cocina_y_libera_la_reserva(db, salon):
    pedido = abrir(db, salon)
    linea = tomar(db, salon, pedido).linea
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    cancelar_linea(db, empresa_id=salon["empresa"].id, linea_id=linea.id)
    assert linea.estado == EstadoLinea.cancelada
    assert reservado(db, salon, "carne") == Decimal("0")
    assert obtener_stock(db, salon["empresa"].id, salon["carne"].id, salon["sucursal"].id).cantidad_fisica == Decimal("3000")
    assert {r.estado for r in db.query(ReservaStock)} == {EstadoReserva.liberada}


def test_cancelar_un_plato_en_preparacion_pasa_a_merma(db, salon):
    pedido = abrir(db, salon)
    linea = tomar(db, salon, pedido).linea
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    linea.estado = EstadoLinea.en_preparacion                    # (cocina lo toma; esa pantalla viene después)
    cancelar_linea(db, empresa_id=salon["empresa"].id, linea_id=linea.id, usuario_id=salon["ana"].id)
    assert obtener_stock(db, salon["empresa"].id, salon["carne"].id, salon["sucursal"].id).cantidad_fisica == Decimal("2850")
    mermas = db.query(MovimientoStock).filter_by(tipo=TipoMovimientoStock.merma).all()
    assert len(mermas) == 3 and {m.motivo_merma for m in mermas} == {MotivoMerma.cancelacion_en_preparacion}


def test_un_plato_ya_listo_no_se_cancela(db, salon):
    pedido = abrir(db, salon)
    linea = tomar(db, salon, pedido).linea
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    linea.estado = EstadoLinea.lista
    with pytest.raises(ErrorNegocio, match="ya salió de cocina"):
        cancelar_linea(db, empresa_id=salon["empresa"].id, linea_id=linea.id)


# ── Cuenta, traspaso, anulación ──────────────────────────────
def test_pedir_la_cuenta_cierra_la_mesa_a_nuevos_platos(db, salon):
    pedido = abrir(db, salon)
    tomar(db, salon, pedido)
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    pedir_cuenta(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    assert pedido.estado == EstadoPedido.cuenta_pedida and pedido.cuenta_pedida_en is not None
    with pytest.raises(ErrorNegocio, match="ya no admite"):
        tomar(db, salon, pedido)
    with pytest.raises(ErrorNegocio, match="ya no admite"):
        enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)


def test_no_se_pide_la_cuenta_con_platos_sin_enviar_ni_sin_platos(db, salon):
    pedido = abrir(db, salon)
    with pytest.raises(ErrorNegocio, match="no tiene platos que cobrar"):
        pedir_cuenta(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    tomar(db, salon, pedido)
    with pytest.raises(ErrorNegocio, match="sin enviar"):
        pedir_cuenta(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)


def test_cancelar_un_plato_aun_se_puede_despues_de_pedir_la_cuenta(db, salon):
    pedido = abrir(db, salon)
    linea = tomar(db, salon, pedido).linea
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    pedir_cuenta(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    cancelar_linea(db, empresa_id=salon["empresa"].id, linea_id=linea.id)
    assert linea.estado == EstadoLinea.cancelada


def test_traspasar_la_mesa_a_otro_mesero_deja_registro(db, salon):
    pedido = abrir(db, salon)
    traspasar_mesero(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id, nuevo_mesero_id=salon["beto"].id)
    assert pedido.mesero_id == salon["beto"].id
    assert [(t.de_usuario_id, t.a_usuario_id) for t in pedido.traspasos] == [(salon["ana"].id, salon["beto"].id)]


def test_reglas_del_traspaso(db, salon):
    pedido = abrir(db, salon)
    with pytest.raises(ErrorNegocio, match="ya la atiende"):
        traspasar_mesero(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id, nuevo_mesero_id=salon["ana"].id)
    with pytest.raises(ErrorNegocio, match="no es mesero"):
        traspasar_mesero(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id,
                         nuevo_mesero_id=salon["cocinero"].id)


def test_anular_solo_si_nadie_consumio(db, salon):
    vacio = abrir(db, salon)
    anular_pedido(db, empresa_id=salon["empresa"].id, pedido_id=vacio.id)
    assert vacio.estado == EstadoPedido.anulado

    enviado = abrir(db, salon, mesa="m2")
    tomar(db, salon, enviado)
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=enviado.id)
    with pytest.raises(ErrorNegocio, match="platos enviados"):
        anular_pedido(db, empresa_id=salon["empresa"].id, pedido_id=enviado.id)


def test_un_cliente_no_ve_pedidos_ni_platos_de_otro(db, salon, otro_local):
    ajena, _ = otro_local
    pedido = abrir(db, salon)
    linea = tomar(db, salon, pedido).linea
    with pytest.raises(ErrorNegocio, match="no existe"):
        enviar_pedido(db, empresa_id=ajena.id, pedido_id=pedido.id)
    with pytest.raises(ErrorNegocio, match="no existe"):
        cancelar_linea(db, empresa_id=ajena.id, linea_id=linea.id)


# ── Plano ────────────────────────────────────────────────────
def test_el_plano_refleja_el_estado_de_cada_mesa(db, salon):
    def luces():
        return {m.nombre: m.estado for m in estado_mesas(
            db, empresa_id=salon["empresa"].id, sucursal_id=salon["sucursal"].id)}

    assert luces() == {"Mesa 1": "libre", "Mesa 2": "libre"}
    pedido = abrir(db, salon)
    assert luces()["Mesa 1"] == "ocupada"
    linea = tomar(db, salon, pedido).linea
    enviar_pedido(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    pedir_cuenta(db, empresa_id=salon["empresa"].id, pedido_id=pedido.id)
    assert luces()["Mesa 1"] == "cuenta_pedida"
    linea.estado = EstadoLinea.lista                              # cocina marcó listo
    plano = {m.nombre: m for m in estado_mesas(db, empresa_id=salon["empresa"].id,
                                               sucursal_id=salon["sucursal"].id)}
    assert plano["Mesa 1"].estado == "lista" and plano["Mesa 1"].lineas_listas == 1
    assert plano["Mesa 1"].mesero_id == salon["ana"].id
