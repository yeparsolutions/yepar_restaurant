# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_caja.py
# Pruebas por HTTP de caja y cobro: turnos, descuento, propina, pagos,
# libro de propinas, cuadre por terminal y resumen del período.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from datetime import datetime, timedelta, timezone

import pytest

from models import RolUsuario


@pytest.fixture()
def api(db, cliente, cabeceras, cobro):
    """Cobro de ejemplo (cajera Cata con tope 10%, admin, chef...) con todos en su sucursal."""
    for persona in ("ana", "beto", "chef", "admin", "cata", "otra_cajera"):
        cobro[persona].sucursal_id = cobro["sucursal"].id
    db.commit()

    class Api:
        s = cobro

        def como(self, persona, metodo, ruta, **kw):
            return getattr(cliente, metodo)(ruta, headers=cabeceras(cobro[persona]), **kw)

        def get(self, persona, ruta, **kw):
            return self.como(persona, "get", ruta, **kw)

        def post(self, persona, ruta, json=None, **kw):
            return self.como(persona, "post", ruta, json=json or {}, **kw)

        def put(self, persona, ruta, json=None, **kw):
            return self.como(persona, "put", ruta, json=json or {}, **kw)

    return Api()


def mesa_con_cuenta(api, mesa="m1", mesero="ana", platos=1):
    """Una mesa con `platos` hamburguesas ya cocinadas y la cuenta pedida ($6.500 cada una)."""
    pedido = api.post(mesero, "/pedidos", {"mesa_id": api.s[mesa].id}).json()
    lineas = [api.post(mesero, f"/pedidos/{pedido['id']}/lineas", {"item_id": api.s["burger"].id}).json()["linea"]
              for _ in range(platos)]
    assert api.post(mesero, f"/pedidos/{pedido['id']}/enviar").status_code == 200
    for l in lineas:
        assert api.post("chef", f"/cocina/lineas/{l['id']}/iniciar").status_code == 200
        assert api.post("chef", f"/cocina/lineas/{l['id']}/lista").status_code == 200
    r = api.post(mesero, f"/pedidos/{pedido['id']}/cuenta")
    assert r.status_code == 200, r.text
    return r.json()


def abrir_turno(api, persona="cata", fondo="20000"):
    r = api.post(persona, "/turnos", {"caja_id": api.s["caja"].id, "fondo": fondo})
    assert r.status_code == 201, r.text
    return r.json()


# ── Turnos ───────────────────────────────────────────────────
def test_turno_abrir_cobrar_en_efectivo_y_cerrar(db, api):
    turno = abrir_turno(api)
    assert turno["estado"] == "abierto" and turno["fondo"] == "20000.00" and turno["caja"] == "Caja 1"
    assert api.get("cata", "/turnos/actual").json()["id"] == turno["id"]

    pedido = mesa_con_cuenta(api)
    pago = api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "efectivo", "monto": "6500", "recibido": "10000"})
    assert pago.status_code == 201, pago.text
    assert pago.json()["vuelto"] == "3500.00" and pago.json()["turno_id"] == turno["id"]
    assert pago.json()["pedido_estado"] == "cerrado" and pago.json()["cuenta"]["pendiente"] == "0.00"

    arqueo = api.get("cata", f"/turnos/{turno['id']}/arqueo").json()
    assert (arqueo["fondo"], arqueo["efectivo_cobrado"], arqueo["esperado"]) == ("20000.00", "6500.00", "26500.00")

    # Contó de menos: sin nota no deja cerrar; con nota, queda la diferencia.
    r = api.post("cata", f"/turnos/{turno['id']}/cerrar", {"contado": "26000"})
    assert r.status_code == 422 and "nota" in r.json()["detalle"]
    cerrado = api.post("cata", f"/turnos/{turno['id']}/cerrar", {"contado": "26000", "nota": "Faltaron 500 de vuelto"})
    assert cerrado.status_code == 200
    assert cerrado.json()["estado"] == "cerrado" and cerrado.json()["diferencia"] == "-500.00"
    assert api.get("cata", "/turnos/actual").status_code == 404

    # El administrador revisa el cuadre; la cajera no.
    assert api.post("cata", f"/turnos/{turno['id']}/revisar").status_code == 403
    rev = api.post("admin", f"/turnos/{turno['id']}/revisar")
    assert rev.status_code == 200 and rev.json()["revisado_por_id"] == api.s["admin"].id


def test_reglas_de_turno_y_caja(db, api):
    abrir_turno(api)
    r = api.post("otra_cajera", "/turnos", {"caja_id": api.s["caja"].id})
    assert r.status_code == 422 and "ya tiene un turno abierto" in r.json()["detalle"]
    assert api.post("cata", "/turnos", {"caja_id": api.s["caja2"].id}).status_code == 422       # ya tiene uno propio
    assert api.post("ana", "/turnos", {"caja_id": api.s["caja2"].id}).status_code == 403        # el mesero no abre caja
    assert api.get("cata", "/turnos/actual").status_code == 200
    assert api.get("otra_cajera", "/turnos/actual").status_code == 404
    # Una cajera no ve el arqueo del turno de otra.
    turno_id = api.get("cata", "/turnos/actual").json()["id"]
    assert api.get("otra_cajera", f"/turnos/{turno_id}/arqueo").status_code == 403
    assert api.get("admin", f"/turnos/{turno_id}/arqueo").status_code == 200


def test_cajas_y_terminales_por_http(db, api):
    r = api.post("admin", "/cajas", {"nombre": "Caja barra"})
    assert r.status_code == 201 and r.json()["nombre"] == "Caja barra"
    assert api.post("admin", "/cajas", {"nombre": "Caja barra"}).status_code == 422
    assert [c["nombre"] for c in api.get("cata", "/cajas").json()] == ["Caja 1", "Caja 2", "Caja barra"]
    assert api.post("cata", "/cajas", {"nombre": "X"}).status_code == 403
    t = api.post("admin", "/terminales", {"nombre": "Terminal 2"})
    assert t.status_code == 201
    assert [x["nombre"] for x in api.get("ana", "/terminales").json()] == ["Terminal 1", "Terminal 2"]


# ── Descuento y propina ──────────────────────────────────────
def test_descuento_con_tope_de_la_cajera_y_admin_sin_tope(db, api):
    abrir_turno(api)
    pedido = mesa_con_cuenta(api)
    r = api.post("cata", f"/pedidos/{pedido['id']}/descuento", {"porcentaje": "20"})
    assert r.status_code == 422 and "tope" in r.json()["detalle"]
    r = api.post("cata", f"/pedidos/{pedido['id']}/descuento", {"porcentaje": "10"})
    assert r.status_code == 200 and r.json()["cuenta"]["descuento"] == "650.00" and r.json()["cuenta"]["total"] == "5850.00"
    r = api.post("admin", f"/pedidos/{pedido['id']}/descuento", {"porcentaje": "50"})
    assert r.json()["cuenta"]["descuento"] == "3250.00"
    assert api.post("ana", f"/pedidos/{pedido['id']}/descuento", {"porcentaje": "5"}).status_code == 403   # el mesero no da descuentos


def test_propina_sugerida_manual_y_solo_del_mesero_de_la_mesa(db, api):
    pedido = mesa_con_cuenta(api)
    assert api.post("beto", f"/pedidos/{pedido['id']}/propina", {}).status_code == 403           # mesa de Ana
    r = api.post("ana", f"/pedidos/{pedido['id']}/propina", {})
    assert r.status_code == 200 and r.json()["cuenta"]["propina"] == "650.00"                    # 10% sugerido
    r = api.post("ana", f"/pedidos/{pedido['id']}/propina", {"monto": "1000"})
    assert r.json()["cuenta"]["propina"] == "1000.00" and r.json()["cuenta"]["total"] == "7500.00"
    assert api.post("ana", f"/pedidos/{pedido['id']}/propina", {"monto": "-5"}).status_code == 422


def test_configuracion_de_cobro(db, api):
    c = api.get("ana", "/configuracion/cobro").json()
    assert c == {"propina_modo": "por_mesa", "propina_sugerida_pct": "10.0"}
    r = api.put("admin", "/configuracion/cobro", {"propina_modo": "grupal", "propina_sugerida_pct": "12"})
    assert r.json() == {"propina_modo": "grupal", "propina_sugerida_pct": "12.0"}
    assert api.put("cata", "/configuracion/cobro", {"propina_modo": "por_mesa"}).status_code == 403
    assert api.put("admin", "/configuracion/cobro", {"propina_modo": "raro"}).status_code == 422
    assert api.put("admin", "/configuracion/cobro", {"propina_sugerida_pct": "150"}).status_code == 422


# ── Pagos ────────────────────────────────────────────────────
def test_pago_con_tarjeta_y_cuadre_por_terminal(db, api):
    pedido = mesa_con_cuenta(api, platos=2)                      # $13.000
    t = api.s["terminal"].id
    # El mesero cobra con el terminal portátil en SU mesa.
    sin_op = api.post("ana", f"/pedidos/{pedido['id']}/pagos", {"medio": "tarjeta", "monto": "5000", "terminal_id": t})
    assert sin_op.status_code == 422 and "operación" in sin_op.json()["detalle"]
    p1 = api.post("ana", f"/pedidos/{pedido['id']}/pagos",
                  {"medio": "tarjeta", "monto": "5000", "terminal_id": t, "numero_operacion": "A-1"})
    assert p1.status_code == 201 and p1.json()["pedido_estado"] == "cuenta_pedida" and p1.json()["cuenta"]["pendiente"] == "8000.00"
    dup = api.post("ana", f"/pedidos/{pedido['id']}/pagos",
                   {"medio": "tarjeta", "monto": "1000", "terminal_id": t, "numero_operacion": "A-1"})
    assert dup.status_code == 422 and "ya se registró" in dup.json()["detalle"]
    p2 = api.post("ana", f"/pedidos/{pedido['id']}/pagos",
                  {"medio": "transferencia", "monto": "8000", "numero_operacion": "TR-77"})
    assert p2.json()["pedido_estado"] == "cerrado"

    ahora = datetime.now(timezone.utc)
    q = f"?desde={(ahora - timedelta(hours=1)).isoformat().replace('+', '%2B')}&hasta={(ahora + timedelta(hours=1)).isoformat().replace('+', '%2B')}&reportado=5500"
    cuadre = api.get("cata", f"/cierre/terminal/{t}{q}").json()
    assert cuadre["total_registrado"] == "5000.00" and cuadre["total_reportado"] == "5500.00"
    assert cuadre["diferencia"] == "500.00" and cuadre["operaciones"] == [["A-1", "5000.00"]]
    assert api.get("ana", f"/cierre/terminal/{t}{q}").status_code == 403


def test_el_mesero_no_cobra_efectivo_ni_mesas_ajenas(db, api):
    abrir_turno(api)
    pedido = mesa_con_cuenta(api)
    r = api.post("ana", f"/pedidos/{pedido['id']}/pagos", {"medio": "efectivo", "monto": "6500"})
    assert r.status_code == 422 and "no maneja efectivo" in r.json()["detalle"]
    r = api.post("beto", f"/pedidos/{pedido['id']}/pagos", {"medio": "transferencia", "monto": "100", "numero_operacion": "X"})
    assert r.status_code == 403
    assert api.post("chef", f"/pedidos/{pedido['id']}/pagos", {"medio": "efectivo", "monto": "6500"}).status_code == 403


def test_efectivo_sin_turno_y_errores_de_monto(db, api):
    pedido = mesa_con_cuenta(api)
    r = api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "efectivo", "monto": "6500"})
    assert r.status_code == 422 and "abrir turno" in r.json()["detalle"]
    abrir_turno(api)
    assert api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "efectivo", "monto": "9000"}).status_code == 422
    assert api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "efectivo", "monto": "6500", "recibido": "5000"}).status_code == 422
    assert api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "cheque", "monto": "6500"}).status_code == 422
    assert api.post("cata", "/pedidos/no-existe/pagos", {"medio": "efectivo", "monto": "1"}).status_code == 404


def test_pago_de_la_tablet_no_se_registra_dos_veces(db, api):
    abrir_turno(api)
    pedido = mesa_con_cuenta(api, platos=2)
    datos = {"medio": "efectivo", "monto": "5000", "pago_id": "11111111-aaaa-bbbb-cccc-222222222222"}
    assert api.post("cata", f"/pedidos/{pedido['id']}/pagos", datos).status_code == 201
    assert api.post("cata", f"/pedidos/{pedido['id']}/pagos", datos).status_code == 422


# ── Propinas ─────────────────────────────────────────────────
def pagar_con_propina(api, mesero, mesa, propina):
    pedido = mesa_con_cuenta(api, mesa=mesa, mesero=mesero)
    r = api.post(mesero, f"/pedidos/{pedido['id']}/propina", {"monto": propina})
    total = r.json()["cuenta"]["total"]
    p = api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "efectivo", "monto": total})
    assert p.status_code == 201, p.text
    return pedido


def test_libro_de_propinas_por_mesa_y_entrega(db, api):
    abrir_turno(api)
    pagar_con_propina(api, "ana", "m1", "650")
    pagar_con_propina(api, "beto", "m2", "300")
    assert [p["monto"] for p in api.get("ana", "/propinas").json()] == ["650.00"]               # cada mesero ve lo suyo
    assert len(api.get("cata", "/propinas").json()) == 2
    saldos = {s["mesero_id"]: s["monto"] for s in api.get("cata", "/propinas/saldos").json()}
    assert saldos == {api.s["ana"].id: "650.00", api.s["beto"].id: "300.00"}
    assert api.get("ana", "/propinas/saldos").status_code == 403

    r = api.post("cata", "/propinas/entregar", {"mesero_id": api.s["ana"].id})
    assert r.status_code == 200 and r.json()["entregado"] == "650.00"
    assert api.post("cata", "/propinas/entregar", {"mesero_id": api.s["ana"].id}).status_code == 422   # ya no tiene pendientes
    assert api.post("ana", "/propinas/entregar", {"mesero_id": api.s["ana"].id}).status_code == 403
    assert [p["estado"] for p in api.get("ana", "/propinas").json()] == ["entregada"]
    assert [p["estado"] for p in api.get("cata", "/propinas?estado=pendiente").json()] == ["pendiente"]


def test_fondo_grupal_repartido_en_partes_iguales_y_por_pesos(db, api):
    api.put("admin", "/configuracion/cobro", {"propina_modo": "grupal"})
    abrir_turno(api)
    pagar_con_propina(api, "ana", "m1", "1000")
    pagar_con_propina(api, "beto", "m2", "500")
    assert [(s["mesero_id"], s["monto"]) for s in api.get("cata", "/propinas/saldos").json()] == [(None, "1500.00")]

    ana, beto = api.s["ana"].id, api.s["beto"].id
    ambos = {"participantes": [ana, beto], "pesos": {str(ana): "1"}}
    assert api.post("admin", "/propinas/repartir", ambos).status_code == 422                 # uno solo de los dos
    assert api.post("cata", "/propinas/repartir", {"participantes": [ana]}).status_code == 403
    r = api.post("admin", "/propinas/repartir", {"pesos": {str(ana): "2", str(beto): "1"}})
    assert r.status_code == 200
    assert {p["usuario_id"]: p["monto"] for p in r.json()} == {ana: "1000.00", beto: "500.00"}
    assert api.post("admin", "/propinas/repartir", {"participantes": [ana]}).status_code == 422   # ya no queda fondo


# ── Cierre ───────────────────────────────────────────────────
def test_resumen_del_periodo(db, api):
    turno = abrir_turno(api)
    pagar_con_propina(api, "ana", "m1", "650")                                   # $6.500 + $650 propina, efectivo
    api.post("cata", f"/turnos/{turno['id']}/cerrar", {"contado": "26000", "nota": "falta un billete"})

    ahora = datetime.now(timezone.utc)
    desde, hasta = (ahora - timedelta(hours=1)).isoformat(), (ahora + timedelta(hours=1)).isoformat()
    r = api.get("admin", "/cierre/resumen", params={"desde": desde, "hasta": hasta})
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["cerradas"], d["ventas"], d["propinas"], d["total_cobrado"]) == (1, "6500.00", "650.00", "7150.00")
    assert d["por_medio"] == {"efectivo": "7150.00"}
    assert d["turnos_con_diferencia"] == [{"turno_id": turno["id"], "diferencia": "-1150.00"}]

    assert api.get("cata", "/cierre/resumen", params={"desde": desde, "hasta": hasta}).status_code == 403
    assert api.get("admin", "/cierre/resumen", params={"desde": hasta, "hasta": desde}).status_code == 422


def test_un_restaurante_no_toca_la_caja_de_otro(db, api, otro_local, nuevo_usuario, cabeceras, cliente):
    ajena, suc = otro_local
    admin_ajeno = nuevo_usuario(ajena, "Admin ajeno", roles=(RolUsuario.administrador,), sucursal_id=suc.id)
    cab = cabeceras(admin_ajeno)
    turno = abrir_turno(api)
    pedido = mesa_con_cuenta(api)
    assert cliente.post(f"/turnos/{turno['id']}/revisar", headers=cab).status_code == 404
    assert cliente.get(f"/turnos/{turno['id']}/arqueo", headers=cab).status_code == 404
    assert cliente.post(f"/pedidos/{pedido['id']}/descuento", json={"porcentaje": "5"}, headers=cab).status_code in (403, 404)
    assert cliente.get(f"/cierre/terminal/{api.s['terminal'].id}", headers=cab,
                       params={"desde": "2026-01-01T00:00:00+00:00", "hasta": "2027-01-01T00:00:00+00:00"}).status_code == 404
