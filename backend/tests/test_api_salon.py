# ============================================================
# YEPAR RESTAURANT — backend/tests/test_api_salon.py
# Pruebas de punta a punta por HTTP: mesero, cocina y barra.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

import pytest

from models import EstacionCocina, RolUsuario


@pytest.fixture()
def api(db, cliente, cabeceras, salon, nuevo_usuario):
    """Salón de ejemplo + cocinero y barman + una forma cómoda de llamar a la API como cada persona."""
    e = salon["empresa"]
    salon["chef"] = nuevo_usuario(e, "Chef", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.cocina)
    salon["barman"] = nuevo_usuario(e, "Barman", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.barra)
    salon["admin"] = nuevo_usuario(e, "Admin", roles=(RolUsuario.administrador,))
    salon["cajera"] = nuevo_usuario(e, "Cata", roles=(RolUsuario.cajero,))
    for persona in ("ana", "beto", "chef", "barman", "admin", "cajera"):
        salon[persona].sucursal_id = salon["sucursal"].id
    db.commit()

    class Api:
        s = salon

        def como(self, persona, metodo, ruta, **kw):
            return getattr(cliente, metodo)(ruta, headers=cabeceras(salon[persona]), **kw)

        def get(self, persona, ruta, **kw):
            return self.como(persona, "get", ruta, **kw)

        def post(self, persona, ruta, json=None, **kw):
            return self.como(persona, "post", ruta, json=json or {}, **kw)

    return Api()


def abrir_mesa(api, mesa="m1", persona="ana", **extra):
    r = api.post(persona, "/pedidos", {"mesa_id": api.s[mesa].id, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def tomar(api, pedido_id, item="burger", persona="ana", **datos):
    r = api.post(persona, f"/pedidos/{pedido_id}/lineas", {"item_id": api.s[item].id, **datos})
    assert r.status_code == 201, r.text
    return r.json()


# ── El viaje completo de un plato ────────────────────────────
def test_viaje_completo_del_pedido_por_http(api):
    pedido = abrir_mesa(api, comensales=2)
    assert pedido["estado"] == "abierto" and pedido["mesa"] == "Mesa 1"

    plato = tomar(api, pedido["id"], cantidad=2, comensal=1, sin_ingredientes=[api.s["cebolla"].id],
                  extra_ids=[api.s["extra"].id])
    assert plato["linea"]["estado"] == "tomada" and plato["disponibilidad"]["alcanza"] is True
    assert plato["linea"]["total"] == "15000.00"                        # (6.500 + 1.000) × 2, en texto exacto
    trago = tomar(api, pedido["id"], item="cola")

    # El plano muestra la mesa ocupada.
    plano = {m["nombre"]: m["estado"] for m in api.get("ana", "/mesas").json()}
    assert plano == {"Mesa 1": "ocupada", "Mesa 2": "libre"}

    # Enviar: todo junto a cocina y barra.
    envio = api.post("ana", f"/pedidos/{pedido['id']}/enviar")
    assert envio.status_code == 200 and {l["estado"] for l in envio.json()["lineas"]} == {"enviada"}
    assert envio.json()["faltantes"] == []

    # Cada estación ve solo lo suyo.
    cocina = api.get("chef", "/cocina/comandas").json()
    barra = api.get("barman", "/cocina/comandas").json()
    assert [(c["plato"], c["estado"]) for c in cocina] == [("Hamburguesa", "enviada")]
    assert [c["plato"] for c in barra] == ["Cola lata"]

    linea_id = plato["linea"]["id"]
    assert api.post("chef", f"/cocina/lineas/{linea_id}/iniciar").json()["estado"] == "en_preparacion"
    listo = api.post("chef", f"/cocina/lineas/{linea_id}/lista")
    assert listo.status_code == 200 and listo.json()["linea"]["estado"] == "lista" and listo.json()["sin_stock"] == []
    assert api.post("barman", f"/cocina/lineas/{trago['linea']['id']}/lista").status_code == 200

    # La mesa se enciende y el mesero retira.
    assert {m["nombre"]: m["estado"] for m in api.get("ana", "/mesas").json()}["Mesa 1"] == "lista"
    retiros = api.get("ana", "/retiros").json()
    assert sorted(r["plato"] for r in retiros) == ["Cola lata", "Hamburguesa"]
    assert api.get("beto", "/retiros").json() == []                      # no son sus mesas
    for r in retiros:
        assert api.post("ana", f"/lineas/{r['linea_id']}/entregar").json()["estado"] == "entregada"

    cuenta = api.post("ana", f"/pedidos/{pedido['id']}/cuenta")
    assert cuenta.status_code == 200
    assert cuenta.json()["estado"] == "cuenta_pedida" and cuenta.json()["cuenta"]["total"] == "16500.00"


def test_lo_hecho_por_la_api_queda_guardado(db, api):
    """Cada endpoint confirma (commit): una sesión nueva ve los datos."""
    from sqlalchemy.orm import sessionmaker
    pedido = abrir_mesa(api)
    tomar(api, pedido["id"])
    api.post("ana", f"/pedidos/{pedido['id']}/enviar")
    nueva = sessionmaker(bind=db.get_bind())()
    try:
        from models import Pedido
        assert nueva.get(Pedido, pedido["id"]).lineas[0].estado.value == "enviada"
    finally:
        nueva.close()


# ── Carta y mesas ────────────────────────────────────────────
def test_la_carta_solo_muestra_vendibles_con_su_semaforo(api):
    carta = {x["nombre"]: x for x in api.get("ana", "/carta").json()}
    assert set(carta) == {"Hamburguesa", "Cola lata"}
    assert carta["Hamburguesa"]["precio_venta"] == "6500.00" and carta["Hamburguesa"]["alcanza"] is True
    assert carta["Cola lata"]["estacion"] == "barra"
    api.post("chef", f"/cocina/items/{api.s['carne'].id}/agotado")
    carta = {x["nombre"]: x for x in api.get("ana", "/carta").json()}
    assert carta["Hamburguesa"]["alcanza"] is False
    assert carta["Hamburguesa"]["faltas"][0]["nombre"] == "Carne" and carta["Hamburguesa"]["faltas"][0]["agotado_manual"]


def test_la_carta_ofrece_lo_que_se_puede_quitar_y_agregar(api):
    carta = {x["nombre"]: x for x in api.get("ana", "/carta").json()}
    burger = carta["Hamburguesa"]
    assert [(o["id"], o["nombre"]) for o in burger["removibles"]] == [(api.s["cebolla"].id, "Cebolla")]
    assert [(o["nombre"], o["precio"]) for o in burger["extras"]] == [("Extra tocineta", "1000.00")]
    assert carta["Cola lata"]["removibles"] == []


def test_el_admin_arma_el_plano_y_el_mesero_se_ancla_por_qr(api):
    r = api.post("admin", "/mesas", {"nombre": "Terraza 1", "capacidad": 6, "pos_x": 10, "pos_y": 20, "forma": "redonda"})
    assert r.status_code == 201
    mesa = r.json()
    assert (mesa["nombre"], mesa["forma"], mesa["sucursal_id"]) == ("Terraza 1", "redonda", api.s["sucursal"].id)
    movida = api.como("admin", "patch", f"/mesas/{mesa['id']}/posicion", json={"pos_x": 300, "pos_y": 400})
    assert (movida.json()["pos_x"], movida.json()["pos_y"]) == (300, 400)
    # El plano que ve el salón trae dónde está y cómo es cada mesa (para dibujarlo).
    en_plano = {m["nombre"]: m for m in api.get("admin", "/mesas").json()}["Terraza 1"]
    assert (en_plano["pos_x"], en_plano["pos_y"], en_plano["forma"], en_plano["capacidad"]) == (300, 400, "redonda", 6)
    escaneada = api.get("ana", f"/mesas/qr/{mesa['qr_token']}")
    assert escaneada.status_code == 200 and escaneada.json()["id"] == mesa["id"]
    assert api.get("ana", "/mesas/qr/inventado").status_code == 404


def test_solo_el_admin_crea_mesas(api):
    assert api.post("ana", "/mesas", {"nombre": "X"}).status_code == 403
    assert api.post("cajera", "/mesas", {"nombre": "X"}).status_code == 403


# ── Reglas y errores con el código HTTP correcto ─────────────
def test_mesa_ocupada_es_422_y_plato_inexistente_404(api):
    abrir_mesa(api)
    r = api.post("beto", "/pedidos", {"mesa_id": api.s["m1"].id})
    assert r.status_code == 422 and "ya está ocupada" in r.json()["detalle"]
    pedido = abrir_mesa(api, mesa="m2", persona="beto")
    r = api.post("beto", f"/pedidos/{pedido['id']}/lineas", {"item_id": 99999})
    assert r.status_code == 404 and "no existe" in r.json()["detalle"]


def test_otro_mesero_no_toca_mi_mesa_pero_el_admin_si(api):
    pedido = abrir_mesa(api)
    linea = tomar(api, pedido["id"])["linea"]
    for ruta in (f"/pedidos/{pedido['id']}/enviar", f"/pedidos/{pedido['id']}/cuenta",
                 f"/pedidos/{pedido['id']}/anular", f"/lineas/{linea['id']}/cancelar"):
        assert api.post("beto", ruta).status_code == 403, ruta
    assert api.como("beto", "delete", f"/lineas/{linea['id']}").status_code == 403
    assert api.post("beto", f"/pedidos/{pedido['id']}/lineas", {"item_id": api.s["cola"].id}).status_code == 403
    assert api.post("admin", f"/pedidos/{pedido['id']}/enviar").status_code == 200


def test_traspaso_de_mesa_y_el_nuevo_mesero_pasa_a_manejarla(api):
    pedido = abrir_mesa(api)
    r = api.post("ana", f"/pedidos/{pedido['id']}/traspaso", {"nuevo_mesero_id": api.s["beto"].id})
    assert r.status_code == 200 and r.json()["mesero_id"] == api.s["beto"].id
    assert api.post("ana", f"/pedidos/{pedido['id']}/enviar").status_code == 403          # ya no es suya
    assert api.post("beto", f"/pedidos/{pedido['id']}/lineas", {"item_id": api.s["cola"].id}).status_code == 201


def test_quitar_un_plato_anotado_responde_204(api):
    pedido = abrir_mesa(api)
    linea = tomar(api, pedido["id"])["linea"]
    assert api.como("ana", "delete", f"/lineas/{linea['id']}").status_code == 204
    assert api.get("ana", f"/pedidos/{pedido['id']}").json()["lineas"] == []


def test_cancelar_en_preparacion_pasa_a_merma_via_api(api):
    pedido = abrir_mesa(api)
    linea = tomar(api, pedido["id"])["linea"]
    api.post("ana", f"/pedidos/{pedido['id']}/enviar")
    api.post("chef", f"/cocina/lineas/{linea['id']}/iniciar")
    r = api.post("ana", f"/lineas/{linea['id']}/cancelar")
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"
    # Un plato ya cancelado no se puede marcar listo.
    assert api.post("chef", f"/cocina/lineas/{linea['id']}/lista").status_code == 422


def test_faltante_al_tomar_avisa_sin_bloquear_y_al_enviar_alerta_al_admin(api):
    pedido = abrir_mesa(api)
    r = api.post("ana", f"/pedidos/{pedido['id']}/lineas", {"item_id": api.s["burger"].id, "cantidad": 60})
    assert r.status_code == 201 and r.json()["disponibilidad"]["alcanza"] is False
    envio = api.post("ana", f"/pedidos/{pedido['id']}/enviar").json()
    assert "Pan" in [f["nombre"] for f in envio["faltantes"]]


def test_cada_estacion_marca_solo_lo_suyo(api):
    pedido = abrir_mesa(api)
    plato = tomar(api, pedido["id"])["linea"]
    api.post("ana", f"/pedidos/{pedido['id']}/enviar")
    r = api.post("barman", f"/cocina/lineas/{plato['id']}/lista")
    assert r.status_code == 422 and "atiende la barra" in r.json()["detalle"]
    assert api.post("admin", f"/cocina/lineas/{plato['id']}/lista").status_code == 200


def test_el_boton_se_acabo_y_reponer(api):
    r = api.post("chef", f"/cocina/items/{api.s['carne'].id}/agotado")
    assert r.status_code == 200 and r.json() == {"platos_agotados": ["Hamburguesa"]}
    assert api.como("chef", "delete", f"/cocina/items/{api.s['carne'].id}/agotado").status_code == 204
    assert {x["nombre"]: x["alcanza"] for x in api.get("ana", "/carta").json()}["Hamburguesa"] is True


def test_el_cocinero_con_estacion_no_puede_espiar_la_otra(api):
    pedido = abrir_mesa(api)
    tomar(api, pedido["id"], item="cola")
    api.post("ana", f"/pedidos/{pedido['id']}/enviar")
    # Aunque el chef pida la barra, solo ve la cocina.
    assert api.get("chef", "/cocina/comandas?estacion=barra").json() == []
    assert len(api.get("admin", "/cocina/comandas?estacion=barra").json()) == 1


def test_aislamiento_entre_restaurantes_por_http(db, api, otro_local, nuevo_usuario, cabeceras, cliente):
    ajena, sucursal_ajena = otro_local
    mesero_ajeno = nuevo_usuario(ajena, "Mesero ajeno", sucursal_id=sucursal_ajena.id)
    pedido = abrir_mesa(api)
    cab = cabeceras(mesero_ajeno)
    assert cliente.get(f"/pedidos/{pedido['id']}", headers=cab).status_code == 404
    assert cliente.post(f"/pedidos/{pedido['id']}/enviar", headers=cab).status_code == 404
    assert cliente.post("/pedidos", json={"mesa_id": api.s["m2"].id}, headers=cab).status_code == 404
    assert cliente.get("/mesas", headers=cab).json() == []                                # su plano está vacío


def test_pedido_con_uuid_de_la_tablet_y_resincronizacion(api):
    uuid = "11111111-2222-3333-4444-555555555555"
    abrir_mesa(api, pedido_id=uuid)
    r = api.post("ana", "/pedidos", {"mesa_id": api.s["m2"].id, "pedido_id": uuid})
    assert r.status_code == 422 and "ya existe" in r.json()["detalle"]


def test_la_api_rechaza_datos_mal_formados(api):
    pedido = abrir_mesa(api)
    assert api.post("ana", f"/pedidos/{pedido['id']}/lineas", {"item_id": "abc"}).status_code == 422
    assert api.post("ana", f"/pedidos/{pedido['id']}/lineas", {"item_id": 1, "precio": 1}).status_code == 422   # campo extra
    assert api.post("ana", f"/pedidos/{pedido['id']}/lineas", {"item_id": api.s["burger"].id,
                                                                "cantidad": 0}).status_code == 422             # regla de negocio


def test_el_cocinero_ve_los_insumos_y_marca_lo_que_se_acabo(api):
    r = api.get("chef", "/cocina/items")
    assert r.status_code == 200
    nombres = {x["nombre"]: x for x in r.json()}
    assert "Carne" in nombres and "Hamburguesa" not in nombres and nombres["Carne"]["agotado"] is False
    assert api.post("chef", f"/cocina/items/{api.s['carne'].id}/agotado").status_code == 200
    r = api.get("chef", "/cocina/items").json()
    assert r[0]["nombre"] == "Carne" and r[0]["agotado"] is True      # los agotados van primero
    assert api.get("ana", "/cocina/items").status_code == 403           # el mesero no entra


def test_el_cocinero_ve_el_recetario_y_abre_cada_receta_sin_costos(api):
    r = api.get("chef", "/cocina/recetas")
    assert r.status_code == 200
    nombres = {x["nombre"] for x in r.json()}
    assert "Hamburguesa" in nombres and "Carne" not in nombres        # solo lo que tiene receta
    receta = api.get("chef", f"/items/{api.s['burger'].id}/receta").json()
    assert receta["lineas"] and "costo_linea" not in str(receta)
    assert api.get("ana", "/cocina/recetas").status_code == 403         # el mesero no entra


def test_el_mesero_ve_a_quien_puede_pasarle_una_mesa_y_se_la_pasa(api):
    otros = api.get("ana", "/meseros").json()
    assert [m["nombre"] for m in otros] == ["Beto"]                       # no se lista a sí misma ni a cocina/caja
    pedido = abrir_mesa(api)
    r = api.post("ana", f"/pedidos/{pedido['id']}/traspaso", {"nuevo_mesero_id": otros[0]["id"]})
    assert r.status_code == 200 and r.json()["mesero_id"] == otros[0]["id"]
    assert api.post("ana", f"/pedidos/{pedido['id']}/traspaso", {"nuevo_mesero_id": otros[0]["id"]}).status_code == 403   # ya no es suya


def test_sin_barman_el_mesero_busca_la_bebida_y_con_barman_sale_de_la_barra(api, db):
    from sqlalchemy import func
    from models import StockSucursal

    def fisico():
        return db.query(func.sum(StockSucursal.cantidad_fisica)).filter(StockSucursal.item_id == api.s["cola"].id).scalar()

    def carta():
        return {x["nombre"]: x for x in api.get("ana", "/carta").json()}

    # Con barman registrado (el del fixture): la bebida sale de la barra, el mesero no puede saltársela.
    assert carta()["Cola lata"]["directo"] is False
    p1 = abrir_mesa(api, "m1")
    cola1 = tomar(api, p1["id"], item="cola")["linea"]
    assert api.post("ana", f"/pedidos/{p1['id']}/enviar").status_code == 200
    assert api.post("ana", f"/lineas/{cola1['id']}/entregar").status_code == 422
    assert api.post("barman", f"/cocina/lineas/{cola1['id']}/lista").status_code == 200       # la barra la marca lista…
    assert api.post("ana", f"/lineas/{cola1['id']}/entregar").status_code == 200              # …y el mesero la retira y entrega

    # Sin barman: el mesero busca la bebida y la entrega directo; el stock sale igual.
    api.s["barman"].activo = False
    db.commit()
    assert carta()["Cola lata"]["directo"] is True and carta()["Hamburguesa"]["directo"] is False
    antes = fisico()
    p2 = abrir_mesa(api, "m2", persona="beto")
    cola2 = tomar(api, p2["id"], item="cola", persona="beto")["linea"]
    burger = tomar(api, p2["id"], item="burger", persona="beto")["linea"]
    assert api.post("beto", f"/pedidos/{p2['id']}/enviar").status_code == 200
    assert api.post("beto", f"/lineas/{burger['id']}/entregar").status_code == 422             # la cocina sigue siendo la cocina
    r = api.post("beto", f"/lineas/{cola2['id']}/entregar")
    assert r.status_code == 200 and r.json()["estado"] == "entregada"
    db.expire_all()
    assert antes - fisico() == 1


def test_el_admin_renombra_y_quita_mesas(api):
    mesa = api.post("admin", "/mesas", {"nombre": "Terraza 1", "capacidad": 4}).json()
    r = api.como("admin", "patch", f"/mesas/{mesa['id']}", json={"nombre": "Terraza A", "capacidad": 6, "forma": "redonda"})
    assert r.status_code == 200 and (r.json()["nombre"], r.json()["capacidad"], r.json()["forma"]) == ("Terraza A", 6, "redonda")
    assert api.como("admin", "patch", f"/mesas/{mesa['id']}", json={"nombre": "Mesa 1"}).status_code == 422      # ya existe
    assert api.como("ana", "patch", f"/mesas/{mesa['id']}", json={"nombre": "X"}).status_code == 403
    # Una mesa que nunca se usó se borra del todo.
    assert api.como("admin", "delete", f"/mesas/{mesa['id']}").status_code == 204
    assert "Terraza A" not in [m["nombre"] for m in api.get("admin", "/mesas").json()]
    # Una mesa con pedido abierto no se puede quitar; con historial se archiva y su nombre queda libre.
    pedido = abrir_mesa(api, "m1")
    assert api.como("admin", "delete", f"/mesas/{api.s['m1'].id}").status_code == 422
    assert api.post("ana", f"/pedidos/{pedido['id']}/anular").status_code == 200
    assert api.como("admin", "delete", f"/mesas/{api.s['m1'].id}").status_code == 204
    assert "Mesa 1" not in [m["nombre"] for m in api.get("admin", "/mesas").json()]
    assert api.post("admin", "/mesas", {"nombre": "Mesa 1"}).status_code == 201                                     # el nombre se reutiliza


def test_cuentas_para_llevar_se_listan_para_el_mesero_y_el_cajero(api):
    # Sin mesa: mostrador o delivery. Ana abre una; Beto, otra.
    a = api.post("ana", "/pedidos", {}).json()
    b = api.post("beto", "/pedidos", {}).json()
    assert a["mesa"] is None
    api.post("ana", f"/pedidos/{a['id']}/lineas", {"item_id": api.s["burger"].id})
    mesa = abrir_mesa(api, "m1", "ana")                       # una con mesa NO aparece en la lista
    assert mesa["mesa"] is not None
    de_ana = api.get("ana", "/pedidos-sin-mesa").json()
    assert [x["pedido_id"] for x in de_ana] == [a["id"]]
    assert de_ana[0]["lineas"] == 1 and de_ana[0]["total"] == "6500.00" and de_ana[0]["despacho_estado"] is None
    todas = api.get("cajera", "/pedidos-sin-mesa").json()
    assert {x["pedido_id"] for x in todas} == {a["id"], b["id"]}
    assert api.get("cajera", "/pedidos-sin-mesa").status_code == 200
    assert api.get("chef", "/pedidos-sin-mesa").status_code == 403
