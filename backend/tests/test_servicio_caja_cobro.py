# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_caja_cobro.py
# Pruebas de caja, turnos, cuenta, propina, descuento y pagos.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from decimal import Decimal

import pytest

from errores import ErrorNegocio
from models import (EstacionCocina, EstadoPedido, MedioPago, ModoPropina, RolUsuario)
from servicios.caja import (abrir_turno, arqueo_turno, cerrar_turno, crear_caja, crear_terminal,
                            revisar_turno)
from servicios.cobro import (anotar_propina, aplicar_descuento, calcular_cuenta, configurar_cobro,
                             registrar_pago)
from servicios.cocina import marcar_entregada, marcar_lista
from servicios.mesas import estado_mesas
from servicios.pedidos import (abrir_pedido, cancelar_linea, enviar_pedido, pedir_cuenta,
                               tomar_linea)

D = Decimal


@pytest.fixture()
def cobro(db, salon, nuevo_usuario):
    """Salón + cajera (tope de descuento 10%), administrador, chef, una caja y un terminal."""
    s = salon
    e, suc = s["empresa"], s["sucursal"]
    s["cata"] = nuevo_usuario(e, "Cata", roles=(RolUsuario.cajero,), descuento_max_pct=D("10"))
    s["otra_cajera"] = nuevo_usuario(e, "Dani", roles=(RolUsuario.cajero,))
    s["admin"] = nuevo_usuario(e, "Admin", roles=(RolUsuario.administrador,))
    s["chef"] = nuevo_usuario(e, "Chef", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.cocina)
    s["barman"] = nuevo_usuario(e, "Barman", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.barra)
    s["caja"] = crear_caja(db, empresa_id=e.id, sucursal_id=suc.id, nombre="Caja 1")
    s["caja2"] = crear_caja(db, empresa_id=e.id, sucursal_id=suc.id, nombre="Caja 2")
    s["terminal"] = crear_terminal(db, empresa_id=e.id, sucursal_id=suc.id, nombre="Terminal 1")
    db.commit()
    return s


def cuenta_pedida(db, s, mesa="m1", entregar=True):
    """Mesa con una hamburguesa + extra tocineta ($7.500) y una cola ($1.500) = $9.000, con la cuenta pedida."""
    e = s["empresa"].id
    pedido = abrir_pedido(db, empresa_id=e, sucursal_id=s["sucursal"].id, mesa_id=s[mesa].id, mesero_id=s["ana"].id)
    plato = tomar_linea(db, empresa_id=e, pedido_id=pedido.id, item_id=s["burger"].id,
                        extra_ids=[s["extra"].id], sin_ingredientes=[s["cebolla"].id]).linea
    trago = tomar_linea(db, empresa_id=e, pedido_id=pedido.id, item_id=s["cola"].id).linea
    enviar_pedido(db, empresa_id=e, pedido_id=pedido.id)
    marcar_lista(db, empresa_id=e, linea_id=plato.id, usuario_id=s["chef"].id)
    marcar_lista(db, empresa_id=e, linea_id=trago.id, usuario_id=s["barman"].id)
    if entregar:
        marcar_entregada(db, empresa_id=e, linea_id=plato.id)
        marcar_entregada(db, empresa_id=e, linea_id=trago.id)
    pedir_cuenta(db, empresa_id=e, pedido_id=pedido.id)
    return pedido


def pagar(db, s, pedido, quien="cata", medio=MedioPago.efectivo, monto=None, **datos):
    monto = calcular_cuenta(db, empresa_id=s["empresa"].id, pedido_id=pedido.id).pendiente if monto is None else monto
    return registrar_pago(db, empresa_id=s["empresa"].id, pedido_id=pedido.id, usuario_id=s[quien].id,
                          medio=medio, monto=monto, **datos)


# ── Cajas, terminales y turnos ───────────────────────────────
def test_reglas_al_crear_cajas_y_terminales(db, cobro):
    e, suc = cobro["empresa"].id, cobro["sucursal"].id
    with pytest.raises(ErrorNegocio, match="Ya existe una caja"):
        crear_caja(db, empresa_id=e, sucursal_id=suc, nombre=" Caja 1 ")
    with pytest.raises(ErrorNegocio, match="necesita un nombre"):
        crear_caja(db, empresa_id=e, sucursal_id=suc, nombre="")
    with pytest.raises(ErrorNegocio, match="Ya existe un terminal"):
        crear_terminal(db, empresa_id=e, sucursal_id=suc, nombre="Terminal 1")


def test_abrir_turno_con_fondo(db, cobro):
    s = cobro
    turno = abrir_turno(db, empresa_id=s["empresa"].id, caja_id=s["caja"].id, usuario_id=s["cata"].id, fondo=20000)
    assert (turno.fondo, turno.estado.value, turno.usuario_id) == (D("20000.00"), "abierto", s["cata"].id)


def test_reglas_al_abrir_turno(db, cobro):
    s = cobro
    e = s["empresa"].id
    abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id, fondo=0)
    with pytest.raises(ErrorNegocio, match="ya tiene un turno abierto"):
        abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["otra_cajera"].id)       # caja ocupada
    with pytest.raises(ErrorNegocio, match="ya tiene un turno abierto"):
        abrir_turno(db, empresa_id=e, caja_id=s["caja2"].id, usuario_id=s["cata"].id)             # cajera ocupada
    with pytest.raises(ErrorNegocio, match="no es cajero"):
        abrir_turno(db, empresa_id=e, caja_id=s["caja2"].id, usuario_id=s["ana"].id)
    with pytest.raises(ErrorNegocio, match="no puede ser negativo"):
        abrir_turno(db, empresa_id=e, caja_id=s["caja2"].id, usuario_id=s["otra_cajera"].id, fondo=-1)


def test_la_caja_de_otro_cliente_no_existe(db, cobro, otro_local, nuevo_usuario):
    ajena, sucursal_ajena = otro_local
    caja_ajena = crear_caja(db, empresa_id=ajena.id, sucursal_id=sucursal_ajena.id, nombre="Caja X")
    with pytest.raises(ErrorNegocio, match="no existe"):
        abrir_turno(db, empresa_id=cobro["empresa"].id, caja_id=caja_ajena.id, usuario_id=cobro["cata"].id)


def test_cierre_de_turno_cuadrado_solo_cuenta_el_efectivo(db, cobro):
    s = cobro
    e = s["empresa"].id
    turno = abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id, fondo=20000)
    pedido = cuenta_pedida(db, s)
    pagar(db, s, pedido, monto=5000, recibido=10000)                                   # efectivo (con vuelto)
    pagar(db, s, pedido, medio=MedioPago.tarjeta, terminal_id=s["terminal"].id, numero_operacion="A1")  # resto
    arqueo = arqueo_turno(db, empresa_id=e, turno_id=turno.id)
    assert (arqueo.fondo, arqueo.efectivo_cobrado, arqueo.esperado, arqueo.cantidad_pagos) == \
        (D("20000.00"), D("5000.00"), D("25000.00"), 1)
    cerrado = cerrar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["cata"].id, contado=25000)
    assert (cerrado.estado.value, cerrado.diferencia, cerrado.esperado) == ("cerrado", D("0.00"), D("25000.00"))
    assert cerrado.cerrado_en is not None and cerrado.nota is None


def test_diferencia_en_el_cierre_exige_nota(db, cobro):
    s = cobro
    e = s["empresa"].id
    turno = abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id, fondo=20000)
    with pytest.raises(ErrorNegocio, match="escribe una nota"):
        cerrar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["cata"].id, contado=19000)
    cerrado = cerrar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["cata"].id, contado=19000,
                           nota="Se dio mal un vuelto")
    assert cerrado.diferencia == D("-1000.00") and cerrado.nota == "Se dio mal un vuelto"


def test_quien_cierra_y_cierre_doble(db, cobro):
    s = cobro
    e = s["empresa"].id
    turno = abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    with pytest.raises(ErrorNegocio, match="Solo el cajero del turno"):
        cerrar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["otra_cajera"].id, contado=0)
    cerrar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["admin"].id, contado=0)     # el admin sí
    with pytest.raises(ErrorNegocio, match="ya está cerrado"):
        cerrar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["admin"].id, contado=0)


def test_el_admin_revisa_el_cuadre_de_un_turno_cerrado(db, cobro):
    s = cobro
    e = s["empresa"].id
    turno = abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    with pytest.raises(ErrorNegocio, match="sigue abierto"):
        revisar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["admin"].id)
    cerrar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["cata"].id, contado=0)
    with pytest.raises(ErrorNegocio, match="Solo un administrador"):
        revisar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["cata"].id)
    revisar_turno(db, empresa_id=e, turno_id=turno.id, usuario_id=s["admin"].id)
    assert turno.revisado_por_id == s["admin"].id and turno.revisado_en is not None


# ── La cuenta ────────────────────────────────────────────────
def test_la_cuenta_suma_extras_y_quitar_ingredientes_no_baja_el_precio(db, cobro):
    pedido = cuenta_pedida(db, cobro)
    c = calcular_cuenta(db, empresa_id=cobro["empresa"].id, pedido_id=pedido.id)
    assert (c.subtotal, c.descuento, c.propina, c.total, c.pendiente) == \
        (D("9000.00"), D("0"), D("0"), D("9000.00"), D("9000.00"))


def test_un_plato_cancelado_no_se_cobra(db, cobro):
    s = cobro
    e = s["empresa"].id
    pedido = abrir_pedido(db, empresa_id=e, sucursal_id=s["sucursal"].id, mesa_id=s["m1"].id, mesero_id=s["ana"].id)
    a = tomar_linea(db, empresa_id=e, pedido_id=pedido.id, item_id=s["cola"].id).linea
    b = tomar_linea(db, empresa_id=e, pedido_id=pedido.id, item_id=s["cola"].id).linea
    enviar_pedido(db, empresa_id=e, pedido_id=pedido.id)
    cancelar_linea(db, empresa_id=e, linea_id=a.id)
    pedir_cuenta(db, empresa_id=e, pedido_id=pedido.id)
    assert calcular_cuenta(db, empresa_id=e, pedido_id=pedido.id).subtotal == D("1500.00")


def test_propina_sugerida_y_manual(db, cobro):
    s = cobro
    e = s["empresa"].id
    pedido = cuenta_pedida(db, s)
    anotar_propina(db, empresa_id=e, pedido_id=pedido.id)                       # 10% de 9.000
    assert pedido.propina == D("900.00")
    configurar_cobro(db, empresa_id=e, propina_sugerida_pct=15)
    anotar_propina(db, empresa_id=e, pedido_id=pedido.id)
    assert pedido.propina == D("1350.00")
    anotar_propina(db, empresa_id=e, pedido_id=pedido.id, monto=2000)
    assert calcular_cuenta(db, empresa_id=e, pedido_id=pedido.id).total == D("11000.00")
    anotar_propina(db, empresa_id=e, pedido_id=pedido.id, monto=0)              # el cliente no deja propina
    assert pedido.propina == D("0.00")


def test_reglas_de_la_propina(db, cobro):
    s = cobro
    e = s["empresa"].id
    abierta = abrir_pedido(db, empresa_id=e, sucursal_id=s["sucursal"].id, mesa_id=s["m2"].id, mesero_id=s["ana"].id)
    with pytest.raises(ErrorNegocio, match="pedir la cuenta"):
        anotar_propina(db, empresa_id=e, pedido_id=abierta.id)
    pedido = cuenta_pedida(db, s)
    with pytest.raises(ErrorNegocio, match="no puede ser negativa"):
        anotar_propina(db, empresa_id=e, pedido_id=pedido.id, monto=-5)


def test_configuracion_de_cobro_por_restaurante(db, cobro, otro_local):
    s = cobro
    ajena, _ = otro_local
    configurar_cobro(db, empresa_id=s["empresa"].id, propina_modo=ModoPropina.grupal, propina_sugerida_pct=12)
    otra = configurar_cobro(db, empresa_id=ajena.id)
    assert (otra.propina_modo, otra.propina_sugerida_pct) == (ModoPropina.por_mesa, D("10"))
    with pytest.raises(ErrorNegocio, match="entre 0 y 100"):
        configurar_cobro(db, empresa_id=s["empresa"].id, propina_sugerida_pct=120)


# ── Descuento ────────────────────────────────────────────────
def test_descuento_hasta_el_tope_de_la_cajera_y_la_propina_va_sobre_lo_descontado(db, cobro):
    s = cobro
    e = s["empresa"].id
    pedido = cuenta_pedida(db, s)
    aplicar_descuento(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["cata"].id, porcentaje=10)
    assert pedido.descuento == D("900.00") and pedido.descuento_por_id == s["cata"].id
    anotar_propina(db, empresa_id=e, pedido_id=pedido.id)                      # 10% de 8.100
    c = calcular_cuenta(db, empresa_id=e, pedido_id=pedido.id)
    assert (c.propina, c.total) == (D("810.00"), D("8910.00"))


def test_descuento_sobre_el_tope_lo_autoriza_solo_el_admin(db, cobro):
    s = cobro
    e = s["empresa"].id
    pedido = cuenta_pedida(db, s)
    with pytest.raises(ErrorNegocio, match="excede el tope"):
        aplicar_descuento(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["cata"].id, porcentaje=15)
    aplicar_descuento(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["admin"].id, porcentaje=15)
    assert pedido.descuento == D("1350.00")


def test_reglas_del_descuento(db, cobro):
    s = cobro
    e = s["empresa"].id
    pedido = cuenta_pedida(db, s)
    with pytest.raises(ErrorNegocio, match="no puede dar descuentos"):
        aplicar_descuento(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["ana"].id, porcentaje=5)
    for malo in (-1, 100, 150):
        with pytest.raises(ErrorNegocio, match="entre 0 y menos de 100"):
            aplicar_descuento(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["admin"].id, porcentaje=malo)
    aplicar_descuento(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["cata"].id, porcentaje=5)
    aplicar_descuento(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["cata"].id, porcentaje=0)   # lo quita
    assert pedido.descuento == D("0.00") and pedido.descuento_por_id is None


# ── Pagos ────────────────────────────────────────────────────
def test_pago_en_efectivo_con_vuelto_cierra_la_mesa(db, cobro):
    s = cobro
    e = s["empresa"].id
    abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    pedido = cuenta_pedida(db, s)
    anotar_propina(db, empresa_id=e, pedido_id=pedido.id)                       # total 9.900
    pago = pagar(db, s, pedido, recibido=10000)
    assert (pago.monto, pago.recibido, pago.vuelto) == (D("9900.00"), D("10000.00"), D("100.00"))
    assert pago.turno_id is not None and pago.usuario_id == s["cata"].id
    assert pedido.estado == EstadoPedido.cerrado and pedido.cerrado_en is not None
    plano = {m.nombre: m.estado for m in estado_mesas(db, empresa_id=e, sucursal_id=s["sucursal"].id)}
    assert plano["Mesa 1"] == "libre"


def test_pago_mixto_en_partes_cierra_al_cubrir_el_total(db, cobro):
    s = cobro
    e = s["empresa"].id
    abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    pedido = cuenta_pedida(db, s)
    pagar(db, s, pedido, monto=4000)
    assert pedido.estado == EstadoPedido.cuenta_pedida
    assert calcular_cuenta(db, empresa_id=e, pedido_id=pedido.id).pendiente == D("5000.00")
    pagar(db, s, pedido, quien="ana", medio=MedioPago.tarjeta, terminal_id=s["terminal"].id, numero_operacion="T-77")
    assert pedido.estado == EstadoPedido.cerrado


def test_no_se_paga_mas_de_lo_pendiente_ni_con_la_cuenta_cerrada(db, cobro):
    s = cobro
    abrir_turno(db, empresa_id=s["empresa"].id, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    pedido = cuenta_pedida(db, s)
    with pytest.raises(ErrorNegocio, match="supera lo pendiente"):
        pagar(db, s, pedido, monto=9500)
    pagar(db, s, pedido)
    with pytest.raises(ErrorNegocio, match="ya está pagada y cerrada"):
        pagar(db, s, pedido, monto=100)


def test_el_efectivo_exige_cajero_con_turno_y_el_mesero_no_lo_maneja(db, cobro):
    s = cobro
    pedido = cuenta_pedida(db, s)
    with pytest.raises(ErrorNegocio, match="abrir turno de caja"):
        pagar(db, s, pedido)
    abrir_turno(db, empresa_id=s["empresa"].id, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    with pytest.raises(ErrorNegocio, match="el mesero no maneja efectivo"):
        pagar(db, s, pedido, quien="ana")
    with pytest.raises(ErrorNegocio, match="no alcanza"):
        pagar(db, s, pedido, recibido=5000)


def test_la_tarjeta_exige_terminal_y_numero_de_operacion_sin_repetir(db, cobro):
    s = cobro
    pedido = cuenta_pedida(db, s)
    with pytest.raises(ErrorNegocio, match="número de operación es obligatorio"):
        pagar(db, s, pedido, quien="ana", medio=MedioPago.tarjeta, monto=1000, terminal_id=s["terminal"].id)
    with pytest.raises(ErrorNegocio, match="terminal válido"):
        pagar(db, s, pedido, quien="ana", medio=MedioPago.tarjeta, monto=1000, numero_operacion="X1")
    with pytest.raises(ErrorNegocio, match="Solo el efectivo"):
        pagar(db, s, pedido, quien="ana", medio=MedioPago.tarjeta, monto=1000, numero_operacion="X1",
              terminal_id=s["terminal"].id, recibido=2000)
    pagar(db, s, pedido, quien="ana", medio=MedioPago.tarjeta, monto=1000, numero_operacion="X1",
          terminal_id=s["terminal"].id)
    with pytest.raises(ErrorNegocio, match="ya se registró en este terminal"):
        pagar(db, s, pedido, quien="ana", medio=MedioPago.tarjeta, monto=1000, numero_operacion="X1",
              terminal_id=s["terminal"].id)


def test_la_transferencia_exige_numero_de_operacion(db, cobro):
    s = cobro
    pedido = cuenta_pedida(db, s)
    with pytest.raises(ErrorNegocio, match="número de operación es obligatorio"):
        pagar(db, s, pedido, medio=MedioPago.transferencia)
    pagar(db, s, pedido, medio=MedioPago.transferencia, numero_operacion="TRF-1")
    assert pedido.estado == EstadoPedido.cerrado


def test_el_terminal_de_otro_local_o_desactivado_no_sirve(db, cobro, otro_local):
    s = cobro
    ajena, sucursal_ajena = otro_local
    terminal_ajeno = crear_terminal(db, empresa_id=ajena.id, sucursal_id=sucursal_ajena.id, nombre="T ajeno")
    pedido = cuenta_pedida(db, s)
    with pytest.raises(ErrorNegocio, match="terminal válido"):
        pagar(db, s, pedido, quien="ana", medio=MedioPago.tarjeta, monto=1000, numero_operacion="Z",
              terminal_id=terminal_ajeno.id)
    s["terminal"].activo = False
    with pytest.raises(ErrorNegocio, match="terminal válido"):
        pagar(db, s, pedido, quien="ana", medio=MedioPago.tarjeta, monto=1000, numero_operacion="Z",
              terminal_id=s["terminal"].id)


def test_no_se_cobra_con_platos_que_cocina_aun_no_termina(db, cobro):
    s = cobro
    e = s["empresa"].id
    abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    pedido = abrir_pedido(db, empresa_id=e, sucursal_id=s["sucursal"].id, mesa_id=s["m1"].id, mesero_id=s["ana"].id)
    tomar_linea(db, empresa_id=e, pedido_id=pedido.id, item_id=s["burger"].id)
    enviar_pedido(db, empresa_id=e, pedido_id=pedido.id)
    pedir_cuenta(db, empresa_id=e, pedido_id=pedido.id)
    with pytest.raises(ErrorNegocio, match="cocina aún no termina"):
        pagar(db, s, pedido)


def test_un_plato_listo_sin_marcar_entregado_no_bloquea_el_cobro(db, cobro):
    s = cobro
    abrir_turno(db, empresa_id=s["empresa"].id, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    pedido = cuenta_pedida(db, s, entregar=False)
    pagar(db, s, pedido)
    assert pedido.estado == EstadoPedido.cerrado


def test_no_se_cobra_antes_de_pedir_la_cuenta(db, cobro):
    s = cobro
    e = s["empresa"].id
    abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    pedido = abrir_pedido(db, empresa_id=e, sucursal_id=s["sucursal"].id, mesa_id=s["m1"].id, mesero_id=s["ana"].id)
    with pytest.raises(ErrorNegocio, match="pedir la cuenta"):
        registrar_pago(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["cata"].id,
                       medio=MedioPago.efectivo, monto=100)


def test_pago_con_uuid_de_la_tablet_y_sincronizacion_doble(db, cobro):
    s = cobro
    abrir_turno(db, empresa_id=s["empresa"].id, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    pedido = cuenta_pedida(db, s)
    pagar(db, s, pedido, monto=1000, pago_id="bbbbbbbb-0000-0000-0000-000000000001")
    with pytest.raises(ErrorNegocio, match="ya existe"):
        pagar(db, s, pedido, monto=1000, pago_id="bbbbbbbb-0000-0000-0000-000000000001")


def test_con_pagos_hechos_ya_no_cambian_propina_ni_descuento(db, cobro):
    s = cobro
    e = s["empresa"].id
    abrir_turno(db, empresa_id=e, caja_id=s["caja"].id, usuario_id=s["cata"].id)
    pedido = cuenta_pedida(db, s)
    pagar(db, s, pedido, monto=1000)
    with pytest.raises(ErrorNegocio, match="ya tiene pagos"):
        anotar_propina(db, empresa_id=e, pedido_id=pedido.id)
    with pytest.raises(ErrorNegocio, match="ya tiene pagos"):
        aplicar_descuento(db, empresa_id=e, pedido_id=pedido.id, usuario_id=s["admin"].id, porcentaje=5)


def test_un_cliente_no_cobra_cuentas_de_otro(db, cobro, otro_local, nuevo_usuario):
    s = cobro
    ajena, _ = otro_local
    cajera_ajena = nuevo_usuario(ajena, "Cajera ajena", roles=(RolUsuario.cajero,))
    pedido = cuenta_pedida(db, s)
    with pytest.raises(ErrorNegocio, match="no existe"):
        registrar_pago(db, empresa_id=ajena.id, pedido_id=pedido.id, usuario_id=cajera_ajena.id,
                       medio=MedioPago.efectivo, monto=100)
