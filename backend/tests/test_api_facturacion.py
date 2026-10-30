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
        ruta = request.url.path
        if ruta.endswith("/ping") or ruta.endswith("/verificar"):
            clave = request.headers.get("x-api-key")
            if clave == "clave-mala-123":
                return httpx.Response(401, json={"detail": "API Key inválida"})
            return httpx.Response(200, json={"ok": True})
        if self.guion:
            r = self.guion.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        if ruta == "/v1/documentos":                                   # YeparFactura (Venezuela)
            return self._yeparfactura(cuerpo)
        return self._yepardte(cuerpo)                                  # YeparDTE (Chile)

    def _folio(self, clave):
        return self.clave_a_folio.setdefault(clave, 1001 + len(self.clave_a_folio))

    def _yepardte(self, c):
        folio = self._folio(c["idempotency_key"])
        total = sum(round(i["precio"] * i["qty"] * (1 - i.get("descuento", 0) / 100)) for i in c["items"])
        neto = round(total / 1.19)
        doc = {"id": "d1", "folio": folio, "numero": str(folio), "neto": neto, "iva": total - neto, "total": total,
               "pdf_url": f"https://pdf.test/{folio}"}
        return httpx.Response(200, json={"ok": True, "documento": doc})

    def _yeparfactura(self, c):
        folio = self._folio(c["request_id"])
        neto = sum(float(i["precio_unitario"]) * float(i["cantidad"]) - float(i["descuento"]) for i in c["items"])
        tasa = 36.5
        return httpx.Response(201, json={
            "documento_id": "abc", "tipo": "factura", "estado": "emitido", "numeracion_consecutiva": folio,
            "numero_control": f"00-{folio:08d}", "idempotente": False, "moneda": c["moneda"],
            "monto_neto": round(neto * tasa, 2), "monto_iva": round(neto * tasa * 0.16, 2),
            "monto_total": round(neto * tasa * 1.16, 2), "tasa_cambio": tasa, "monto_total_divisa": round(neto * 1.16, 2)})

    @property
    def emisiones(self):
        return [l for l in self.llamadas if l[1].endswith("/emitir") or l[1] == "/v1/documentos"]


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


def pedido_pagado_mesa2(api):
    """Una hamburguesa en la mesa 2 (Beto), pagada por transferencia: $6.500."""
    pedido = api.post("beto", "/pedidos", {"mesa_id": api.s["m2"].id}).json()
    l = api.post("beto", f"/pedidos/{pedido['id']}/lineas", {"item_id": api.s["burger"].id}).json()["linea"]
    api.post("beto", f"/pedidos/{pedido['id']}/enviar")
    api.post("chef", f"/cocina/lineas/{l['id']}/iniciar")
    api.post("chef", f"/cocina/lineas/{l['id']}/lista")
    api.post("beto", f"/pedidos/{pedido['id']}/cuenta")
    assert api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "transferencia", "monto": "6500", "numero_operacion": "TR-2"}).status_code == 201
    return pedido["id"]


def conectar(api, proveedor="yepardte", persona="admin", clave="clave-buena-123"):
    return api.put(persona, "/facturacion/conexion", {"proveedor": proveedor, "api_key": clave})


# ── Conexión ─────────────────────────────────────────────────
def test_conectar_yepardte_valida_y_guarda_la_clave_cifrada(db, api, falso):
    r = conectar(api)
    assert r.status_code == 200, r.text
    assert r.json() == {"proveedor": "yepardte", "activo": True, "api_key_final": "••••-123",    # solo los últimos 4
                        "emision_automatica": False, "tipo_automatico": "boleta"}
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
    # Contrato real de YeparDTE: pesos enteros y el descuento (10%) como PORCENTAJE por línea.
    assert cuerpo["items"] == [{"nombre": "Hamburguesa", "precio": 7500, "qty": 1, "descuento": 10},
                               {"nombre": "Hamburguesa", "precio": 6500, "qty": 1, "descuento": 10}]
    assert d["total"] == "12600.00"                                  # 14.000 − 10%; la propina NO se factura

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
    assert all("descuento" not in i for i in falso.emisiones[0][3]["items"])       # sin descuento: líneas tal cual


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


def test_yeparfactura_factura_sin_iva_y_con_la_tasa_de_yeparfactura(db, venezuela, falso):
    api = venezuela
    assert conectar(api, proveedor="yeparfactura").status_code == 200
    assert falso.llamadas[0][1] == "/v1/cuentas/verificar"
    pid = pedido_pagado(api)
    receptor = {"rut": "J-12345678-9", "nombre": "Inversiones Caribe C.A.", "direccion": "Caracas", "email": "a@b.ve"}
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"})
    assert r.status_code == 422 and "no existe boleta" in r.json()["detalle"]

    ok = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": receptor})
    assert ok.status_code == 201, ok.text
    d = ok.json()
    assert d["proveedor"] == "yeparfactura" and d["folio"] == "00-00001001" and d["moneda"] == "USD"
    # YeparFactura congela la tasa y devuelve los montos en bolívares y el total en la divisa original.
    assert d["moneda_montos"] == "VES" and d["tasa_cambio"] == "36.500000"
    assert abs(float(d["total_divisa"]) - 12600.0) <= 0.02          # 14.000 − 10%; convertir IVA incluido→neto puede mover 1 centavo

    _, ruta, cabeceras, c = falso.emisiones[0]
    assert ruta == "/v1/documentos" and cabeceras["x-api-key"] == "clave-buena-123"
    assert c["request_id"] == f"yrs-{pid}" and c["tipo"] == "factura" and c["moneda"] == "USD" and "tasa_cambio" not in c
    assert (c["receptor_rif"], c["receptor_razon_social"], c["receptor_correo"]) == ("J-12345678-9", "Inversiones Caribe C.A.", "a@b.ve")
    assert c["forma_pago"] == "transferencia" and c["condicion_pago"] == "contado"
    # Los precios van SIN IVA (los de la carta lo incluyen: 7.500 / 1,16) y con alícuota general.
    assert [(i["precio_unitario"], i["alicuota"], i["descuento"]) for i in c["items"]] == [
        ("6465.517241", "16", "646.55"), ("5603.448276", "16", "560.34")]


def test_factura_venezolana_a_una_persona_con_cedula_y_rechazos_de_yeparfactura(db, venezuela, falso):
    api = venezuela
    conectar(api, proveedor="yeparfactura")
    pid = pedido_pagado(api, con_descuento=False)
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": {"nombre": "Ana Pérez"}})
    assert r.status_code == 422 and "rut" in r.json()["detalle"]
    # Sin tasa BCV hoy, YeparFactura responde 422: no es transitorio, queda rechazado para reintentar a mano.
    falso.guion = [httpx.Response(422, json={"detail": "No hay tasa BCV disponible para USD en este momento."})]
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": {"nombre": "Ana Pérez", "cedula": "V-12345678"}})
    assert r.status_code == 422 and "tasa BCV" in r.json()["detail"]
    assert falso.emisiones[0][3]["receptor_cedula_pasaporte"] == "V-12345678" and "receptor_rif" not in falso.emisiones[0][3]
    ok = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": {"nombre": "Ana Pérez", "cedula": "V-12345678"}})
    assert ok.status_code == 201 and ok.json()["intentos"] == 2
    # La imprenta que no responde (502) sí es transitoria.
    pid2 = pedido_pagado_mesa2(api)
    falso.guion = [httpx.Response(502, json={"detail": "La imprenta no respondió"})]
    r = api.post("cata", f"/pedidos/{pid2}/documento", {"tipo": "factura", "receptor": {"nombre": "X", "rut": "J-1"}})
    assert r.status_code == 202


def test_moneda_no_soportada_por_yeparfactura(db, venezuela, falso):
    venezuela.s["empresa"].moneda = "COP"
    db.commit()
    conectar(venezuela, proveedor="yeparfactura")
    pid = pedido_pagado(venezuela, con_descuento=False)
    r = venezuela.post("cata", f"/pedidos/{pid}/documento", {"tipo": "factura", "receptor": {"nombre": "X", "rut": "J-1"}})
    assert r.status_code == 422 and "VES, USD, EUR" in r.json()["detail"]


# ── Detalles del contrato de YeparDTE ────────────────────────
def test_yepardte_responde_400_incluso_en_fallos_internos(db, api, falso):
    """YeparDTE nunca responde 5xx (Cloudflare lo oculta): un fallo interno viene como 400 con http_original."""
    conectar(api)
    pid = pedido_pagado(api)
    falso.guion = [httpx.Response(400, json={"detail": {"error_real": "TimeoutError: SII", "http_original": 502}})]
    assert api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"}).status_code == 202      # transitorio
    falso.guion = [httpx.Response(402, json={"detail": "Límite de folios alcanzado."})]
    r = api.post("cata", f"/pedidos/{pid}/documento", {"tipo": "boleta"})                            # plan sin folios: permanente
    assert r.status_code == 422 and "Límite de folios" in r.json()["detail"]


def test_descuento_que_no_es_porcentaje_entero_va_en_una_sola_linea(db, api, falso):
    from servicios.facturacion.yepardte import items_yepardte
    from decimal import Decimal as D
    items = [{"nombre": "Pizza", "cantidad": 2, "precio_unitario": D("9000.00"), "descuento": D("1234.00")},
             {"nombre": "Cola", "cantidad": 1, "precio_unitario": D("1500.50"), "descuento": D("0.00")},
             {"nombre": "Agua", "cantidad": 3, "precio_unitario": D("1000.00"), "descuento": D("300.00")}]
    assert items_yepardte(items) == [
        {"nombre": "Pizza x2", "precio": 16766, "qty": 1},            # 18.000 − 1.234, exacto al peso
        {"nombre": "Cola", "precio": 1501, "qty": 1},                 # precio con decimales: una línea
        {"nombre": "Agua", "precio": 1000, "qty": 3, "descuento": 10}]


# ── Emisión automática al cobrar ─────────────────────────────
def test_emision_automatica_de_la_boleta_al_cerrar_la_mesa(db, api, falso):
    conectar(api)
    c = api.put("admin", "/facturacion/configuracion", {"emision_automatica": True})
    assert c.status_code == 200 and c.json()["emision_automatica"] is True and c.json()["tipo_automatico"] == "boleta"
    assert api.put("cata", "/facturacion/configuracion", {"emision_automatica": False}).status_code == 403
    assert api.put("admin", "/facturacion/configuracion", {"tipo_automatico": "factura"}).status_code == 422

    pedido = api.post("ana", "/pedidos", {"mesa_id": api.s["m1"].id}).json()
    l = api.post("ana", f"/pedidos/{pedido['id']}/lineas", {"item_id": api.s["burger"].id}).json()["linea"]
    api.post("ana", f"/pedidos/{pedido['id']}/enviar")
    api.post("chef", f"/cocina/lineas/{l['id']}/iniciar")
    api.post("chef", f"/cocina/lineas/{l['id']}/lista")
    api.post("ana", f"/pedidos/{pedido['id']}/cuenta")
    parcial = api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "transferencia", "monto": "2000", "numero_operacion": "T1"})
    assert parcial.json()["documento_estado"] is None and falso.emisiones == []            # aún no está pagada
    final = api.post("cata", f"/pedidos/{pedido['id']}/pagos", {"medio": "transferencia", "monto": "4500", "numero_operacion": "T2"})
    assert final.status_code == 201 and final.json()["pedido_estado"] == "cerrado"
    assert final.json()["documento_estado"] == "emitido" and final.json()["documento_folio"] == "1001"
    assert api.get("cata", f"/pedidos/{pedido['id']}/documento").json()["tipo"] == "boleta"


def test_si_la_factura_falla_el_cobro_igual_queda_hecho(db, api, falso):
    conectar(api)
    api.put("admin", "/facturacion/configuracion", {"emision_automatica": True})
    falso.guion = [httpx.ConnectError("sin red")]
    pid = pedido_pagado(api)                                                                # el cobro NO se cae
    doc = api.get("cata", f"/pedidos/{pid}/documento").json()
    assert doc["estado"] == "pendiente"
    assert api.get("ana", f"/pedidos/{pid}").json()["estado"] == "cerrado"
    assert api.post("cata", "/documentos/reintentar").json()[0]["estado"] == "emitido"


def test_en_venezuela_no_hay_emision_automatica(db, venezuela, falso):
    conectar(venezuela, proveedor="yeparfactura")
    r = venezuela.put("admin", "/facturacion/configuracion", {"emision_automatica": True})
    assert r.status_code == 422 and "Venezuela" in r.json()["detalle"]


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
