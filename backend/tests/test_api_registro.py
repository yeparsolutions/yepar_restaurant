# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_registro.py
# Registro público: el dueño crea su restaurante desde la web y queda con la sesión iniciada.
# ============================================================

import pytest

from models import Empresa, Unidad
from routers import registro

DATOS = {"nombre_restaurante": "Hamburguesería Demo", "admin_nombre": "Alberto", "admin_usuario": "alberto",
         "password": "clave-segura-1"}


@pytest.fixture(autouse=True)
def _reiniciar_ritmo(monkeypatch):
    registro._intentos.clear()                 # cada prueba parte sin historial de altas
    monkeypatch.delenv("REGISTRO_ABIERTO", raising=False)
    yield
    registro._intentos.clear()


def test_registro_crea_todo_y_deja_la_sesion_iniciada(db, cliente):
    r = cliente.post("/registro", json=DATOS)
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert len(cuerpo["codigo_acceso"]) == 8 and cuerpo["usuario"]["roles"] == ["administrador"]
    assert db.query(Empresa).count() == 1 and db.query(Unidad).count() > 0          # sembró las unidades
    # El token que devolvió ya sirve, y el login normal también.
    yo = cliente.get("/auth/yo", headers={"Authorization": f"Bearer {cuerpo['access_token']}"})
    assert yo.status_code == 200 and yo.json()["nombre"] == "Alberto"
    login = cliente.post("/auth/login", json={"codigo_empresa": cuerpo["codigo_acceso"], "username": "alberto",
                                              "password": "clave-segura-1"})
    assert login.status_code == 200


def test_contrasena_corta_se_rechaza_y_no_deja_restos(db, cliente):
    r = cliente.post("/registro", json={**DATOS, "password": "corta"})
    assert r.status_code == 422
    assert db.query(Empresa).count() == 0


def test_campos_desconocidos_se_rechazan(cliente):
    assert cliente.post("/registro", json={**DATOS, "es_superadmin": True}).status_code == 422


def test_registro_cerrado_por_el_interruptor(cliente, monkeypatch):
    monkeypatch.setenv("REGISTRO_ABIERTO", "0")
    assert cliente.get("/registro/estado").json() == {"abierto": False}
    assert cliente.post("/registro", json=DATOS).status_code == 403


def test_tope_de_altas_por_hora_y_por_direccion(cliente, monkeypatch):
    monkeypatch.setenv("REGISTRO_MAX_POR_HORA", "2")
    for i in range(2):
        assert cliente.post("/registro", json={**DATOS, "admin_usuario": f"dueno{i}"}).status_code == 201
    assert cliente.post("/registro", json={**DATOS, "admin_usuario": "dueno9"}).status_code == 429
    # Otra dirección distinta no está bloqueada.
    otra = cliente.post("/registro", json={**DATOS, "admin_usuario": "dueno9"},
                        headers={"x-forwarded-for": "203.0.113.7"})
    assert otra.status_code == 201
