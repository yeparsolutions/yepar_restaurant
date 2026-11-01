# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_sync.py
# Sincronización de la tablet: lo hecho sin conexión sube en orden, sin duplicarse.
# ============================================================

import uuid

import pytest

from models import RolUsuario
from tests.test_api_salon import api  # noqa: F401  (reutiliza el salón de ejemplo)


def uid():
    return str(uuid.uuid4())


def op(tipo, **datos):
    return {"op_id": uid(), "tipo": tipo, "datos": datos}


def subir(api, persona, ops):
    r = api.post(persona, "/sync/operaciones", {"operaciones": ops})
    assert r.status_code == 200, r.text
    return r.json()


def test_una_noche_sin_internet_sube_completa_y_en_orden(api):
    pedido, linea = uid(), uid()
    ops = [
        op("abrir_pedido", pedido_id=pedido, mesa_id=api.s["m1"].id, comensales=2),
        op("tomar_linea", pedido_id=pedido, linea_id=linea, item_id=api.s["burger"].id, cantidad=2),
        op("enviar", pedido_id=pedido),
        op("pedir_cuenta", pedido_id=pedido),
    ]
    r = subir(api, "ana", ops)
    assert r["aplicadas"] == 4 and r["rechazadas"] == 0
    p = api.get("ana", f"/pedidos/{pedido}").json()
    assert p["estado"] == "cuenta_pedida" and p["lineas"][0]["id"] == linea
    assert [c["plato"] for c in api.get("chef", "/cocina/comandas").json()] == ["Hamburguesa"]


def test_reenviar_la_misma_operacion_no_duplica(api):
    pedido = uid()
    ops = [op("abrir_pedido", pedido_id=pedido, mesa_id=api.s["m1"].id)]
    assert subir(api, "ana", ops)["aplicadas"] == 1
    r = subir(api, "ana", ops)                          # se cortó la respuesta y la tablet reintenta
    assert r["resultados"][0]["repetida"] is True and r["resultados"][0]["estado"] == "aplicada"
    assert len(api.get("ana", "/mesas").json()) == 2


def test_una_rechazada_no_frena_las_demas_y_queda_registrada(api):
    pedido, otro = uid(), uid()
    malas = op("tomar_linea", pedido_id=uid(), item_id=api.s["burger"].id)       # pedido que no existe
    ops = [op("abrir_pedido", pedido_id=pedido, mesa_id=api.s["m1"].id), malas,
           op("abrir_pedido", pedido_id=otro, mesa_id=api.s["m1"].id),            # mesa ya ocupada
           op("tomar_linea", pedido_id=pedido, item_id=api.s["cola"].id)]
    r = subir(api, "ana", ops)
    estados = [x["estado"] for x in r["resultados"]]
    assert estados == ["aplicada", "rechazada", "rechazada", "aplicada"]
    assert "ocupada" in r["resultados"][2]["error"]
    # Reintentar la rechazada devuelve el mismo motivo, sin volver a intentarlo.
    r2 = subir(api, "ana", [malas])
    assert r2["resultados"][0]["repetida"] is True and r2["resultados"][0]["estado"] == "rechazada"
    assert len(api.get("ana", f"/pedidos/{pedido}").json()["lineas"]) == 1


def test_datos_invalidos_se_rechazan_con_motivo(api):
    r = subir(api, "ana", [op("enviar", pedido_id="corto"), op("quitar_linea"),
                           op("abrir_pedido", mesa_id=api.s["m1"].id)])        # sin pedido_id
    assert [x["estado"] for x in r["resultados"]] == ["rechazada"] * 3
    assert "pedido_id" in r["resultados"][0]["error"]


def test_operacion_rechazada_a_medias_no_deja_basura(api):
    pedido = uid()
    subir(api, "ana", [op("abrir_pedido", pedido_id=pedido, mesa_id=api.s["m1"].id)])
    r = subir(api, "ana", [op("enviar", pedido_id=pedido)])          # no hay platos tomados
    assert r["rechazadas"] == 1 and "No hay platos" in r["resultados"][0]["error"]
    assert api.get("chef", "/cocina/comandas").json() == []


def test_no_toca_mesas_de_otro_mesero_ni_de_otra_empresa(api, db, nuevo_usuario, otro_local):
    pedido = uid()
    subir(api, "ana", [op("abrir_pedido", pedido_id=pedido, mesa_id=api.s["m1"].id)])
    r = subir(api, "beto", [op("tomar_linea", pedido_id=pedido, item_id=api.s["cola"].id)])
    assert r["resultados"][0]["estado"] == "rechazada" and "otro mesero" in r["resultados"][0]["error"]
    ajeno = nuevo_usuario(otro_local[0], "Ajeno", sucursal_id=otro_local[1].id)
    api.s["ajeno"] = ajeno
    r = subir(api, "ajeno", [op("anular_pedido", pedido_id=pedido)])
    assert r["resultados"][0]["estado"] == "rechazada"
    assert api.get("ana", f"/pedidos/{pedido}").json()["estado"] == "abierto"


def test_permisos_y_limites(api):
    assert api.post("chef", "/sync/operaciones", {"operaciones": [op("enviar", pedido_id=uid())]}).status_code == 403
    assert api.post("ana", "/sync/operaciones", {"operaciones": []}).status_code == 422
    assert api.post("ana", "/sync/operaciones", {"operaciones": [op("inventar")]}).status_code == 422
