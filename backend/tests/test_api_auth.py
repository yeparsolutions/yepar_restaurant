# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_auth.py
# Pruebas del inicio de sesión y del control de acceso por rol.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

from models import RolUsuario
from seguridad import crear_token, encriptar_password


def crear_con_clave(db, nuevo_usuario, empresa, nombre, clave, **extra):
    usuario = nuevo_usuario(empresa, nombre, **extra)
    usuario.password_hash = encriptar_password(clave)
    db.commit()
    return usuario


def login(cliente, **datos):
    base = {"codigo_empresa": "DEMO0001", "username": "ana", "password": "secreta123"}
    base.update(datos)
    return cliente.post("/auth/login", json=base)


def test_login_correcto_devuelve_token_y_datos_de_la_persona(db, cliente, local, nuevo_usuario):
    empresa, sucursal = local
    crear_con_clave(db, nuevo_usuario, empresa, "Ana", "secreta123", sucursal_id=sucursal.id)
    r = login(cliente)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["token_type"] == "bearer" and cuerpo["access_token"]
    assert cuerpo["usuario"] == {"id": cuerpo["usuario"]["id"], "nombre": "Ana", "roles": ["mesero"],
                                 "estacion": None, "sucursal_id": sucursal.id}


def test_el_codigo_de_empresa_no_distingue_mayusculas(db, cliente, local, nuevo_usuario):
    crear_con_clave(db, nuevo_usuario, local[0], "Ana", "secreta123")
    assert login(cliente, codigo_empresa="demo0001").status_code == 200


def test_credenciales_incorrectas_dan_el_mismo_mensaje(db, cliente, local, nuevo_usuario):
    crear_con_clave(db, nuevo_usuario, local[0], "Ana", "secreta123")
    for datos in ({"password": "mala"}, {"username": "nadie"}, {"codigo_empresa": "NOEXISTE"}):
        r = login(cliente, **datos)
        assert r.status_code == 401
        assert r.json()["detail"] == "Código, usuario o contraseña incorrectos."


def test_un_usuario_desactivado_no_entra(db, cliente, local, nuevo_usuario):
    ana = crear_con_clave(db, nuevo_usuario, local[0], "Ana", "secreta123")
    ana.activo = False
    db.commit()
    assert login(cliente).status_code == 401


def test_el_mismo_usuario_en_dos_restaurantes_no_se_mezcla(db, cliente, local, otro_local, nuevo_usuario):
    crear_con_clave(db, nuevo_usuario, local[0], "Ana", "clave-del-demo")
    crear_con_clave(db, nuevo_usuario, otro_local[0], "Ana", "clave-de-la-pizzeria")
    assert login(cliente, password="clave-del-demo").status_code == 200
    assert login(cliente, password="clave-de-la-pizzeria").status_code == 401           # clave del otro local
    assert login(cliente, codigo_empresa="AJENA001", password="clave-de-la-pizzeria").status_code == 200


def test_login_rechaza_campos_de_mas_o_faltantes(cliente):
    assert cliente.post("/auth/login", json={"codigo_empresa": "X", "username": "a"}).status_code == 422
    assert cliente.post("/auth/login", json={"codigo_empresa": "X", "username": "a", "password": "b",
                                             "admin": True}).status_code == 422


def test_yo_devuelve_la_sesion_actual(db, cliente, cabeceras, local, nuevo_usuario):
    ana = nuevo_usuario(local[0], "Ana")
    r = cliente.get("/auth/yo", headers=cabeceras(ana))
    assert r.status_code == 200 and r.json()["nombre"] == "Ana"


def test_sin_token_o_con_token_malo_es_401(db, cliente, cabeceras, local, nuevo_usuario):
    ana = nuevo_usuario(local[0], "Ana")
    assert cliente.get("/auth/yo").status_code == 401
    assert cliente.get("/auth/yo", headers={"Authorization": "Bearer basura"}).status_code == 401
    adulterado = crear_token(ana)[:-3] + "xyz"
    assert cliente.get("/auth/yo", headers={"Authorization": f"Bearer {adulterado}"}).status_code == 401


def test_quien_fue_desactivado_pierde_el_acceso_aunque_su_token_siga_vigente(db, cliente, cabeceras, local,
                                                                              nuevo_usuario):
    ana = nuevo_usuario(local[0], "Ana")
    cab = cabeceras(ana)
    assert cliente.get("/auth/yo", headers=cab).status_code == 200
    ana.activo = False
    db.commit()
    assert cliente.get("/auth/yo", headers=cab).status_code == 401


def test_el_rol_decide_a_que_puerta_entra(db, cliente, cabeceras, local, nuevo_usuario):
    e, _ = local
    cajero = nuevo_usuario(e, "Cata", roles=(RolUsuario.cajero,))
    chef = nuevo_usuario(e, "Chef", roles=(RolUsuario.cocinero,))
    admin = nuevo_usuario(e, "Admin", roles=(RolUsuario.administrador,))
    assert cliente.get("/cocina/comandas?sucursal_id=1", headers=cabeceras(cajero)).status_code == 403
    assert cliente.get("/cocina/comandas?sucursal_id=1", headers=cabeceras(chef)).status_code == 200
    assert cliente.get("/cocina/comandas?sucursal_id=1", headers=cabeceras(admin)).status_code == 200   # admin entra a todo
    assert cliente.get("/carta?sucursal_id=1", headers=cabeceras(chef)).status_code == 403


def test_salud_no_pide_sesion(cliente):
    assert cliente.get("/salud").json() == {"estado": "ok"}
