# ============================================================
# YEPAR RESTAURANT — backend/tests/conftest.py
# Preparación compartida por todas las pruebas.
#
# Cada prueba recibe una base SQLite en memoria, nueva y vacía, así
# que no dependen una de otra ni tocan datos reales.
# ============================================================

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registra todos los modelos antes de crear tablas)
from database import Base
from models import Empresa, Item, Sucursal, TipoItem
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
