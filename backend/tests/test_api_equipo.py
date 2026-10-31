# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_equipo.py
# Sucursales, personal, contraseñas y el alta de un restaurante nuevo (de cero hasta iniciar sesión).
# ============================================================

import argparse

import pytest

from crear_restaurante import ejecutar
from models import Empresa, RolUsuario
from seguridad import encriptar_password


@pytest.fixture()
def api(db, cliente, cabeceras, local, u, nuevo_usuario):
    empresa, sucursal = local
    admin = nuevo_usuario(empresa, "Admin", roles=(RolUsuario.administrador,), sucursal_id=sucursal.id)
    admin.password_hash = encriptar_password("clave-actual-1")
    db.commit()
    personas = {"admin": admin, "ana": nuevo_usuario(empresa, "Ana", sucursal_id=sucursal.id)}

    class Api:
        s = sucursal

        def req(self, p, metodo, ruta, json=None):
            kw = {} if json is None else {"json": json}
            return getattr(cliente, metodo)(ruta, headers=cabeceras(personas[p]), **kw)

        def get(self, p, ruta):
            return self.req(p, "get", ruta)

        def post(self, p, ruta, json=None):
            return self.req(p, "post", ruta, json or {})

        def patch(self, p, ruta, json=None):
            return self.req(p, "patch", ruta, json or {})

    return Api()


def nueva(api, **extra):
    datos = {"nombre": "Beto", "username": "beto", "password": "segura-123", "roles": ["mesero"],
             "sucursal_id": api.s.id, **extra}
    return api.post("admin", "/personal", datos)


def test_crear_personal_con_su_puesto_y_entra_a_iniciar_sesion(db, cliente, api):
    r = nueva(api)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["roles"] == ["mesero"] and p["sucursal_id"] == api.s.id and p["activo"] and not p["tiene_pin"]
    codigo = db.get(Empresa, db.query(Empresa).first().id).codigo_acceso
    login = cliente.post("/auth/login", json={"codigo_empresa": codigo, "username": "beto", "password": "segura-123"})
    assert login.status_code == 200 and login.json()["usuario"]["roles"] == ["mesero"]


def test_reglas_del_puesto(db, api):
    assert nueva(api, password="corta").status_code == 422
    assert nueva(api, sucursal_id=None).status_code == 422                            # mesero sin local
    assert nueva(api, roles=["cocinero"]).status_code == 422                           # cocinero sin estación
    assert nueva(api, roles=["cajero"], estacion="cocina").status_code == 422        # estación solo del cocinero
    assert nueva(api, sucursal_id=9999).status_code == 404
    assert nueva(api, descuento_max_pct="150").status_code == 422
    assert nueva(api, roles=["inventado"]).status_code == 422
    assert nueva(api, roles=["cocinero"], estacion="barra").status_code == 201
    assert nueva(api, username="BETO").status_code == 422                              # usuario repetido (sin importar mayúsculas)
    ok = nueva(api, username="dani", nombre="Dani", roles=["cajero"], descuento_max_pct="12.5")
    assert ok.status_code == 201 and ok.json()["descuento_max_pct"] == "12.5"
    assert api.post("ana", "/personal", {}).status_code == 403
    assert api.get("ana", "/personal").status_code == 403


def test_cambiar_puesto_y_dar_de_baja_sin_perder_al_ultimo_admin(db, api):
    beto = nueva(api).json()
    r = api.patch("admin", f"/personal/{beto['id']}", {"roles": ["cajero", "mesero"], "descuento_max_pct": "10"})
    assert r.status_code == 200 and r.json()["roles"] == ["cajero", "mesero"] and r.json()["descuento_max_pct"] == "10.0"
    assert api.patch("admin", f"/personal/{beto['id']}", {"activo": False}).json()["activo"] is False
    admin_id = next(p["id"] for p in api.get("admin", "/personal").json() if p["username"] == "admin")
    r = api.patch("admin", f"/personal/{admin_id}", {"activo": False})
    assert r.status_code == 422 and "sin un administrador" in r.json()["detalle"]
    assert api.patch("admin", f"/personal/{admin_id}", {"roles": ["cajero"]}).status_code == 422
    # Con un segundo administrador sí se puede.
    otro = nueva(api, username="jefe", nombre="Jefe", roles=["administrador"], sucursal_id=None).json()
    assert api.patch("admin", "/personal/99999", {"nombre": "x"}).status_code == 404
    assert api.patch("admin", f"/personal/{admin_id}", {"roles": ["cajero"], "descuento_max_pct": "5"}).status_code == 200


def test_una_persona_dada_de_baja_ya_no_inicia_sesion(db, cliente, api):
    beto = nueva(api).json()
    api.patch("admin", f"/personal/{beto['id']}", {"activo": False})
    codigo = db.query(Empresa).first().codigo_acceso
    r = cliente.post("/auth/login", json={"codigo_empresa": codigo, "username": "beto", "password": "segura-123"})
    assert r.status_code == 401


def test_contrasenas(db, cliente, api):
    beto = nueva(api).json()
    assert api.post("admin", f"/personal/{beto['id']}/password", {"password": "nueva-clave-9"}).status_code == 204
    codigo = db.query(Empresa).first().codigo_acceso
    ok = cliente.post("/auth/login", json={"codigo_empresa": codigo, "username": "beto", "password": "nueva-clave-9"})
    assert ok.status_code == 200
    assert api.post("admin", f"/personal/{beto['id']}/password", {"password": "corta"}).status_code == 422
    # Cambio propio: exige la actual y una nueva distinta.
    assert api.post("admin", "/auth/cambiar-password", {"actual": "mala", "nueva": "otra-clave-77"}).status_code == 422
    assert api.post("admin", "/auth/cambiar-password", {"actual": "clave-actual-1", "nueva": "clave-actual-1"}).status_code == 422
    assert api.post("admin", "/auth/cambiar-password", {"actual": "clave-actual-1", "nueva": "otra-clave-77"}).status_code == 204
    r = cliente.post("/auth/login", json={"codigo_empresa": codigo, "username": "admin", "password": "otra-clave-77"})
    assert r.status_code == 200


def test_sucursales(db, api):
    assert [s["nombre"] for s in api.get("admin", "/sucursales").json()] == ["Casa matriz"]
    nueva_s = api.post("admin", "/sucursales", {"nombre": "Providencia"})
    assert nueva_s.status_code == 201
    assert api.post("admin", "/sucursales", {"nombre": "providencia"}).status_code == 422
    r = api.patch("admin", f"/sucursales/{nueva_s.json()['id']}", {"nombre": "Las Condes"})
    assert r.status_code == 200 and r.json()["nombre"] == "Las Condes"
    assert api.patch("admin", f"/sucursales/{nueva_s.json()['id']}", {"nombre": "Casa matriz"}).status_code == 422
    assert api.patch("admin", "/sucursales/9999", {"nombre": "x"}).status_code == 404
    assert api.post("ana", "/sucursales", {"nombre": "x"}).status_code == 403


def test_no_se_ve_ni_se_toca_el_personal_de_otra_empresa(db, api, otro_local, nuevo_usuario, cliente, cabeceras):
    ajeno = nuevo_usuario(otro_local[0], "Ajeno", roles=(RolUsuario.administrador,), sucursal_id=otro_local[1].id)
    h = cabeceras(ajeno)
    mio = nueva(api).json()
    assert cliente.patch(f"/personal/{mio['id']}", json={"activo": False}, headers=h).status_code == 404
    assert cliente.post(f"/personal/{mio['id']}/password", json={"password": "hackeada-123"}, headers=h).status_code == 404
    assert [p["username"] for p in cliente.get("/personal", headers=h).json()] == ["ajeno"]
    assert cliente.post("/personal", json={"nombre": "X", "username": "x", "password": "segura-123",
                                           "roles": ["mesero"], "sucursal_id": api.s.id}, headers=h).status_code == 404


def test_alta_de_un_restaurante_nuevo_de_cero_a_iniciar_sesion(db, cliente):
    args = argparse.Namespace(nombre="Pizzería Sur", sucursal="Centro", admin_nombre="Marta", admin_usuario="marta",
                              pais="cl", moneda="clp")
    codigo = ejecutar(db, args, "clave-super-1")
    assert len(codigo) == 8 and codigo.isalnum() and codigo == codigo.upper()
    r = cliente.post("/auth/login", json={"codigo_empresa": codigo.lower(), "username": "marta", "password": "clave-super-1"})
    assert r.status_code == 200 and r.json()["usuario"]["roles"] == ["administrador"]
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert [s["nombre"] for s in cliente.get("/sucursales", headers=h).json()] == ["Centro"]
    assert cliente.get("/unidades", headers=h).json() != []          # las unidades quedaron sembradas
    # El asistente de arranque parte con sucursal hecha y lo demás pendiente.
    a = cliente.get("/carga-masiva/asistente", headers=h).json()
    assert a["completados"] == 1 and a["siguiente"].startswith("Cargar insumos")      # solo la sucursal; el admin no cuenta como personal
