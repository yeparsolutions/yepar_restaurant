# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_propinas_cierre.py
# Pruebas del libro de propinas, el cuadre por terminal y el resumen.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from errores import ErrorNegocio
from models import EstadoPropina, MedioPago, ModoPropina
from servicios.caja import abrir_turno, cerrar_turno
from servicios.cierre import cuadre_terminal, resumen_periodo
from servicios.cobro import anotar_propina, configurar_cobro, registrar_pago
from servicios.cocina import marcar_lista
from servicios.pedidos import (abrir_pedido, enviar_pedido, pedir_cuenta, tomar_linea,
                               traspasar_mesero)
from servicios.propinas import (entregar_propinas, libro_propinas, repartir_fondo_grupal,
                                saldos_por_entregar)

D = Decimal


def cuenta_pedida(db, s, mesa="m1", mesero="ana"):
    """Mesa con una hamburguesa ($6.500) y una cola ($1.500) = $8.000 con la cuenta pedida."""
    e = s["empresa"].id
    pedido = abrir_pedido(db, empresa_id=e, sucursal_id=s["sucursal"].id, mesa_id=s[mesa].id, mesero_id=s[mesero].id)
    plato = tomar_linea(db, empresa_id=e, pedido_id=pedido.id, item_id=s["burger"].id).linea
    trago = tomar_linea(db, empresa_id=e, pedido_id=pedido.id, item_id=s["cola"].id).linea
    enviar_pedido(db, empresa_id=e, pedido_id=pedido.id)
    marcar_lista(db, empresa_id=e, linea_id=plato.id, usuario_id=s["chef"].id)
    marcar_lista(db, empresa_id=e, linea_id=trago.id, usuario_id=s["barman"].id)
    pedir_cuenta(db, empresa_id=e, pedido_id=pedido.id)
    return pedido


def cobrar(db, s, pedido, propina=None, medio=MedioPago.efectivo, quien="cata", **datos):
    """Anota la propina (None = sugerida; 0 = sin propina) y paga todo lo pendiente."""
    e = s["empresa"].id
    anotar_propina(db, empresa_id=e, pedido_id=pedido.id, monto=propina)
    total = pedido.propina + D("8000.00")
    return registrar_pago(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s[quien].id, medio=medio,
                          monto=total, **datos)


@pytest.fixture()
def turno(db, cobro):
    return abrir_turno(db, empresa_id=cobro["empresa"].id, caja_id=cobro["caja"].id, usuario_id=cobro["cata"].id)


def rango():
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    return ahora - timedelta(days=1), ahora + timedelta(days=1)


# ── Libro de propinas ────────────────────────────────────────
def test_modo_por_mesa_la_propina_queda_a_nombre_del_mesero(db, cobro, turno):
    s = cobro
    cobrar(db, s, cuenta_pedida(db, s))                                  # 10% de 8.000 = 800
    libro = libro_propinas(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id)
    assert [(p.mesero_id, p.monto, p.modo, p.estado) for p in libro] == \
        [(s["ana"].id, D("800.00"), ModoPropina.por_mesa, EstadoPropina.pendiente)]
    assert saldos_por_entregar(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id) == {s["ana"].id: D("800.00")}


def test_sin_propina_no_se_anota_nada_y_con_la_mesa_abierta_tampoco(db, cobro, turno):
    s = cobro
    cobrar(db, s, cuenta_pedida(db, s), propina=0)
    cuenta_pedida(db, s, mesa="m2")                                       # mesa sin cobrar todavía
    assert libro_propinas(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id) == []


def test_modo_grupal_la_propina_va_al_fondo_comun(db, cobro, turno):
    s = cobro
    configurar_cobro(db, empresa_id=s["empresa"].id, propina_modo=ModoPropina.grupal)
    cobrar(db, s, cuenta_pedida(db, s))
    assert saldos_por_entregar(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id) == {None: D("800.00")}


def test_si_se_traspaso_la_mesa_la_propina_es_del_mesero_actual(db, cobro, turno):
    s = cobro
    pedido = cuenta_pedida(db, s)
    traspasar_mesero(db, empresa_id=s["empresa"].id, pedido_id=pedido.id, nuevo_mesero_id=s["beto"].id)
    cobrar(db, s, pedido)
    assert list(saldos_por_entregar(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id)) == [s["beto"].id]


def test_pagar_en_partes_anota_la_propina_una_sola_vez(db, cobro, turno):
    s = cobro
    e = s["empresa"].id
    pedido = cuenta_pedida(db, s)
    anotar_propina(db, empresa_id=e, pedido_id=pedido.id)
    registrar_pago(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["cata"].id,
                   medio=MedioPago.efectivo, monto=5000)
    assert libro_propinas(db, empresa_id=e, sucursal_id=s["sucursal"].id) == []        # aún no se cierra la mesa
    registrar_pago(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["cata"].id,
                   medio=MedioPago.efectivo, monto=3800)
    assert len(libro_propinas(db, empresa_id=e, sucursal_id=s["sucursal"].id)) == 1


def test_entregar_las_propinas_pendientes_de_un_mesero(db, cobro, turno):
    s = cobro
    e, suc = s["empresa"].id, s["sucursal"].id
    cobrar(db, s, cuenta_pedida(db, s, mesa="m1"))
    cobrar(db, s, cuenta_pedida(db, s, mesa="m2"), propina=500)
    assert entregar_propinas(db, empresa_id=e, sucursal_id=suc, mesero_id=s["ana"].id, usuario_id=s["cata"].id) == D("1300.00")
    assert {p.estado for p in libro_propinas(db, empresa_id=e, sucursal_id=suc)} == {EstadoPropina.entregada}
    assert saldos_por_entregar(db, empresa_id=e, sucursal_id=suc) == {}
    with pytest.raises(ErrorNegocio, match="no tiene propinas pendientes"):
        entregar_propinas(db, empresa_id=e, sucursal_id=suc, mesero_id=s["ana"].id, usuario_id=s["cata"].id)


def test_solo_caja_o_admin_entrega_propinas_y_dentro_del_cliente(db, cobro, turno, otro_local, nuevo_usuario):
    s = cobro
    e, suc = s["empresa"].id, s["sucursal"].id
    cobrar(db, s, cuenta_pedida(db, s))
    with pytest.raises(ErrorNegocio, match="no puede entregar propinas"):
        entregar_propinas(db, empresa_id=e, sucursal_id=suc, mesero_id=s["ana"].id, usuario_id=s["beto"].id)
    ajena, _ = otro_local
    with pytest.raises(ErrorNegocio, match="no existe"):
        entregar_propinas(db, empresa_id=ajena.id, sucursal_id=suc, mesero_id=s["ana"].id, usuario_id=s["cata"].id)


def test_el_libro_se_puede_filtrar_por_mesero_y_estado(db, cobro, turno):
    s = cobro
    e, suc = s["empresa"].id, s["sucursal"].id
    cobrar(db, s, cuenta_pedida(db, s, mesa="m1", mesero="ana"))
    cobrar(db, s, cuenta_pedida(db, s, mesa="m2", mesero="beto"))
    assert len(libro_propinas(db, empresa_id=e, sucursal_id=suc, mesero_id=s["beto"].id)) == 1
    entregar_propinas(db, empresa_id=e, sucursal_id=suc, mesero_id=s["ana"].id, usuario_id=s["cata"].id)
    pendientes = libro_propinas(db, empresa_id=e, sucursal_id=suc, estado=EstadoPropina.pendiente)
    assert [p.mesero_id for p in pendientes] == [s["beto"].id]


# ── Fondo grupal ─────────────────────────────────────────────
def grupal_con_fondo(db, s):
    configurar_cobro(db, empresa_id=s["empresa"].id, propina_modo=ModoPropina.grupal)
    cobrar(db, s, cuenta_pedida(db, s, mesa="m1"), propina=1000)             # fondo de 1.000


def test_repartir_el_fondo_en_partes_iguales_con_el_sobrante_al_primero(db, cobro, turno):
    s = cobro
    e, suc = s["empresa"].id, s["sucursal"].id
    grupal_con_fondo(db, s)
    partes = repartir_fondo_grupal(db, empresa_id=e, sucursal_id=suc, usuario_id=s["admin"].id,
                                   participantes=[s["ana"].id, s["beto"].id, s["chef"].id])
    assert partes == {s["ana"].id: D("333.34"), s["beto"].id: D("333.33"), s["chef"].id: D("333.33")}
    assert sum(partes.values()) == D("1000.00")
    assert None not in saldos_por_entregar(db, empresa_id=e, sucursal_id=suc)          # el fondo quedó repartido
    assert saldos_por_entregar(db, empresa_id=e, sucursal_id=suc)[s["ana"].id] == D("333.34")
    # Y cada persona cobra su parte como cualquier propina pendiente.
    assert entregar_propinas(db, empresa_id=e, sucursal_id=suc, mesero_id=s["beto"].id,
                             usuario_id=s["cata"].id) == D("333.33")


def test_repartir_proporcional_por_pesos(db, cobro, turno):
    s = cobro
    grupal_con_fondo(db, s)
    partes = repartir_fondo_grupal(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id,
                                   usuario_id=s["admin"].id, participantes={s["ana"].id: 3, s["beto"].id: 1})
    assert partes == {s["ana"].id: D("750.00"), s["beto"].id: D("250.00")}


def test_reglas_del_reparto_grupal(db, cobro, turno):
    s = cobro
    e, suc = s["empresa"].id, s["sucursal"].id
    with pytest.raises(ErrorNegocio, match="No hay fondo grupal"):
        repartir_fondo_grupal(db, empresa_id=e, sucursal_id=suc, usuario_id=s["admin"].id, participantes=[s["ana"].id])
    grupal_con_fondo(db, s)
    with pytest.raises(ErrorNegocio, match="Solo un administrador"):
        repartir_fondo_grupal(db, empresa_id=e, sucursal_id=suc, usuario_id=s["cata"].id, participantes=[s["ana"].id])
    with pytest.raises(ErrorNegocio, match="entre quiénes"):
        repartir_fondo_grupal(db, empresa_id=e, sucursal_id=suc, usuario_id=s["admin"].id, participantes=[])
    with pytest.raises(ErrorNegocio, match="mayores que cero"):
        repartir_fondo_grupal(db, empresa_id=e, sucursal_id=suc, usuario_id=s["admin"].id,
                              participantes={s["ana"].id: 0})
    repartir_fondo_grupal(db, empresa_id=e, sucursal_id=suc, usuario_id=s["admin"].id, participantes=[s["ana"].id])
    with pytest.raises(ErrorNegocio, match="No hay fondo grupal"):                      # ya se repartió
        repartir_fondo_grupal(db, empresa_id=e, sucursal_id=suc, usuario_id=s["admin"].id, participantes=[s["ana"].id])


def test_no_se_reparte_a_personas_de_otro_cliente(db, cobro, turno, otro_local, nuevo_usuario):
    s = cobro
    ajena, _ = otro_local
    ajeno = nuevo_usuario(ajena, "Mesero ajeno")
    grupal_con_fondo(db, s)
    with pytest.raises(ErrorNegocio, match="no existe"):
        repartir_fondo_grupal(db, empresa_id=s["empresa"].id, sucursal_id=s["sucursal"].id,
                              usuario_id=s["admin"].id, participantes=[ajeno.id])


# ── Cuadre por terminal ──────────────────────────────────────
def test_cuadre_por_terminal_compara_con_el_comprobante(db, cobro):
    s = cobro
    e = s["empresa"].id
    cobrar(db, s, cuenta_pedida(db, s, mesa="m1"), propina=0, medio=MedioPago.tarjeta, quien="ana",
           terminal_id=s["terminal"].id, numero_operacion="OP-1")
    cobrar(db, s, cuenta_pedida(db, s, mesa="m2"), propina=500, medio=MedioPago.tarjeta, quien="beto",
           terminal_id=s["terminal"].id, numero_operacion="OP-2")
    desde, hasta = rango()
    ok = cuadre_terminal(db, empresa_id=e, terminal_id=s["terminal"].id, desde=desde, hasta=hasta, reportado=16500)
    assert (ok.cantidad, ok.total_registrado, ok.diferencia) == (2, D("16500.00"), D("0.00"))
    assert ok.operaciones == [("OP-1", D("8000.00")), ("OP-2", D("8500.00"))]
    falta = cuadre_terminal(db, empresa_id=e, terminal_id=s["terminal"].id, desde=desde, hasta=hasta, reportado=17000)
    assert falta.diferencia == D("500.00")                           # el terminal cobró 500 que no anotamos
    sin_comprobante = cuadre_terminal(db, empresa_id=e, terminal_id=s["terminal"].id, desde=desde, hasta=hasta)
    assert sin_comprobante.diferencia is None


def test_el_cuadre_respeta_el_rango_el_medio_y_el_cliente(db, cobro, turno, otro_local):
    s = cobro
    e = s["empresa"].id
    cobrar(db, s, cuenta_pedida(db, s), propina=0)                  # efectivo: no cuenta en el terminal
    ayer = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)
    vacio = cuadre_terminal(db, empresa_id=e, terminal_id=s["terminal"].id, desde=ayer - timedelta(days=1), hasta=ayer)
    assert (vacio.cantidad, vacio.total_registrado) == (0, D("0.00"))
    desde, hasta = rango()
    assert cuadre_terminal(db, empresa_id=e, terminal_id=s["terminal"].id, desde=desde, hasta=hasta).cantidad == 0
    ajena, _ = otro_local
    with pytest.raises(ErrorNegocio, match="no existe"):
        cuadre_terminal(db, empresa_id=ajena.id, terminal_id=s["terminal"].id, desde=desde, hasta=hasta)


# ── Resumen del período ──────────────────────────────────────
def test_resumen_del_dia(db, cobro, turno):
    s = cobro
    e, suc = s["empresa"].id, s["sucursal"].id
    cobrar(db, s, cuenta_pedida(db, s, mesa="m1"), propina=900)                                   # efectivo 8.900
    cobrar(db, s, cuenta_pedida(db, s, mesa="m2"), propina=0, medio=MedioPago.tarjeta, quien="ana",
           terminal_id=s["terminal"].id, numero_operacion="OP-9")                                 # tarjeta 8.000
    cuenta_pedida(db, s, mesa="m1")                                                              # abierta: no cuenta
    cerrar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["cata"].id, contado=8800, nota="faltaron 100")
    desde, hasta = rango()
    r = resumen_periodo(db, empresa_id=e, sucursal_id=suc, desde=desde, hasta=hasta)
    assert (r.cerradas, r.ventas, r.descuentos, r.propinas, r.total_cobrado) == \
        (2, D("16000.00"), D("0"), D("900.00"), D("16900.00"))
    assert r.por_medio == {"efectivo": D("8900.00"), "tarjeta": D("8000.00")}
    assert r.turnos_con_diferencia == [(turno.id, D("-100.00"))]


def test_resumen_vacio_y_acotado_al_cliente(db, cobro, otro_local):
    s = cobro
    ajena, sucursal_ajena = otro_local
    desde, hasta = rango()
    r = resumen_periodo(db, empresa_id=ajena.id, sucursal_id=sucursal_ajena.id, desde=desde, hasta=hasta)
    assert (r.cerradas, r.total_cobrado, r.por_medio) == (0, D("0"), {})
    with pytest.raises(ErrorNegocio, match="no existe"):
        resumen_periodo(db, empresa_id=ajena.id, sucursal_id=s["sucursal"].id, desde=desde, hasta=hasta)
