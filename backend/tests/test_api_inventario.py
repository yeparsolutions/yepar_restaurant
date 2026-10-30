# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_inventario.py
# Pruebas por HTTP de compras, producción, mermas, stock y alertas.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

import pytest

from models import EstacionCocina, RolUsuario


@pytest.fixture()
def api(db, cliente, cabeceras, local, u, nuevo_usuario):
    empresa, sucursal = local
    personas = {
        "admin": nuevo_usuario(empresa, "Admin", roles=(RolUsuario.administrador,), sucursal_id=sucursal.id),
        "chef": nuevo_usuario(empresa, "Chef", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.cocina,
                              sucursal_id=sucursal.id),
        "ana": nuevo_usuario(empresa, "Ana", sucursal_id=sucursal.id),
    }

    class Api:
        def req(self, persona, metodo, ruta, json=None):
            kw = {} if json is None else {"json": json}
            return getattr(cliente, metodo)(ruta, headers=cabeceras(personas[persona]), **kw)

        def get(self, persona, ruta):
            return self.req(persona, "get", ruta)

        def post(self, persona, ruta, json=None):
            return self.req(persona, "post", ruta, json or {})

        def put(self, persona, ruta, json=None):
            return self.req(persona, "put", ruta, json or {})

    return Api()


def crear(api, tipo, nombre, unidad, **extra):
    r = api.post("admin", "/items", {"tipo": tipo, "nombre": nombre, "unidad_base": unidad, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def comprar(api, item, cantidad, **kw):
    r = api.post("admin", "/inventario/compras", {"item_id": item["id"], "cantidad": cantidad, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_compra_por_kilos_sube_gramos_y_recalcula_costo(db, u, api):
    tomate = crear(api, "materia_prima", "Tomate", "g")
    c = comprar(api, tomate, "1", unidad="kg", monto_neto="1500")
    assert c["cantidad_base"] == "1000.000" and c["stock_nuevo"] == "1000.000"
    assert c["costo_unitario_base"] == "1.500000" and c["costo_referencia"] == "1.500000"
    c2 = comprar(api, tomate, "1", unidad="kg", monto_neto="1800")
    assert c2["costo_promedio"] == "1.650000" and c2["costo_referencia"] == "1.800000"
    assert c2["stock_nuevo"] == "2000.000"


def test_compra_por_presentacion(db, u, api):
    cola = crear(api, "vendible_reventa", "Cola", "und", precio_venta="1500", estacion="barra")
    p = api.post("admin", f"/items/{cola['id']}/presentaciones", {"nombre": "Caja 12", "cantidad_en_base": "12"}).json()
    c = comprar(api, cola, "3", presentacion_id=p["id"], monto_neto="36000")
    assert c["cantidad_base"] == "36.000" and c["costo_unitario_base"] == "1000.000000"


def test_errores_de_compra(db, u, api):
    salsa = crear(api, "componente", "Salsa", "g")
    r = api.post("admin", "/inventario/compras", {"item_id": salsa["id"], "cantidad": "1", "costo_unitario_base": "5"})
    assert r.status_code == 422 and "no se compra" in r.json()["detalle"]
    tomate = crear(api, "materia_prima", "Tomate", "g")
    r = api.post("admin", "/inventario/compras", {"item_id": tomate["id"], "cantidad": "1"})
    assert r.status_code == 422 and "uno solo" in r.json()["detalle"]
    r = api.post("admin", "/inventario/compras", {"item_id": 9999, "cantidad": "1", "costo_unitario_base": "1"})
    assert r.status_code in (404, 422)


def test_produccion_gasta_insumos_y_suma_el_componente(db, u, api):
    mayo = crear(api, "materia_prima", "Mayonesa", "g")
    ajo = crear(api, "materia_prima", "Ajo", "g")
    salsa = crear(api, "componente", "Salsa de ajo", "g")
    comprar(api, mayo, "1", unidad="kg", costo_unitario_base="3")
    comprar(api, ajo, "200", costo_unitario_base="10")
    r = api.put("admin", f"/items/{salsa['id']}/receta", {"rendimiento": "1000", "lineas": [
        {"ingrediente_id": mayo["id"], "cantidad": "900"}, {"ingrediente_id": ajo["id"], "cantidad": "100"}]})
    assert r.status_code == 200

    p = api.post("chef", "/inventario/produccion", {"item_id": salsa["id"]})        # el cocinero produce
    assert p.status_code == 201, p.text
    assert p.json()["cantidad_producida"] == "1000.000" and p.json()["costo_total"] == "3700.00"
    assert p.json()["costo_unitario"] == "3.700000" and p.json()["faltantes"] == []
    stock = {s["nombre"]: s["fisico"] for s in api.get("chef", "/inventario/stock").json()}
    assert stock == {"Mayonesa": "100.000", "Ajo": "100.000", "Salsa de ajo": "1000.000"}

    # Producir medio lote gasta la mitad; si falta un insumo solo avisa.
    p2 = api.post("chef", "/inventario/produccion", {"item_id": salsa["id"], "cantidad_producida": "1000"}).json()
    assert p2["faltantes"] == ["Mayonesa"] or "Mayonesa" in p2["faltantes"]
    assert api.post("chef", "/inventario/produccion", {"item_id": mayo["id"]}).status_code == 422


def test_mermas_restan_stock_y_quedan_en_el_libro(db, u, api):
    leche = crear(api, "materia_prima", "Leche", "ml")
    comprar(api, leche, "2", unidad="l", costo_unitario_base="1")
    r = api.post("chef", "/inventario/mermas", {"item_id": leche["id"], "cantidad": "250", "motivo": "vencido", "nota": "caja abierta"})
    assert r.status_code == 201
    assert r.json()["cantidad"] == "-250.000" and r.json()["stock_nuevo"] == "1750.000" and r.json()["motivo_merma"] == "vencido"
    libro = api.get("admin", f"/inventario/movimientos?item_id={leche['id']}").json()
    assert [m["tipo"] for m in libro] == ["merma", "compra"]
    assert api.post("chef", "/inventario/mermas", {"item_id": leche["id"], "cantidad": "0", "motivo": "vencido"}).status_code == 422
    assert api.post("chef", "/inventario/mermas", {"item_id": leche["id"], "cantidad": "5", "motivo": "robo"}).status_code == 422
    assert api.post("chef", "/inventario/mermas",
                    {"item_id": leche["id"], "cantidad": "5", "motivo": "cancelacion_en_preparacion"}).status_code == 422


def test_no_se_mermea_un_plato(db, u, api):
    plato = crear(api, "vendible_preparado", "Pizza", "und", precio_venta="9000", estacion="cocina")
    r = api.post("chef", "/inventario/mermas", {"item_id": plato["id"], "cantidad": "1", "motivo": "danado"})
    assert r.status_code == 422 and "ingredientes" in r.json()["detalle"]


def test_alertas_y_lista_de_compras(db, u, api):
    cola = crear(api, "vendible_reventa", "Cola", "und", precio_venta="1500", estacion="barra", stock_minimo="24")
    harina = crear(api, "materia_prima", "Harina", "g", stock_minimo="5000")
    api.post("admin", f"/items/{cola['id']}/presentaciones", {"nombre": "Caja 12", "cantidad_en_base": "12", "es_defecto": True})
    comprar(api, cola, "10", costo_unitario_base="800")
    comprar(api, harina, "10", unidad="kg", costo_unitario_base="1")

    alertas = api.get("chef", "/inventario/alertas").json()
    assert [(a["nombre"], a["disponible"]) for a in alertas] == [("Cola", "10.000")]
    lista = api.get("admin", "/inventario/lista-compras").json()
    assert len(lista["lineas"]) == 1
    linea = lista["lineas"][0]
    assert linea["cantidad_base"] == "38.000" and linea["presentacion"] == "Caja 12" and linea["cantidad_presentacion"] == 4
    assert linea["costo_estimado"] == "30400.00" and lista["costo_total_estimado"] == "30400.00"
    assert [s["nombre"] for s in api.get("admin", "/inventario/stock?solo_bajo_minimo=true").json()] == ["Cola"]


def test_permisos_del_inventario(db, u, api):
    tomate = crear(api, "materia_prima", "Tomate", "g")
    compra = {"item_id": tomate["id"], "cantidad": "1", "costo_unitario_base": "1"}
    assert api.post("chef", "/inventario/compras", compra).status_code == 403            # comprar: solo admin
    assert api.get("chef", "/inventario/lista-compras").status_code == 403
    assert api.get("chef", "/inventario/movimientos").status_code == 403
    for ruta in ("/inventario/stock", "/inventario/alertas", "/inventario/lista-compras"):
        assert api.get("ana", ruta).status_code == 403                                     # el mesero no ve inventario
    assert api.post("ana", "/inventario/mermas", {"item_id": tomate["id"], "cantidad": "1", "motivo": "vencido"}).status_code == 403


def test_aislamiento_entre_restaurantes(db, u, api, otro_local, nuevo_usuario, cabeceras, cliente):
    ajena, suc = otro_local
    admin_ajeno = nuevo_usuario(ajena, "Admin ajeno", roles=(RolUsuario.administrador,), sucursal_id=suc.id)
    tomate = crear(api, "materia_prima", "Tomate", "g")
    comprar(api, tomate, "1", unidad="kg", costo_unitario_base="1")
    cab = cabeceras(admin_ajeno)
    assert cliente.get("/inventario/stock", headers=cab).json() == []
    r = cliente.post("/inventario/compras", json={"item_id": tomate["id"], "cantidad": "1", "costo_unitario_base": "1"}, headers=cab)
    assert r.status_code in (404, 422)
    assert cliente.get(f"/inventario/movimientos?item_id={tomate['id']}", headers=cab).status_code in (404, 422)
