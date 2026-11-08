# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_devoluciones.py
# Devoluciones de dinero (reembolsos): reglas, PIN de supervisor, arqueo del cajón y resumen del período.
# ============================================================

from datetime import datetime, timedelta, timezone

import pytest

from models import Devolucion
from tests.test_api_caja import abrir_turno, api, mesa_con_cuenta  # noqa: F401
from tests.test_api_supervisor import CLAVE, con_pin  # noqa: F401


def _rango():
    ahora = datetime.now(timezone.utc)
    f = lambda d: d.isoformat().replace("+", "%2B")
    return f"?desde={f(ahora - timedelta(hours=1))}&hasta={f(ahora + timedelta(hours=1))}"


def cuenta_cobrada_en_efectivo(api, platos=2):
    """Cuenta cerrada: $6.500 por plato, pagada en efectivo por la cajera."""
    pedido = mesa_con_cuenta(api, platos=platos)
    total = f"{6500 * platos}"
    r = api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "efectivo", "monto": total})
    assert r.status_code == 201 and r.json()["pedido_estado"] == "cerrado", r.text
    return pedido


def devolver(api, pedido, monto, medio="efectivo", persona="cata", **extra):
    cuerpo = {"medio": medio, "monto": monto, "motivo": "Plato frío"}
    cuerpo.update(extra)
    return api.post(persona, f"/pedidos/{pedido['id']}/devoluciones", cuerpo)


def test_devolver_efectivo_baja_el_arqueo_y_exige_pin(con_pin):
    api = con_pin
    turno = abrir_turno(api)                                       # fondo 20.000
    pedido = cuenta_cobrada_en_efectivo(api)                       # +13.000
    sup = {"supervisor_id": api.s["admin"].id}

    sin_pin = devolver(api, pedido, "3000")
    assert sin_pin.status_code == 422 and "PIN de un supervisor" in sin_pin.json()["detalle"]
    malo = devolver(api, pedido, "3000", pin_supervisor="1111", **sup)
    assert malo.status_code == 422 and "PIN incorrecto" in malo.json()["detalle"]

    r = devolver(api, pedido, "3000", pin_supervisor="4821", **sup)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["monto"] == "3000.00" and d["turno_id"] == turno["id"] and d["autorizado_por_id"] == api.s["admin"].id
    arqueo = api.get("cata", f"/turnos/{turno['id']}/arqueo").json()
    assert arqueo["efectivo_devuelto"] == "3000.00" and arqueo["esperado"] == "30000.00"      # 20.000 + 13.000 − 3.000
    assert [x["monto"] for x in api.get("cata", f"/pedidos/{pedido['id']}/devoluciones").json()] == ["3000.00"]


def test_no_se_devuelve_mas_de_lo_cobrado_por_ese_medio(con_pin):
    api = con_pin
    abrir_turno(api)
    pedido = cuenta_cobrada_en_efectivo(api)                       # 13.000 en efectivo
    sup = {"supervisor_id": api.s["admin"].id, "pin_supervisor": "4821"}
    assert devolver(api, pedido, "10000", **sup).status_code == 201
    r = devolver(api, pedido, "3500", **sup)                       # solo quedan 3.000
    assert r.status_code == 422 and "quedan 3000.00" in r.json()["detalle"]
    assert devolver(api, pedido, "3000", **sup).status_code == 201
    por_tarjeta = devolver(api, pedido, "100", medio="tarjeta", numero_operacion="X-1", **sup)
    assert por_tarjeta.status_code == 422                          # nada entró por tarjeta
    assert devolver(api, pedido, "0", **sup).status_code == 422


def test_el_administrador_no_necesita_pin_y_el_efectivo_pide_turno(con_pin):
    api = con_pin
    abrir_turno(api)
    pedido = cuenta_cobrada_en_efectivo(api)
    # El admin no tiene turno abierto: el efectivo sale del cajón de alguien, así que no puede.
    r = devolver(api, pedido, "1000", persona="admin")
    assert r.status_code == 422 and "turno" in r.json()["detalle"]
    # Sin turno la cajera tampoco (se cierra el suyo).
    t = api.get("cata", "/turnos/actual").json()
    assert api.post("cata", f"/turnos/{t['id']}/cerrar", {"contado": "33000", "nota": "ok"}).status_code == 200
    r = devolver(api, pedido, "1000", supervisor_id=api.s["admin"].id, pin_supervisor="4821")
    assert r.status_code == 422 and "turno" in r.json()["detalle"]


def test_solo_de_cuentas_cobradas_y_con_motivo(con_pin):
    api = con_pin
    abrir_turno(api)
    abierta = mesa_con_cuenta(api, platos=1)                       # cuenta pedida, sin cobrar
    sup = {"supervisor_id": api.s["admin"].id, "pin_supervisor": "4821"}
    r = devolver(api, abierta, "1000", **sup)
    assert r.status_code == 422 and "ya cobrada" in r.json()["detalle"]
    assert api.post("cata", f"/pedidos/{abierta['id']}/devoluciones",
                    {"medio": "efectivo", "monto": "1", "motivo": ""}).status_code == 422       # motivo vacío (validación)
    assert api.post("ana", f"/pedidos/{abierta['id']}/devoluciones",
                    {"medio": "efectivo", "monto": "1", "motivo": "x y z"}).status_code == 403  # el mesero no devuelve


def test_tarjeta_va_al_cuadre_del_terminal_y_el_resumen_queda_neto(con_pin):
    api = con_pin
    abrir_turno(api)
    pedido = mesa_con_cuenta(api, platos=2)                        # 13.000
    t = api.s["terminal"].id
    assert api.post("cata", f"/pedidos/{pedido['id']}/pagos",
                    {"medio": "tarjeta", "monto": "13000", "terminal_id": t, "numero_operacion": "A-1"}).status_code == 201
    sup = {"supervisor_id": api.s["admin"].id, "pin_supervisor": "4821"}
    sin_op = devolver(api, pedido, "2000", medio="tarjeta", **sup)
    assert sin_op.status_code == 422 and "número de operación" in sin_op.json()["detalle"]
    r = devolver(api, pedido, "2000", medio="tarjeta", numero_operacion="D-1", **sup)
    assert r.status_code == 201 and r.json()["turno_id"] is None

    cuadre = api.get("cata", f"/cierre/terminal/{t}{_rango()}").json()
    assert cuadre["total_registrado"] == "11000.00"
    assert cuadre["operaciones"] == [["A-1", "13000.00"], ["D-1", "-2000.00"]]
    resumen = api.get("admin", f"/cierre/resumen{_rango()}").json()
    assert resumen["por_medio"]["tarjeta"] == "11000.00" and resumen["devoluciones"] == "2000.00"


def test_devolver_todo_con_anular_documento_pide_nota_de_credito(db, con_pin):
    api = con_pin
    abrir_turno(api)
    pedido = cuenta_cobrada_en_efectivo(api, platos=1)            # 6.500
    sup = {"supervisor_id": api.s["admin"].id, "pin_supervisor": "4821"}
    # Parcial: la nota de crédito es por la cuenta completa, así que no aplica todavía.
    r = devolver(api, pedido, "1000", anular_documento=True, **sup)
    assert r.status_code == 201 and r.json()["nota_credito_estado"] == "no_aplica"
    # Total, pero el local no tiene facturador conectado: la devolución queda firme igual.
    r = devolver(api, pedido, "5500", anular_documento=True, **sup)
    assert r.status_code == 201 and r.json()["nota_credito_estado"] == "no_disponible"
    assert db.query(Devolucion).filter_by(pedido_id=pedido["id"]).count() == 2


def test_lista_de_cobradas_con_lo_pagado_y_devuelto(con_pin):
    api = con_pin
    abrir_turno(api)
    pedido = cuenta_cobrada_en_efectivo(api, platos=1)
    devolver(api, pedido, "1500", supervisor_id=api.s["admin"].id, pin_supervisor="4821")
    lista = api.get("cata", "/cobradas").json()
    assert len(lista) == 1 and lista[0]["pedido_id"] == pedido["id"] and lista[0]["total"] == "6500.00"
    assert lista[0]["pagado"]["efectivo"] == "6500.00" and lista[0]["devuelto"]["efectivo"] == "1500.00"
    assert api.get("ana", "/cobradas").status_code == 403
