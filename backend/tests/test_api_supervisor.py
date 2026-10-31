# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_supervisor.py
# PIN de supervisor: autoriza descuentos sobre el tope del cajero, con bloqueo por intentos fallidos.
# ============================================================

import pytest

from models import Pedido, RolUsuario
from seguridad import encriptar_password
from tests.test_api_caja import api, mesa_con_cuenta  # noqa: F401  (reutiliza el cobro de ejemplo)

CLAVE = "clave-del-admin"


@pytest.fixture()
def con_pin(db, api):
    """El administrador con contraseña real y su PIN 4821 ya definido."""
    api.s["admin"].password_hash = encriptar_password(CLAVE)
    db.commit()
    r = api.como("admin", "put", "/supervisor/pin", json={"pin": "4821", "password": CLAVE})
    assert r.status_code == 204, r.text
    return api


def descuento(api, pedido, pct, pin=None, sup=None, persona="cata"):
    cuerpo = {"porcentaje": pct}
    if sup is not None:
        cuerpo["supervisor_id"] = sup
    if pin is not None:
        cuerpo["pin_supervisor"] = pin
    return api.post(persona, f"/pedidos/{pedido['id']}/descuento", cuerpo)


def test_cajera_pasa_su_tope_con_el_pin_y_queda_quien_autorizo(db, con_pin):
    api = con_pin
    pedido = mesa_con_cuenta(api)
    r = descuento(api, pedido, "20")
    assert r.status_code == 422 and "PIN de un supervisor" in r.json()["detalle"]
    r = descuento(api, pedido, "20", pin="4821", sup=api.s["admin"].id)
    assert r.status_code == 200 and r.json()["cuenta"]["descuento"] == "1300.00"
    p = db.get(Pedido, pedido["id"])
    assert p.descuento_por_id == api.s["cata"].id and p.descuento_autorizado_por_id == api.s["admin"].id
    # Bajar al tope ya no necesita supervisor y borra la autorización anterior.
    r = descuento(api, pedido, "10")
    assert r.status_code == 200 and db.get(Pedido, pedido["id"]).descuento_autorizado_por_id is None


def test_dentro_del_tope_no_pide_pin(db, con_pin):
    pedido = mesa_con_cuenta(con_pin)
    assert descuento(con_pin, pedido, "10").status_code == 200


def test_pin_incorrecto_y_bloqueo_tras_cinco_fallos(db, con_pin):
    api = con_pin
    pedido = mesa_con_cuenta(api)
    sup = api.s["admin"].id
    for _ in range(4):
        r = descuento(api, pedido, "20", pin="0000", sup=sup)
        assert r.status_code == 422 and r.json()["detalle"] == "PIN incorrecto."
    assert descuento(api, pedido, "20", pin="9999", sup=sup).json()["detalle"] == "PIN incorrecto."   # 5.º fallo
    # Ahora hasta el PIN correcto queda bloqueado.
    r = descuento(api, pedido, "20", pin="4821", sup=sup)
    assert r.status_code == 422 and "bloqueado" in r.json()["detalle"]
    assert db.get(Pedido, pedido["id"]).descuento_autorizado_por_id is None


def test_los_fallos_se_guardan_aunque_la_peticion_falle(db, con_pin):
    api = con_pin
    pedido = mesa_con_cuenta(api)
    descuento(api, pedido, "20", pin="0000", sup=api.s["admin"].id)
    db.refresh(api.s["admin"])
    assert api.s["admin"].pin_fallos == 1
    # Un acierto reinicia el contador.
    assert descuento(api, pedido, "20", pin="4821", sup=api.s["admin"].id).status_code == 200
    db.refresh(api.s["admin"])
    assert api.s["admin"].pin_fallos == 0


def test_solo_vale_el_pin_de_un_administrador_de_la_misma_empresa(db, con_pin):
    api = con_pin
    pedido = mesa_con_cuenta(api)
    # La cajera no es supervisora aunque se le ponga un hash de PIN.
    api.s["otra_cajera"].pin_hash = encriptar_password("4821")
    db.commit()
    r = descuento(api, pedido, "20", pin="4821", sup=api.s["otra_cajera"].id)
    assert r.status_code == 422 and "no existe o no tiene PIN" in r.json()["detalle"]
    assert descuento(api, pedido, "20", pin="4821", sup=99999).status_code == 422
    # Un supervisor inactivo deja de valer.
    api.s["admin"].activo = False
    db.commit()
    assert descuento(api, pedido, "20", pin="4821", sup=api.s["admin"].id).status_code in (401, 422)


def test_definir_pin_reglas(db, api):
    api.s["admin"].password_hash = encriptar_password(CLAVE)
    db.commit()
    def poner(pin, clave=CLAVE, persona="admin"):
        return api.como(persona, "put", "/supervisor/pin", json={"pin": pin, "password": clave})
    assert poner("4821", "mala").status_code == 422
    assert poner("1234").status_code == 422 and poner("7777").status_code == 422     # fáciles de adivinar
    assert poner("48a1").status_code == 422 and poner("12").status_code == 422
    assert poner("4821", persona="cata").status_code == 403
    assert api.get("cata", "/supervisores").json() == []
    assert poner("482195").status_code == 204
    assert api.get("cata", "/supervisores").json() == [{"id": api.s["admin"].id, "nombre": "Admin"}]
    assert api.get("ana", "/supervisores").status_code == 403
    assert api.como("admin", "delete", "/supervisor/pin").status_code == 204
    assert api.get("cata", "/supervisores").json() == []


def test_el_pin_no_se_guarda_en_claro(db, con_pin):
    h = con_pin.s["admin"].pin_hash
    assert h and "4821" not in h and h.startswith("$2")
