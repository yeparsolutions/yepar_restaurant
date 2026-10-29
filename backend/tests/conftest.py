# ============================================================
# YEPAR RESTAURANT — backend/tests/conftest.py
# Preparación compartida por todas las pruebas.
#
# Cada prueba recibe una base SQLite en memoria, nueva y vacía, así
# que no dependen una de otra ni tocan datos reales.
# ============================================================

from decimal import Decimal

D = Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registra todos los modelos antes de crear tablas)
from database import Base
from models import (EstacionCocina, Empresa, Extra, ExtraPlato, Item, RolUsuario, Sucursal,
                    TipoItem, Usuario, UsuarioRol)
from servicios.caja import crear_caja, crear_terminal
from servicios.compras import ingresar_compra
from servicios.mesas import crear_mesa
from servicios.recetas import LineaReceta, guardar_receta
from semilla import sembrar_unidades


@pytest.fixture()
def db():
    """Sesión sobre una base limpia, con todas las tablas creadas."""
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield sesion
    sesion.close()
    engine.dispose()


@pytest.fixture()
def u(db):
    """Catálogo de unidades sembrado: u['kg'], u['g'], u['ml']..."""
    return sembrar_unidades(db)


@pytest.fixture()
def local(db):
    """Un restaurante con una sucursal: devuelve (empresa, sucursal)."""
    empresa = Empresa(nombre="Hamburguesería Demo", codigo_acceso="DEMO0001")
    db.add(empresa)
    db.flush()
    sucursal = Sucursal(empresa_id=empresa.id, nombre="Casa matriz")
    db.add(sucursal)
    db.commit()
    return empresa, sucursal


@pytest.fixture()
def otro_local(db):
    """Un SEGUNDO restaurante (otro cliente), para probar el aislamiento entre clientes."""
    empresa = Empresa(nombre="Pizzería Ajena", codigo_acceso="AJENA001")
    db.add(empresa)
    db.flush()
    sucursal = Sucursal(empresa_id=empresa.id, nombre="Local ajeno")
    db.add(sucursal)
    db.commit()
    return empresa, sucursal


@pytest.fixture()
def nuevo_item(db):
    """Fábrica de ítems: nuevo_item(empresa, unidad_base, 'Tomate', tipo=..., **extras)."""
    def _crear(empresa, unidad_base, nombre, tipo=TipoItem.materia_prima, **extra):
        item = Item(empresa_id=empresa.id, tipo=tipo, nombre=nombre,
                    unidad_base_id=unidad_base.id, **extra)
        db.add(item)
        db.commit()
        return item
    return _crear


@pytest.fixture()
def nuevo_usuario(db):
    """Fábrica de usuarios: nuevo_usuario(empresa, 'Ana', roles=(RolUsuario.mesero,))."""
    def _crear(empresa, nombre, roles=(RolUsuario.mesero,), **extra):
        usuario = Usuario(empresa_id=empresa.id, nombre=nombre, username=nombre.lower().replace(" ", "."),
                          password_hash="x", **extra)
        usuario.roles = [UsuarioRol(rol=r) for r in roles]
        db.add(usuario)
        db.commit()
        return usuario
    return _crear


@pytest.fixture()
def salon(db, u, local, nuevo_item, nuevo_usuario):
    """Local con 2 mesas, 2 meseros y una carta: hamburguesa ($6.500), extra tocineta ($1.000) y cola ($1.500)."""
    empresa, sucursal = local
    pan = nuevo_item(empresa, u["und"], "Pan")
    carne = nuevo_item(empresa, u["g"], "Carne")
    cebolla = nuevo_item(empresa, u["g"], "Cebolla")
    tocineta = nuevo_item(empresa, u["g"], "Tocineta")
    cola = nuevo_item(empresa, u["und"], "Cola lata", tipo=TipoItem.vendible_reventa,
                      precio_venta=Decimal("1500"), estacion=EstacionCocina.barra)
    burger = nuevo_item(empresa, u["und"], "Hamburguesa", tipo=TipoItem.vendible_preparado,
                        precio_venta=Decimal("6500"))
    guardar_receta(db, empresa_id=empresa.id, item_id=burger.id, rendimiento=1, lineas=[
        LineaReceta(pan.id, 1), LineaReceta(carne.id, 150), LineaReceta(cebolla.id, 30, es_removible=True)])
    extra = Extra(empresa_id=empresa.id, nombre="Extra tocineta", precio=Decimal("1000"),
                  ingrediente_id=tocineta.id, cantidad=Decimal("25"), aplica_a_todos=False)
    db.add(extra)
    db.flush()
    db.add(ExtraPlato(extra_id=extra.id, item_id=burger.id))
    for item, cant in ((pan, 50), (carne, 3000), (cebolla, 1000), (tocineta, 500), (cola, 24)):
        ingresar_compra(db, empresa_id=empresa.id, sucursal_id=sucursal.id, item_id=item.id,
                        cantidad=cant, costo_unitario_base="1")
    m1 = crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 1")
    m2 = crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 2")
    ana = nuevo_usuario(empresa, "Ana")
    beto = nuevo_usuario(empresa, "Beto")
    cocinero = nuevo_usuario(empresa, "Carlos", roles=(RolUsuario.cocinero,))
    db.commit()
    return dict(empresa=empresa, sucursal=sucursal, pan=pan, carne=carne, cebolla=cebolla, cola=cola,
                burger=burger, extra=extra, m1=m1, m2=m2, ana=ana, beto=beto, cocinero=cocinero)


@pytest.fixture()
def cobro(db, salon, nuevo_usuario):
    """Salón + cajera (tope de descuento 10%), administrador, chef, una caja y un terminal."""
    s = salon
    e, suc = s["empresa"], s["sucursal"]
    s["cata"] = nuevo_usuario(e, "Cata", roles=(RolUsuario.cajero,), descuento_max_pct=D("10"))
    s["otra_cajera"] = nuevo_usuario(e, "Dani", roles=(RolUsuario.cajero,))
    s["admin"] = nuevo_usuario(e, "Admin", roles=(RolUsuario.administrador,))
    s["chef"] = nuevo_usuario(e, "Chef", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.cocina)
    s["barman"] = nuevo_usuario(e, "Barman", roles=(RolUsuario.cocinero,), estacion=EstacionCocina.barra)
    s["caja"] = crear_caja(db, empresa_id=e.id, sucursal_id=suc.id, nombre="Caja 1")
    s["caja2"] = crear_caja(db, empresa_id=e.id, sucursal_id=suc.id, nombre="Caja 2")
    s["terminal"] = crear_terminal(db, empresa_id=e.id, sucursal_id=suc.id, nombre="Terminal 1")
    db.commit()
    return s
