# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_despacho.py
# Delivery con Yepar Go, con un Yepar Go SIMULADO (httpx.MockTransport): nunca se llama al real.
# ============================================================

import json

import httpx
import pytest

from servicios.facturacion import base
from tests.test_api_caja import api, mesa_con_cuenta  # noqa: F401  (reutiliza el cobro de ejemplo)

CENTRO = "11111111-1111-4111-8111-111111111111"


class YeparGoFalso:
    """Un Yepar Go de mentira: guarda las órdenes que le piden y responde según el guion."""

    def __init__(self):
        self.llamadas = []                  # [(método, ruta, headers, cuerpo)]
        self.guion = []                     # respuestas forzadas (httpx.Response o Exception), en orden
        self.ordenes = {}                   # id → {"status": ...}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(request.content) if request.content else None
        ruta = request.url.path
        self.llamadas.append((request.method, ruta, dict(request.headers), cuerpo))
        if request.headers.get("x-api-key") == "clave-mala-123":
            return httpx.Response(401, json={"message": "API Key inválida o revocada"})
        if ruta.endswith("/pickup-centers"):
            return httpx.Response(200, json=[{"id": CENTRO, "name": "Local Centro", "address": "Av. Siempre Viva 742"}])
        if self.guion:
            r = self.guion.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        if request.method == "POST" and ruta.endswith("/orders"):
            n = len(self.ordenes) + 1
            oid = f"00000000-0000-4000-8000-{n:012d}"
            self.ordenes[oid] = {"status": "pending"}
            return httpx.Response(201, json={"id": oid, "orderNumber": f"YGO-2026-{n:04d}", "status": "pending",
                                             "trackingToken": f"tok{n}", "trackingUrl": f"https://go.test/track/tok{n}"})
        if request.method == "GET" and "/orders/" in ruta:
            oid = ruta.rsplit("/", 1)[1]
            if oid not in self.ordenes:
                return httpx.Response(404, json={"message": "Orden no encontrada"})
            return httpx.Response(200, json={"id": oid, "status": self.ordenes[oid]["status"],
                                             "trackingUrl": "https://go.test/track/x"})
        return httpx.Response(404)

    @property
    def creaciones(self):
        return [c for c in self.llamadas if c[0] == "POST"]


@pytest.fixture()
def go(monkeypatch):
    falso = YeparGoFalso()
    monkeypatch.setattr(base, "transporte_http", lambda: httpx.MockTransport(falso))
    return falso


@pytest.fixture()
def conectado(api, go):
    r = api.put("admin", "/despacho/conexion", {"api_key": "ygo_clave-buena-9876", "direccion_retiro": "Av. Siempre Viva 742",
                                                "centro_retiro_id": CENTRO})
    assert r.status_code == 200, r.text
    return api


DEST = {"destinatario": "Juan Pérez", "direccion": "Av. Providencia 1234", "telefono": "+56911112222",
        "ciudad": "Santiago", "notas": "Tocar el timbre 2 veces"}


def test_conectar_valida_la_llave_y_la_guarda_cifrada(db, api, go):
    r = api.put("admin", "/despacho/conexion", {"api_key": "clave-mala-123"})
    assert r.status_code == 422 and "no es válida" in r.json()["detalle"]
    r = api.put("admin", "/despacho/conexion", {"api_key": "ygo_clave-buena-9876", "centro_retiro_id": "no-existe"})
    assert r.status_code == 422 and "centro de retiro" in r.json()["detalle"]
    r = api.put("admin", "/despacho/conexion", {"api_key": "ygo_clave-buena-9876", "centro_retiro_id": CENTRO,
                                                "direccion_retiro": "Av. Siempre Viva 742"})
    assert r.status_code == 200 and r.json()["api_key_final"] == "••••9876" and "buena" not in r.text
    from models import IntegracionDespacho
    assert "buena" not in db.query(IntegracionDespacho).one().api_key_cifrada
    assert api.get("cata", "/despacho/conexion").json()["centro_retiro_id"] == CENTRO
    assert api.put("cata", "/despacho/conexion", {"api_key": "x"}).status_code == 403
    assert api.get("admin", "/despacho/centros-retiro").json() == [
        {"id": CENTRO, "nombre": "Local Centro", "direccion": "Av. Siempre Viva 742"}]


def test_sin_conexion_no_hay_despacho(db, api, go):
    pedido = mesa_con_cuenta(api)
    r = api.post("cata", f"/pedidos/{pedido['id']}/despacho", DEST)
    assert r.status_code == 404 and "no tiene Yepar Go conectado" in r.json()["detalle"]


def test_pedir_reparto_crea_la_orden_con_el_contrato_de_yepar_go(db, conectado, go):
    api = conectado
    pedido = mesa_con_cuenta(api, platos=2)
    r = api.post("cata", f"/pedidos/{pedido['id']}/despacho", DEST)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["estado"] == "creado" and d["go_numero"] == "YGO-2026-0001" and d["estado_go"] == "pending"
    assert d["seguimiento_url"] == "https://go.test/track/tok1"
    metodo, ruta, cab, cuerpo = go.creaciones[0]
    assert ruta == "/api/v1/integration/orders" and cab["x-api-key"] == "ygo_clave-buena-9876"
    assert cuerpo["recipientName"] == "Juan Pérez" and cuerpo["deliveryAddress"] == "Av. Providencia 1234"
    assert cuerpo["recipientPhone"] == "+56911112222" and cuerpo["deliveryCity"] == "Santiago"
    assert cuerpo["pickupAddress"] == "Av. Siempre Viva 742" and cuerpo["pickupCenterId"] == CENTRO
    assert cuerpo["packageDescription"] == "2× Hamburguesa"
    assert cuerpo["notes"].startswith(f"YRS-D{d['id']} · Pedido ") and "timbre" in cuerpo["notes"]
    assert "deliveryLat" not in cuerpo and "recipientEmail" not in cuerpo       # lo vacío no se envía (Yepar Go rechaza extras)
    # Repetirlo no pide otro motorista.
    assert api.post("cata", f"/pedidos/{pedido['id']}/despacho", DEST).json()["id"] == d["id"]
    assert len(go.creaciones) == 1
    assert api.get("cata", f"/pedidos/{pedido['id']}/despacho").json()["go_numero"] == "YGO-2026-0001"


def test_yepar_go_caido_deja_el_despacho_pendiente_y_se_reintenta(db, conectado, go):
    api = conectado
    pedido = mesa_con_cuenta(api)
    go.guion = [httpx.Response(503, json={"message": "caído"})]
    r = api.post("cata", f"/pedidos/{pedido['id']}/despacho", DEST)
    assert r.status_code == 202 and r.json()["estado"] == "pendiente" and r.json()["intentos"] == 1
    assert api.get("cata", "/despachos?estado=pendiente").json()[0]["pedido_id"] == pedido["id"]
    r = api.post("cata", "/despachos/reintentar")
    assert r.status_code == 200 and r.json()[0]["estado"] == "creado" and r.json()[0]["intentos"] == 2
    assert api.post("cata", "/despachos/reintentar").json() == []


def test_corte_de_red_tambien_es_reintentable(db, conectado, go):
    api = conectado
    pedido = mesa_con_cuenta(api)
    go.guion = [httpx.ReadTimeout("lento")]
    r = api.post("cata", f"/pedidos/{pedido['id']}/despacho", DEST)
    assert r.status_code == 202 and "PUDO crearse" in r.json()["ultimo_error"]


def test_rechazo_de_yepar_go_se_explica_y_se_puede_corregir(db, conectado, go):
    api = conectado
    pedido = mesa_con_cuenta(api)
    go.guion = [httpx.Response(400, json={"message": ["deliveryAddress must be a string", "recipientName es muy corto"]})]
    r = api.post("cata", f"/pedidos/{pedido['id']}/despacho", DEST)
    assert r.status_code == 422 and "recipientName es muy corto" in r.json()["detail"]
    # Corrige y reintenta sobre el MISMO despacho.
    ok = api.post("cata", f"/pedidos/{pedido['id']}/despacho", {**DEST, "destinatario": "Juan Carlos Pérez"})
    assert ok.status_code == 201 and ok.json()["intentos"] == 2
    assert len(api.get("cata", "/despachos").json()) == 1
    # El límite del plan también llega como rechazo, sin reintentos automáticos.
    otro = mesa_con_cuenta(api, mesa="m2")
    go.guion = [httpx.Response(403, json={"message": "Límite de órdenes del plan alcanzado"})]
    r = api.post("cata", f"/pedidos/{otro['id']}/despacho", DEST)
    assert r.status_code == 422 and "Límite" in r.json()["detail"]
    assert api.post("cata", "/despachos/reintentar").json() == []


def test_seguimiento_actualiza_el_estado_y_solo_consulta_lo_que_sigue_en_la_calle(db, conectado, go):
    api = conectado
    p1, p2 = mesa_con_cuenta(api), mesa_con_cuenta(api, mesa="m2")
    d1 = api.post("cata", f"/pedidos/{p1['id']}/despacho", DEST).json()
    d2 = api.post("cata", f"/pedidos/{p2['id']}/despacho", {**DEST, "destinatario": "Ana Soto"}).json()
    ids = list(go.ordenes)
    go.ordenes[ids[0]]["status"], go.ordenes[ids[1]]["status"] = "in_route", "delivered"
    r = api.post("cata", "/despachos/actualizar").json()
    assert {x["id"]: x["estado_go"] for x in r} == {d1["id"]: "in_route", d2["id"]: "delivered"}
    antes = len(go.llamadas)
    assert [x["id"] for x in api.get("cata", "/despachos?en_curso=true").json()] == [d1["id"]]
    api.post("cata", "/despachos/actualizar")                   # la entregada ya no se vuelve a consultar
    assert len(go.llamadas) - antes == 1
    assert api.post("cata", f"/despachos/{d2['id']}/actualizar").json()["estado_go"] == "delivered"
    assert api.post("cata", "/despachos/99999/actualizar").status_code == 404


def test_actualizacion_masiva_tolera_a_uno_caido(db, conectado, go):
    api = conectado
    p1, p2 = mesa_con_cuenta(api), mesa_con_cuenta(api, mesa="m2")
    api.post("cata", f"/pedidos/{p1['id']}/despacho", DEST)
    api.post("cata", f"/pedidos/{p2['id']}/despacho", DEST)
    go.guion = [httpx.Response(503)]
    r = api.post("cata", "/despachos/actualizar")
    assert r.status_code == 200 and sum(1 for x in r.json() if x["ultimo_error"]) == 1


def test_permisos_y_aislamiento(db, conectado, go):
    api = conectado
    pedido = mesa_con_cuenta(api, mesero="ana")
    assert api.post("beto", f"/pedidos/{pedido['id']}/despacho", DEST).status_code == 403     # no es su mesa
    assert api.post("ana", f"/pedidos/{pedido['id']}/despacho", DEST).status_code == 201       # el mesero en su cuenta
    assert api.get("ana", "/despachos").status_code == 403
    assert api.post("chef", f"/pedidos/{pedido['id']}/despacho", DEST).status_code == 403
    assert api.post("cata", f"/pedidos/{pedido['id']}/despacho", {**DEST, "destinatario": "x"}).status_code == 422


def test_cuenta_anulada_no_se_despacha_y_desconectar_corta_el_servicio(db, conectado, go):
    api = conectado
    p = api.post("ana", "/pedidos", {"mesa_id": api.s["m1"].id}).json()
    assert api.post("ana", f"/pedidos/{p['id']}/anular").status_code == 200
    r = api.post("cata", f"/pedidos/{p['id']}/despacho", DEST)
    assert r.status_code == 422 and "anulada" in r.json()["detalle"]
    assert api.como("admin", "delete", "/despacho/conexion").status_code == 204
    otra = mesa_con_cuenta(api, mesa="m2")
    assert api.post("cata", f"/pedidos/{otra['id']}/despacho", DEST).status_code == 404


def test_delivery_sin_mesa_permite_varias_cuentas_a_la_vez(db, conectado, go):
    api = conectado
    a = api.post("ana", "/pedidos", {})
    b = api.post("ana", "/pedidos", {})
    assert a.status_code == 201 and b.status_code == 201 and a.json()["mesa_id"] is None
    t = api.post("ana", f"/pedidos/{a.json()['id']}/lineas", {"item_id": api.s["burger"].id}).json()["linea"]
    assert api.post("ana", f"/pedidos/{a.json()['id']}/enviar").status_code == 200
    assert api.get("chef", "/cocina/comandas").json()[0]["mesa"] == "Mostrador"
    assert api.post("ana", f"/pedidos/{a.json()['id']}/despacho", DEST).status_code == 201
