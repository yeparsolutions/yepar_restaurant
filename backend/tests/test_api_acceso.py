# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_acceso.py
# Entrar sin escribir el código del restaurante: el administrador con su correo, y las tablets vinculadas
# una vez con un enlace (después el personal solo toca su nombre).
# ============================================================

import pytest

from models import Empresa, RolUsuario
from routers import registro
from seguridad import encriptar_password


@pytest.fixture(autouse=True)
def _sin_historial_de_altas():
    registro._intentos.clear()
    yield
    registro._intentos.clear()


@pytest.fixture()
def api(db, cliente, cabeceras, local, nuevo_usuario):
    empresa, sucursal = local
    admin = nuevo_usuario(empresa, "Admin", roles=(RolUsuario.administrador,), sucursal_id=sucursal.id)
    admin.password_hash = encriptar_password("clave-admin-1")
    ana = nuevo_usuario(empresa, "Ana", sucursal_id=sucursal.id)
    ana.password_hash = encriptar_password("clave-ana-123")
    db.commit()

    class Api:
        def como(self, persona, metodo, ruta, **kw):
            return getattr(cliente, metodo)(ruta, headers=cabeceras({"admin": admin, "ana": ana}[persona]), **kw)

    return Api()


def registrar(cliente, correo="dueno@demo.cl", clave="clave-segura-1"):
    return cliente.post("/registro", json={"nombre_restaurante": "Demo", "admin_nombre": "Dueño", "email": correo,
                                           "password": clave})


# ── Correo ───────────────────────────────────────────────────
def test_el_administrador_entra_con_correo_sin_codigo(cliente):
    assert registrar(cliente).status_code == 201
    r = cliente.post("/auth/login", json={"email": "  DUENO@demo.CL ", "password": "clave-segura-1"})
    assert r.status_code == 200 and r.json()["usuario"]["roles"] == ["administrador"]


def test_correo_o_clave_malos_dan_el_mismo_mensaje(cliente):
    registrar(cliente)
    for datos in ({"email": "dueno@demo.cl", "password": "mala"}, {"email": "otro@demo.cl", "password": "clave-segura-1"}):
        r = cliente.post("/auth/login", json=datos)
        assert r.status_code == 401 and r.json()["detail"] == "Correo o contraseña incorrectos."


def test_un_correo_no_se_puede_repetir_ni_siquiera_en_otro_restaurante(db, cliente):
    assert registrar(cliente).status_code == 201
    r = registrar(cliente, correo="DUENO@demo.cl")
    assert r.status_code == 422 and "ya está registrado" in r.json()["detalle"]
    assert db.query(Empresa).count() == 1                                    # no quedó un restaurante a medias


def test_correo_invalido_se_rechaza(cliente):
    for malo in ("sin-arroba", "a@b", "con espacio@x.cl"):
        assert registrar(cliente, correo=malo).status_code == 422


def test_login_sin_ninguna_forma_completa_se_rechaza(cliente):
    assert cliente.post("/auth/login", json={"password": "x"}).status_code == 422
    assert cliente.post("/auth/login", json={"username": "ana", "password": "x"}).status_code == 422   # falta código o enlace


def test_cada_persona_puede_registrar_su_correo_con_su_clave(db, cliente, api):
    assert api.como("admin", "post", "/auth/correo", json={"email": "admin@demo.cl", "password": "mala"}).status_code == 401
    assert api.como("admin", "post", "/auth/correo", json={"email": "admin@demo.cl", "password": "clave-admin-1"}).status_code == 200
    assert cliente.post("/auth/login", json={"email": "admin@demo.cl", "password": "clave-admin-1"}).status_code == 200
    # Otra persona no puede quedarse con el mismo correo.
    r = api.como("ana", "post", "/auth/correo", json={"email": "ADMIN@demo.cl", "password": "clave-ana-123"})
    assert r.status_code == 422


# ── Vinculación de tablets ───────────────────────────────────
def vincular(api):
    r = api.como("admin", "post", "/acceso/vinculo")
    assert r.status_code == 201
    return r.json()["token"]


def test_la_tablet_vinculada_lista_al_personal_y_este_entra_sin_codigo(cliente, api):
    token = vincular(api)
    r = cliente.get(f"/acceso/vinculo/{token}")                                       # público: lo abre la tablet
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["restaurante"] and [p["username"] for p in cuerpo["personal"]] == ["ana"]   # el admin no aparece
    login = cliente.post("/auth/login", json={"vinculo": token, "username": "ana", "password": "clave-ana-123"})
    assert login.status_code == 200 and login.json()["usuario"]["nombre"] == "Ana"
    mala = cliente.post("/auth/login", json={"vinculo": token, "username": "ana", "password": "incorrecta"})
    assert mala.status_code == 401 and mala.json()["detail"] == "Nombre o contraseña incorrectos."


def test_solo_el_administrador_genera_el_enlace(api):
    assert api.como("ana", "post", "/acceso/vinculo").status_code == 403
    assert api.como("ana", "delete", "/acceso/vinculos").status_code == 403


def test_desvincular_invalida_todos_los_enlaces_y_tablets(cliente, api):
    viejo = vincular(api)
    assert api.como("admin", "delete", "/acceso/vinculos").status_code == 204
    assert cliente.get(f"/acceso/vinculo/{viejo}").status_code == 404
    assert cliente.post("/auth/login", json={"vinculo": viejo, "username": "ana", "password": "clave-ana-123"}).status_code == 401
    nuevo = vincular(api)                                                             # uno nuevo sí funciona
    assert nuevo != viejo and cliente.get(f"/acceso/vinculo/{nuevo}").status_code == 200


def test_un_enlace_inventado_o_de_otro_tipo_no_sirve(cliente, api):
    assert cliente.get("/acceso/vinculo/inventado").status_code == 404
    # Un token de sesión (firmado con la misma clave) no vale como enlace de tablet.
    sesion = cliente.post("/auth/login", json={"codigo_empresa": "DEMO0001", "username": "ana", "password": "clave-ana-123"})
    assert sesion.status_code == 200
    assert cliente.get(f"/acceso/vinculo/{sesion.json()['access_token']}").status_code == 404


def test_el_enlace_de_un_restaurante_no_deja_entrar_a_gente_de_otro(db, cliente, api, otro_local, nuevo_usuario):
    pedro = nuevo_usuario(otro_local[0], "Pedro", sucursal_id=otro_local[1].id)
    pedro.password_hash = encriptar_password("clave-pedro-1")
    db.commit()
    token = vincular(api)                                                             # enlace del restaurante DEMO
    r = cliente.post("/auth/login", json={"vinculo": token, "username": pedro.username, "password": "clave-pedro-1"})
    assert r.status_code == 401
