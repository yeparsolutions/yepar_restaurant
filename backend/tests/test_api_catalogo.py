# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_catalogo.py
# Pruebas por HTTP del catálogo: ítems, recetas, costos y extras.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

import pytest

from models import EstacionCocina, RolUsuario
from servicios.compras import ingresar_compra


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
        empresa_ = empresa
        sucursal_ = sucursal

        def como(self, persona, metodo, ruta, **kw):
            return getattr(cliente, metodo)(ruta, headers=cabeceras(personas[persona]), **kw)

        def get(self, persona, ruta, **kw):
            return self.como(persona, "get", ruta, **kw)

        def post(self, persona, ruta, json=None, **kw):
            return self.como(persona, "post", ruta, json=json or {}, **kw)

        def put(self, persona, ruta, json=None, **kw):
            return self.como(persona, "put", ruta, json=json or {}, **kw)

        def patch(self, persona, ruta, json=None, **kw):
            return self.como(persona, "patch", ruta, json=json or {}, **kw)

    return Api()


def crear(api, tipo, nombre, unidad, **extra):
    r = api.post("admin", "/items", {"tipo": tipo, "nombre": nombre, "unidad_base": unidad, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def armar_carta(api, db):
    """Una hamburguesa con salsa de ajo (componente), con costos cargados por compras."""
    pan = crear(api, "materia_prima", "Pan", "und")
    carne = crear(api, "materia_prima", "Carne", "g")
    cebolla = crear(api, "materia_prima", "Cebolla", "g")
    mayo = crear(api, "materia_prima", "Mayonesa", "g")
    ajo = crear(api, "materia_prima", "Ajo", "g")
    salsa = crear(api, "componente", "Salsa de ajo", "g")
    burger = crear(api, "vendible_preparado", "Hamburguesa", "und", precio_venta="6500", estacion="cocina")
    for item, costo in ((pan, "300"), (carne, "8"), (cebolla, "1"), (mayo, "3"), (ajo, "10")):
        ingresar_compra(db, empresa_id=api.empresa_.id, sucursal_id=api.sucursal_.id, item_id=item["id"],
                        cantidad=1000, costo_unitario_base=costo)
    db.commit()
    r = api.put("admin", f"/items/{salsa['id']}/receta",
                {"rendimiento": "1", "rendimiento_unidad": "kg",
                 "lineas": [{"ingrediente_id": mayo["id"], "cantidad": "900"},
                            {"ingrediente_id": ajo["id"], "cantidad": "0.1", "unidad": "kg"}]})
    assert r.status_code == 200, r.text
    r = api.put("admin", f"/items/{burger['id']}/receta",
                {"rendimiento": "1", "instrucciones": "Sellar 3 min por lado.",
                 "lineas": [{"ingrediente_id": pan["id"], "cantidad": "1"},
                            {"ingrediente_id": carne["id"], "cantidad": "150"},
                            {"ingrediente_id": salsa["id"], "cantidad": "20"},
                            {"ingrediente_id": cebolla["id"], "cantidad": "30", "es_removible": True}]})
    assert r.status_code == 200, r.text
    return dict(pan=pan, carne=carne, cebolla=cebolla, mayo=mayo, ajo=ajo, salsa=salsa, burger=burger)


# ── Unidades, categorías e ítems ─────────────────────────────
def test_cualquier_usuario_ve_el_catalogo_de_unidades(db, u, api):
    r = api.get("ana", "/unidades")
    assert r.status_code == 200
    codigos = {x["codigo"]: x for x in r.json()}
    assert set(codigos) >= {"g", "kg", "ml", "l", "cc", "und"} and codigos["kg"]["es_base"] is False


def test_el_administrador_arma_el_catalogo(db, u, api):
    cat = api.post("admin", "/categorias", {"nombre": "Congelados", "orden": 1})
    assert cat.status_code == 201
    item = crear(api, "materia_prima", "Papas", "g", categoria_id=cat.json()["id"], stock_minimo="2000")
    assert item["unidad_base"] == "g" and item["stock_minimo"] == "2000.000" and item["costo_referencia"] == "0.000000"
    assert item["activo"] is True and item["tiene_receta"] is False
    assert api.get("admin", f"/items/{item['id']}").json()["nombre"] == "Papas"
    assert [i["nombre"] for i in api.get("admin", "/items?q=pap").json()] == ["Papas"]
    assert api.get("admin", "/items?tipo=componente").json() == []


def test_editar_y_desactivar_un_item(db, u, api):
    plato = crear(api, "vendible_preparado", "Pizza", "und", precio_venta="9000", estacion="cocina")
    r = api.patch("admin", f"/items/{plato['id']}", {"precio_venta": "9900", "activo": False})
    assert r.status_code == 200 and r.json()["precio_venta"] == "9900.00" and r.json()["activo"] is False
    assert api.get("admin", "/items").json() == []                                          # desaparece de la lista...
    assert len(api.get("admin", "/items?incluir_inactivos=true").json()) == 1               # ...pero no se pierde
    # El tipo y la unidad no son editables: la API rechaza el campo.
    assert api.patch("admin", f"/items/{plato['id']}", {"tipo": "componente"}).status_code == 422


def test_errores_del_catalogo_con_su_codigo_http(db, u, api):
    crear(api, "materia_prima", "Tomate", "g")
    r = api.post("admin", "/items", {"tipo": "materia_prima", "nombre": "tomate", "unidad_base": "g"})
    assert r.status_code == 422 and "Ya existe un ítem" in r.json()["detalle"]
    r = api.post("admin", "/items", {"tipo": "materia_prima", "nombre": "Sal", "unidad_base": "kg"})
    assert r.status_code == 422 and "no es una unidad base" in r.json()["detalle"]
    assert api.post("admin", "/items", {"tipo": "raro", "nombre": "X", "unidad_base": "g"}).status_code == 422
    assert api.get("admin", "/items/99999").status_code == 404


def test_presentaciones_y_extras(db, u, api):
    cola = crear(api, "vendible_reventa", "Cola", "und", precio_venta="1500", estacion="barra")
    p = api.post("admin", f"/items/{cola['id']}/presentaciones",
                 {"nombre": "Caja 12 un", "cantidad_en_base": "12", "es_defecto": True})
    assert p.status_code == 201 and p.json()["cantidad_en_base"] == "12.000" and p.json()["es_defecto"] is True
    tocineta = crear(api, "materia_prima", "Tocineta", "g")
    burger = crear(api, "vendible_preparado", "Hamburguesa", "und", precio_venta="6500")
    e = api.post("admin", "/extras", {"nombre": "Extra tocineta", "precio": "1000", "ingrediente_id": tocineta["id"],
                                     "cantidad": "25", "aplica_a_todos": False, "plato_ids": [burger["id"]]})
    assert e.status_code == 201
    assert e.json()["precio"] == "1000.00" and e.json()["plato_ids"] == [burger["id"]]
    assert [x["nombre"] for x in api.get("admin", "/extras").json()] == ["Extra tocineta"]


# ── Recetas y costos ─────────────────────────────────────────
def test_recetas_con_unidades_convertidas_y_costo_del_plato(db, u, api):
    c = armar_carta(api, db)
    receta = api.get("admin", f"/items/{c['salsa']['id']}/receta").json()
    assert receta["rendimiento"] == "1000.000" and receta["unidad"] == "g"           # 1 kg → 1000 g
    assert [(l["nombre"], l["cantidad"]) for l in receta["lineas"]] == [("Mayonesa", "900.000"), ("Ajo", "100.000")]

    costo = api.get("admin", f"/items/{c['burger']['id']}/costo").json()
    assert costo["costo_total"] == "1604.00" and costo["costo_unitario"] == "1604.000000"
    assert costo["precio_venta"] == "6500.00" and costo["margen_pct"] == "75.3"       # (6.500 − 1.604) / 6.500
    assert {l["nombre"]: l["costo_linea"] for l in costo["lineas"]}["Salsa de ajo"] == "74.00"

    sin = api.get("admin", f"/items/{c['burger']['id']}/costo?sin={c['cebolla']['id']}").json()
    assert sin["costo_total"] == "1574.00"
    # Quitar algo que no es removible: error de negocio.
    r = api.get("admin", f"/items/{c['burger']['id']}/costo?sin={c['carne']['id']}")
    assert r.status_code == 422 and "no son removibles" in r.json()["detalle"]


def test_el_cocinero_ve_la_receta_pero_no_los_costos(db, u, api):
    c = armar_carta(api, db)
    r = api.get("chef", f"/items/{c['burger']['id']}/receta")
    assert r.status_code == 200 and r.json()["instrucciones"] == "Sellar 3 min por lado."
    assert [l["es_removible"] for l in r.json()["lineas"]] == [False, False, False, True]
    assert api.get("chef", f"/items/{c['burger']['id']}/costo").status_code == 403
    assert api.put("chef", f"/items/{c['burger']['id']}/receta", {"rendimiento": "1", "lineas": []}).status_code == 403


def test_receta_invalida_y_ciclos_dan_422(db, u, api):
    c = armar_carta(api, db)
    # La salsa ya es ingrediente de la hamburguesa; hacer que la salsa use a la hamburguesa no se puede.
    r = api.put("admin", f"/items/{c['salsa']['id']}/receta",
                {"rendimiento": "1000", "lineas": [{"ingrediente_id": c["burger"]["id"], "cantidad": "1"}]})
    assert r.status_code == 422 and "no puede ser ingrediente" in r.json()["detalle"]
    r = api.put("admin", f"/items/{c['salsa']['id']}/receta",
                {"rendimiento": "1000", "lineas": [{"ingrediente_id": c["salsa"]["id"], "cantidad": "1"}]})
    assert r.status_code == 422 and "de sí mismo" in r.json()["detalle"]
    r = api.put("admin", f"/items/{c['salsa']['id']}/receta",
                {"rendimiento": "1000", "lineas": [{"ingrediente_id": c["ajo"]["id"], "cantidad": "1", "unidad": "l"}]})
    assert r.status_code == 422 and "familias distintas" in r.json()["detalle"]
    r = api.get("admin", f"/items/{c['pan']['id']}/receta")
    assert r.status_code == 422 and "no tiene receta" in r.json()["detalle"]


def test_reemplazar_una_receta_por_http(db, u, api):
    c = armar_carta(api, db)
    r = api.put("admin", f"/items/{c['salsa']['id']}/receta",
                {"rendimiento": "2", "rendimiento_unidad": "kg",
                 "lineas": [{"ingrediente_id": c["mayo"]["id"], "cantidad": "1.8", "unidad": "kg"},
                            {"ingrediente_id": c["ajo"]["id"], "cantidad": "200"}]})
    assert r.status_code == 200 and r.json()["rendimiento"] == "2000.000"
    assert [l["cantidad"] for l in r.json()["lineas"]] == ["1800.000", "200.000"]


# ── Permisos y aislamiento ───────────────────────────────────
def test_solo_el_administrador_toca_el_catalogo(db, u, api):
    for persona in ("ana", "chef"):
        assert api.post(persona, "/items", {"tipo": "materia_prima", "nombre": "X", "unidad_base": "g"}).status_code == 403
        assert api.get(persona, "/items").status_code == 403
        assert api.post(persona, "/extras", {}).status_code == 403
    assert api.get("ana", "/categorias").status_code == 403
    assert api.get("chef", "/categorias").status_code == 200                       # el cocinero ve categorías


def test_un_restaurante_no_ve_el_catalogo_de_otro(db, u, api, otro_local, nuevo_usuario, cabeceras, cliente):
    ajena, sucursal_ajena = otro_local
    admin_ajeno = nuevo_usuario(ajena, "Admin ajeno", roles=(RolUsuario.administrador,), sucursal_id=sucursal_ajena.id)
    item = crear(api, "materia_prima", "Secreto", "g")
    cab = cabeceras(admin_ajeno)
    assert cliente.get("/items", headers=cab).json() == []
    assert cliente.get(f"/items/{item['id']}", headers=cab).status_code == 404
    assert cliente.patch(f"/items/{item['id']}", json={"nombre": "Robado"}, headers=cab).status_code == 404
    r = cliente.post("/items", json={"tipo": "materia_prima", "nombre": "Secreto", "unidad_base": "g"}, headers=cab)
    assert r.status_code == 201                                                     # su propio "Secreto": no choca
