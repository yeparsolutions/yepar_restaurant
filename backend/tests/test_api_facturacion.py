# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_facturacion.py
# Pruebas por HTTP de la facturación electrónica con facturadores
# SIMULADOS (httpx.MockTransport): nunca se llama a YeparDTE ni a
# YeparFactura de verdad.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

import json

import httpx
import pytest

from servicios.facturacion import base


class FacturadorFalso:
    """Un YeparDTE/YeparFactura de mentira: anota cada llamada y responde según el guion."""

    def __init__(self):
        self.llamadas = []          # [(método, ruta, headers, cuerpo)]
        self.guion = []             # respuestas en orden: httpx.Response o Exception; si se acaba, éxito
        self.clave_a_folio = {}     # idempotencia real: misma clave → mismo folio

    def __call__(self, request: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(request.content) if request.content else None
        self.llamadas.append((request.method, request.url.path, dict(request.headers), cuerpo))
        if request.url.path.endswith("/ping"):
            if request.headers.get("x-api-key") == "clave-mala-123":
                return httpx.Response(401, json={"detail": "API Key inválida"})
            return httpx.Response(200, json={"ok": True})
        if self.guion:
            r = self.guion.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        clave = cuerpo["idempotency_key"]
        folio = self.clave_a_folio.setdefault(clave, 1001 + len(self.clave_a_folio))
        total = sum(float(i["precio"]) * (i.get("qty") or i.get("cantidad")) - float(i["descuento"]) for i in cuerpo["items"])
        doc = {"folio": folio, "numero": f"00-{folio}", "neto": round(total / 1.19, 2), "iva": round(total - total / 1.19, 2),
               "total": total, "pdf_url": f"https://pdf.test/{folio}"}
        return httpx.Response(200, json={"documento": doc, "track_id": "T-1"})

    @property
    def emisiones(self):
        return [l for l in self.llamadas if l[1].endswith("/emitir")]


@pytest.fixture()
def falso(monkeypatch):
    f = FacturadorFalso()
    monkeypatch.setattr(base, "transporte_http", lambda: httpx.MockTransport(f))
    return f


@pytest.fixture()
def api(db, cliente, cabeceras, cobro, falso):
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


def pedido_pagado(api, con_descuento=True):
    """2 hamburguesas (una con extra tocineta): $14.000, descuento 10%, propina $700, pagado por transferencia."""
    pedido = api.post("ana", "/pedidos", {"mesa_id": api.s["m1"].id}).json()
    l1 = api.post("ana", f"/pedidos/{pedido['id']}/lineas", {"item_id": api.s["burger"].id, "extra_ids": [api.s["extra"].id]}).json()["linea"]
    l2 = api.post("ana", f"/pedidos/{pedido['id']}/lineas", {"item_id": api.s["burger"].id}).json()["linea"]
    api.post("ana", f"/pedidos/{pedido['id']}/enviar")
    for l in (l1, l2):
        api.post("chef", f"/cocina/lineas/{l['id']}/iniciar")
        api.post("chef", f"/cocina/lineas/{l['id']}/lista")
    api.post("ana", f"/pedidos/{pedido['id']}/cuenta")
    api.post("ana", f"/pedidos/{pedido['id']}/propina", {"monto": "700"})
    if con_descuento:
        assert api.post("cata", f"/pedidos/{pedido['id']}/descuento", {"porcentaje": "10"}).status_code == 200
    total = "13300.00" if con_descuento else "14700.00"
    assert api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "transferencia", "monto": total, "numero_operacion": "TR-1"}).status_code == 201
    return pedido["id"]


def conectar(api, proveedor="yepardte", persona="admin", clave="clave-buena-123"):
    return api.put(persona, "/facturacion/conexion", {"proveedor": proveedor, "api_key": clave})


# ── Conexión ─────────────────────────────────────────────────
def test_conectar_yepardte_valida_y_guarda_la_clave_cifrada(db, api, falso):
    r = conectar(api)
    assert r.status_code == 200, r.text
    assert r.json() == {"proveedor": "yepardte", "activo": True, "api_key_final": "••••-123"}   # solo los últimos 4
    assert falso.llamadas[0][1] == "/api/v1/ping" and falso.llamadas[0][2]["x-api-key"] == "clave-buena-123"
    from models import IntegracionFacturacion
    guardada = db.get(IntegracionFacturacion, api.s["empresa"].id).api_key_cifrada
    assert "clave-buena-123" not in guardada                              # nunca en texto plano
    assert api.get("cata", "/facturacion/conexion").json()["proveedor"] == "yepardte"


def test_clave_invalida_o_pais_equivocado_no_se_guardan(db, api):
    r = conectar(api, clave="clave-mala-123")
    assert r.status_code == 422 and "No se pudo validar" in r.json()["detalle"]
    r = conectar(api, proveedor="yeparfactura")                           # el restaurante es de Chile
    assert r.status_code == 422 and "VE" in r.json()["detalle"]
    assert api.get("cata", "/facturacion/conexion").status_code == 422     # sigue sin facturador
    assert conectar(api, persona="cata").status_code == 403                # solo el administrador conecta
    assert api.put("admin", "/facturacion/conexion", {"proveedor": "sii", "api_key": "x" * 10}).status_code == 422


def test_desconectar(db, api):
    conectar(api)
    assert api.como("admin", "delete", "/facturacion/conexion").status_code == 204
    pid = pedido_pagado(api)
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"})
    assert r.status_code == 422 and "no tiene un facturador" in r.json()["detalle"]


# ── Emisión (Chile · YeparDTE) ───────────────────────────────
def test_emitir_boleta_manda_lo_vendido_sin_propina_y_no_duplica(db, api, falso):
    conectar(api)
    pid = pedido_pagado(api)
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["estado"] == "emitido" and d["folio"] == "1001" and d["tipo"] == "boleta" and d["pdf_url"] == "https://pdf.test/1001"
    assert d["moneda"] == "CLP" and d["intentos"] == 1

    _, ruta, cabeceras, cuerpo = falso.emisiones[0]
    assert cabeceras["x-api-key"] == "clave-buena-123" and cuerpo["idempotency_key"] == f"yrs-{pid}"
    assert cuerpo["tipo"] == "boleta" and cuerpo["receptor"] == {"nombre": "Consumidor Final"} and cuerpo["iva_incluido"] is True
    assert [(i["precio"], i["qty"], i["descuento"]) for i in cuerpo["items"]] == [("7500.00", 1, "750.00"), ("6500.00", 1, "650.00")]
    assert sum(float(i["precio"]) * i["qty"] - float(i["descuento"]) for i in cuerpo["items"]) == 12600.0   # 14.000 − 1.400; la propina NO se factura

    # Repetir devuelve el mismo documento sin volver a llamar al facturador.
    otra = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"})
    assert otra.status_code == 201 and otra.json()["id"] == d["id"] and len(falso.emisiones) == 1
    assert api.get("cata", f"/pedidos/{pid}/documento").json()["folio"] == "1001"


def test_factura_exige_los_datos_del_receptor(db, api, falso):
    conectar(api)
    pid = pedido_pagado(api, con_descuento=False)
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura"})
    assert r.status_code == 422 and "rut" in r.json()["detalle"] and falso.emisiones == []
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": {
        "rut": "76.123.456-7", "nombre": "Constructora Sur SpA", "giro": "Construcción", "email": "pagos@sur.cl"}})
    assert r.status_code == 201
    assert falso.emisiones[0][3]["receptor"]["rut"] == "76.123.456-7" and falso.emisiones[0][3]["tipo"] == "factura"
    assert [i["descuento"] for i in falso.emisiones[0][3]["items"]] == ["0.00", "0.00"]


def test_sin_conexion_queda_pendiente_y_se_reintenta_sin_duplicar(db, api, falso):
    conectar(api)
    pid = pedido_pagado(api)
    falso.guion = [httpx.ConnectError("sin red")]
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"})
    assert r.status_code == 202 and r.json()["estado"] == "pendiente" and r.json()["folio"] is None
    assert "No se pudo conectar" in r.json()["ultimo_error"]
    assert [x["estado"] for x in api.get("cata", "/documentos?estado=pendiente").json()] == ["pendiente"]

    # Vuelve la red: se reintentan todos los pendientes, con la MISMA clave.
    rr = api.post("cata", "/documentos/reintentar")
    assert rr.status_code == 200 and rr.json()[0]["estado"] == "emitido" and rr.json()[0]["intentos"] == 2
    assert {e[3]["idempotency_key"] for e in falso.emisiones} == {f"yrs-{pid}"}
    assert api.post("cata", "/documentos/reintentar").json() == []


def test_si_tarda_en_responder_se_considera_pendiente_no_perdido(db, api, falso):
    conectar(api)
    pid = pedido_pagado(api)
    falso.guion = [httpx.ReadTimeout("lento")]
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"})
    assert r.status_code == 202 and "PUDO emitirse" in r.json()["ultimo_error"]
    assert api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"}).json()["estado"] == "emitido"


def test_rechazo_del_facturador_se_corrige_y_se_reintenta(db, api, falso):
    conectar(api)
    pid = pedido_pagado(api, con_descuento=False)
    falso.guion = [httpx.Response(400, json={"detail": "RUT del receptor inválido"})]
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": {"rut": "1-1", "nombre": "X"}})
    assert r.status_code == 422 and "RUT del receptor inválido" in r.json()["detail"]
    assert api.get("cata", f"/pedidos/{pid}/documento").json()["estado"] == "rechazado"
    assert api.post("cata", "/documentos/reintentar").json() == []          # un rechazo no se reintenta solo: hay que corregirlo
    ok = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": {"rut": "76.123.456-7", "nombre": "Sur SpA"}})
    assert ok.status_code == 201 and ok.json()["intentos"] == 2


def test_error_del_servidor_del_facturador_es_reintentable(db, api, falso):
    conectar(api)
    pid = pedido_pagado(api)
    falso.guion = [httpx.Response(503)]
    assert api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"}).status_code == 202


def test_solo_se_factura_una_cuenta_pagada_y_con_permiso(db, api, falso):
    conectar(api)
    abierta = api.post("ana", "/pedidos", {"mesa_id": api.s["m2"].id}).json()
    r = api.post("cata", f"/pedidos/{abierta['id']}/documento", {"tipo": "boleta"})
    assert r.status_code == 422 and "ya pagada" in r.json()["detalle"]
    pid = pedido_pagado(api)
    assert api.post("ana", f"/pedidos/{pid}/documento", {"tipo": "boleta"}).status_code == 403     # el mesero no factura
    assert api.get("ana", "/documentos").status_code == 403
    assert api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "recibo"}).status_code == 422
    assert api.get("cata", f"/pedidos/{pid}/documento").status_code == 404                          # aún no tiene documento
    assert falso.emisiones == []


# ── Venezuela · YeparFactura ─────────────────────────────────
@pytest.fixture()
def venezuela(db, api):
    empresa = api.s["empresa"]
    empresa.pais, empresa.moneda = "VE", "USD"
    db.commit()
    return api


def test_yeparfactura_solo_factura_con_tasa_de_cambio(db, venezuela, falso):
    api = venezuela
    assert conectar(api, proveedor="yeparfactura").status_code == 200
    pid = pedido_pagado(api)
    receptor = {"rut": "J-12345678-9", "nombre": "Inversiones Caribe C.A.", "direccion": "Caracas"}
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"})
    assert r.status_code == 422 and "no existe boleta" in r.json()["detalle"]
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": receptor})
    assert r.status_code == 422 and "tasa de cambio" in r.json()["detalle"] and falso.emisiones == []

    ok = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": receptor, "tasa_cambio": "36.5"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["proveedor"] == "yeparfactura" and ok.json()["folio"] == "00-1001"
    assert ok.json()["moneda"] == "USD" and ok.json()["tasa_cambio"] == "36.500000"
    cuerpo = falso.emisiones[0][3]
    assert cuerpo["moneda"] == "USD" and cuerpo["tasa_cambio"] == "36.5" and cuerpo["tipo"] == "factura"
    assert cuerpo["items"][0]["cantidad"] == 1 and cuerpo["idempotency_key"] == f"yrs-{pid}"


# ── Aislamiento ──────────────────────────────────────────────
def test_un_restaurante_no_factura_cuentas_de_otro(db, api, falso, otro_local, nuevo_usuario, cabeceras, cliente):
    from models import RolUsuario
    ajena, suc = otro_local
    admin_ajeno = nuevo_usuario(ajena, "Admin ajeno", roles=(RolUsuario.administrador,), sucursal_id=suc.id)
    conectar(api)
    pid = pedido_pagado(api)
    cab = cabeceras(admin_ajeno)
    assert cliente.put("/facturacion/conexion", json={"proveedor": "yepardte", "api_key": "otra-clave-999"}, headers=cab).status_code == 200
    r = cliente.post(f"/pedidos/{pid}/documento", json={"tipo": "boleta"}, headers=cab)
    assert r.status_code == 404
    assert cliente.get("/documentos", headers=cab).json() == []
