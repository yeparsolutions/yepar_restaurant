# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_recepcion.py
# Recepción física a ciegas (factura → conteo del cocinero → stock) e inventario físico ciego.
# ============================================================

import pytest

from models import EstacionCocina, RolUsuario


@pytest.fixture()
def api(db, cliente, cabeceras, local, u, nuevo_usuario, otro_local):
    empresa, sucursal = local
    personas = {
        "admin": nuevo_usuario(empresa, "Admin", roles=(RolUsuario.administrador,), sucursal_id=sucursal.id),
        "chef": nuevo_usuario(empresa, "Chef", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.cocina,
                              sucursal_id=sucursal.id),
        "ana": nuevo_usuario(empresa, "Ana", sucursal_id=sucursal.id),
    }
    otra_empresa = otro_local[0]
    personas["ajeno"] = nuevo_usuario(otra_empresa, "Ajeno", roles=(RolUsuario.administrador,),
                                      sucursal_id=otro_local[1].id)

    class Api:
        def req(self, persona, metodo, ruta, json=None):
            kw = {} if json is None else {"json": json}
            return getattr(cliente, metodo)(ruta, headers=cabeceras(personas[persona]), **kw)

        def get(self, persona, ruta):
            return self.req(persona, "get", ruta)

        def post(self, persona, ruta, json=None):
            return self.req(persona, "post", ruta, json or {})

    return Api()


def item(api, tipo, nombre, unidad, **extra):
    r = api.post("admin", "/items", {"tipo": tipo, "nombre": nombre, "unidad_base": unidad, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def stock_de(api, it):
    filas = api.get("admin", "/inventario/stock").json()
    return next((f for f in filas if f["item_id"] == it["id"]), None)


def factura(api, lineas, **kw):
    r = api.post("admin", "/compras", {"proveedor": "Distribuidora Sur", "numero_documento": "F-100",
                                       "lineas": lineas, **kw})
    assert r.status_code == 201, r.text
    return r.json()


# ── Recepción ────────────────────────────────────────────────
def test_registrar_factura_no_sube_stock(db, u, api):
    tomate = item(api, "materia_prima", "Tomate", "g")
    c = factura(api, [{"item_id": tomate["id"], "cantidad": "5", "unidad": "kg", "monto_neto": "7500"}])
    assert c["estado"] == "por_recibir"
    assert c["lineas"][0]["cantidad_facturada"] == "5000.000"
    assert c["lineas"][0]["costo_unitario_base"] == "1.500000"
    fila = stock_de(api, tomate)
    assert fila is None or fila["fisico"] == "0.000"


def test_cocinero_ve_hoja_ciega_y_recibe_lo_contado(db, u, api):
    tomate = item(api, "materia_prima", "Tomate", "g")
    c = factura(api, [{"item_id": tomate["id"], "cantidad": "5", "unidad": "kg", "monto_neto": "7500"}])
    espera = api.get("chef", "/compras/por-recibir").json()
    assert [e["id"] for e in espera] == [c["id"]]
    hoja = api.get("chef", f"/compras/{c['id']}/recepcion")
    assert hoja.status_code == 200
    texto = hoja.text
    assert "cantidad_facturada" not in texto and "costo" not in texto and "monto" not in texto
    linea = hoja.json()["lineas"][0]
    # Llegaron solo 4 kg de los 5 facturados.
    r = api.post("chef", f"/compras/{c['id']}/recibir",
                 {"lineas": [{"linea_id": linea["linea_id"], "cantidad": "4", "unidad": "kg"}]})
    assert r.status_code == 200, r.text
    assert "cantidad_facturada" not in r.text and r.json()["estado"] == "recibida"
    assert stock_de(api, tomate)["fisico"] == "4000.000"
    # El admin sí ve la diferencia.
    d = api.get("admin", f"/compras/{c['id']}").json()["lineas"][0]
    assert d["cantidad_facturada"] == "5000.000" and d["cantidad_recibida"] == "4000.000"
    assert d["diferencia"] == "-1000.000"


def test_no_se_recibe_dos_veces_ni_se_deja_linea_sin_contar(db, u, api):
    a = item(api, "materia_prima", "Harina", "g")
    b = item(api, "materia_prima", "Sal", "g")
    c = factura(api, [{"item_id": a["id"], "cantidad": "1000", "monto_neto": "1000"},
                      {"item_id": b["id"], "cantidad": "500", "monto_neto": "500"}])
    la, lb = c["lineas"]
    r = api.post("chef", f"/compras/{c['id']}/recibir", {"lineas": [{"linea_id": la["id"], "cantidad": "1000"}]})
    assert r.status_code == 422 and "Sal" in r.json()["detalle"]
    ok = {"lineas": [{"linea_id": la["id"], "cantidad": "1000"}, {"linea_id": lb["id"], "cantidad": "0"}]}
    assert api.post("chef", f"/compras/{c['id']}/recibir", ok).status_code == 200
    assert stock_de(api, b) is None or stock_de(api, b)["fisico"] == "0.000"
    assert api.post("chef", f"/compras/{c['id']}/recibir", ok).status_code == 422


def test_factura_duplicada_repetida_y_no_comprable(db, u, api):
    a = item(api, "materia_prima", "Harina", "g")
    salsa = item(api, "componente", "Salsa", "g")
    factura(api, [{"item_id": a["id"], "cantidad": "10", "costo_unitario_base": "1"}])
    r = api.post("admin", "/compras", {"proveedor": "Distribuidora Sur", "numero_documento": "F-100",
                                       "lineas": [{"item_id": a["id"], "cantidad": "1", "costo_unitario_base": "1"}]})
    assert r.status_code == 422 and "ya está registrada" in r.json()["detalle"]
    r = api.post("admin", "/compras", {"proveedor": "X", "lineas": [
        {"item_id": a["id"], "cantidad": "1", "costo_unitario_base": "1"},
        {"item_id": a["id"], "cantidad": "2", "costo_unitario_base": "1"}]})
    assert r.status_code == 422 and "repetido" in r.json()["detalle"]
    r = api.post("admin", "/compras", {"proveedor": "X", "lineas": [
        {"item_id": salsa["id"], "cantidad": "1", "costo_unitario_base": "1"}]})
    assert r.status_code == 422 and "no se compra" in r.json()["detalle"]


def test_anular_y_permisos_y_aislamiento(db, u, api):
    a = item(api, "materia_prima", "Harina", "g")
    c = factura(api, [{"item_id": a["id"], "cantidad": "10", "costo_unitario_base": "1"}])
    assert api.post("chef", "/compras", {"proveedor": "X", "lineas": []}).status_code == 403
    assert api.get("chef", f"/compras/{c['id']}").status_code == 403
    assert api.get("ana", "/compras/por-recibir").status_code == 403
    assert api.get("ajeno", f"/compras/{c['id']}").status_code == 404
    assert api.get("ajeno", f"/compras/{c['id']}/recepcion").status_code == 404
    assert api.post("admin", f"/compras/{c['id']}/anular").json()["estado"] == "anulada"
    r = api.post("chef", f"/compras/{c['id']}/recibir", {"lineas": [{"linea_id": c["lineas"][0]["id"], "cantidad": "1"}]})
    assert r.status_code == 422
    assert api.post("admin", f"/compras/{c['id']}/anular").status_code == 422


# ── Inventario físico ciego ──────────────────────────────────
def con_stock(api, nombre, cantidad, unidad="g", costo="2"):
    it = item(api, "materia_prima", nombre, unidad)
    r = api.post("admin", "/inventario/compras", {"item_id": it["id"], "cantidad": cantidad,
                                                  "costo_unitario_base": costo})
    assert r.status_code == 201, r.text
    return it


def test_inventario_ciego_flujo_completo(db, u, api):
    harina = con_stock(api, "Harina", "1000")
    sal = con_stock(api, "Sal", "500")
    inv = api.post("admin", "/inventario-fisico", {})
    assert inv.status_code == 201, inv.text
    inv = inv.json()
    assert inv["estado"] == "contando" and inv["total_items"] == 2
    # Ya hay uno en curso.
    assert api.post("admin", "/inventario-fisico", {}).status_code == 422
    hoja = api.get("chef", "/inventario-fisico/activo")
    assert hoja.status_code == 200
    assert "cantidad_sistema" not in hoja.text and "costo" not in hoja.text
    # No se puede cerrar el conteo con ítems sin contar.
    r = api.post("chef", f"/inventario-fisico/{inv['id']}/finalizar-conteo")
    assert r.status_code == 422 and "Faltan 2" in r.json()["detalle"]
    assert api.post("chef", f"/inventario-fisico/{inv['id']}/contar",
                    {"item_id": harina["id"], "cantidad": "0.9", "unidad": "kg"}).status_code == 200
    r = api.post("chef", f"/inventario-fisico/{inv['id']}/contar", {"item_id": sal["id"], "cantidad": "500"})
    assert r.json()["contados"] == 2
    assert api.post("chef", f"/inventario-fisico/{inv['id']}/finalizar-conteo").json()["estado"] == "en_revision"
    # El cocinero no ve la revisión; el admin sí.
    assert api.get("chef", f"/inventario-fisico/{inv['id']}/revision").status_code == 403
    rev = api.get("admin", f"/inventario-fisico/{inv['id']}/revision").json()
    por_nombre = {l["item"]: l for l in rev["lineas"]}
    assert por_nombre["Harina"]["cantidad_sistema"] == "1000.000" and por_nombre["Harina"]["diferencia"] == "-100.000"
    assert por_nombre["Harina"]["valor_diferencia"] == "-200.00" and por_nombre["Sal"]["diferencia"] == "0.000"
    assert rev["con_diferencia"] == 1 and rev["valor_total_diferencia"] == "-200.00"
    # Recuento de la harina: vuelve a contando y se cuenta de nuevo.
    r = api.post("admin", f"/inventario-fisico/{inv['id']}/recontar", {"item_ids": [harina["id"]]})
    assert r.json()["estado"] == "contando" and r.json()["contados"] == 1
    api.post("chef", f"/inventario-fisico/{inv['id']}/contar", {"item_id": harina["id"], "cantidad": "950"})
    api.post("chef", f"/inventario-fisico/{inv['id']}/finalizar-conteo")
    c = api.post("admin", f"/inventario-fisico/{inv['id']}/cerrar").json()
    assert c["estado"] == "cerrado" and c["ajustes"] == 1
    assert stock_de(api, harina)["fisico"] == "950.000"
    assert stock_de(api, sal)["fisico"] == "500.000"
    movs = [m for m in db.execute(__import__("sqlalchemy").text(
        "select tipo, referencia_tipo, cantidad from movimientos_stock where tipo='ajuste_inventario'"))]
    assert len(movs) == 1 and movs[0][1] == "inventario_fisico"
    # Se puede abrir otro.
    assert api.post("admin", "/inventario-fisico", {}).status_code == 201


def test_cierre_conserva_ventas_hechas_durante_el_conteo(db, u, api):
    harina = con_stock(api, "Harina", "1000")
    inv = api.post("admin", "/inventario-fisico", {}).json()
    # Mientras se cuenta, sale merma de 100 (el sistema pasa a 900).
    r = api.post("admin", "/inventario/mermas", {"item_id": harina["id"], "cantidad": "100", "motivo": "danado"})
    assert r.status_code == 201, r.text
    # El cocinero contó 900 (ya sin esos 100): no hay diferencia real… pero la foto decía 1000 → delta −100.
    api.post("chef", f"/inventario-fisico/{inv['id']}/contar", {"item_id": harina["id"], "cantidad": "850"})
    api.post("chef", f"/inventario-fisico/{inv['id']}/finalizar-conteo")
    api.post("admin", f"/inventario-fisico/{inv['id']}/cerrar")
    # 900 (sistema) + (850 − 1000) = 750: las salidas del conteo se conservan.
    assert stock_de(api, harina)["fisico"] == "750.000"


def test_cancelar_no_toca_stock_y_reglas(db, u, api):
    harina = con_stock(api, "Harina", "1000")
    inv = api.post("admin", "/inventario-fisico", {}).json()
    api.post("chef", f"/inventario-fisico/{inv['id']}/contar", {"item_id": harina["id"], "cantidad": "1"})
    assert api.post("admin", f"/inventario-fisico/{inv['id']}/cerrar").status_code == 422   # aún no está en revisión
    assert api.post("chef", f"/inventario-fisico/{inv['id']}/contar",
                    {"item_id": harina["id"], "cantidad": "-1"}).status_code == 422
    assert api.post("chef", f"/inventario-fisico/{inv['id']}/contar", {"item_id": 9999, "cantidad": "1"}).status_code == 404
    assert api.post("ajeno", f"/inventario-fisico/{inv['id']}/cancelar").status_code == 404
    assert api.post("ana", f"/inventario-fisico/{inv['id']}/contar", {"item_id": harina["id"], "cantidad": "1"}).status_code == 403
    assert api.post("admin", f"/inventario-fisico/{inv['id']}/cancelar").json()["estado"] == "cancelado"
    assert stock_de(api, harina)["fisico"] == "1000.000"
    assert api.get("chef", "/inventario-fisico/activo").status_code == 404
    assert api.post("admin", f"/inventario-fisico/{inv['id']}/cancelar").status_code == 422


def test_inventario_por_categoria(db, u, api):
    cat = api.post("admin", "/categorias", {"nombre": "Secos"})
    assert cat.status_code == 201, cat.text
    cid = cat.json()["id"]
    item(api, "materia_prima", "Arroz", "g", categoria_id=cid)
    item(api, "materia_prima", "Pollo", "g")
    inv = api.post("admin", "/inventario-fisico", {"categoria_id": cid}).json()
    assert inv["total_items"] == 1
    api.post("admin", f"/inventario-fisico/{inv['id']}/cancelar")
    assert api.post("admin", "/inventario-fisico", {"categoria_id": 9999}).status_code == 422
