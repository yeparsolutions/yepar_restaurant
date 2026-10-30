# ============================================================
# YEPAR RESTAURANT — backend/tests/test_migraciones.py
# Vigila que las migraciones (Alembic) y los modelos no se separen:
# si alguien cambia un modelo y olvida la migración, esta prueba falla.
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

import io
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

import models  # noqa: F401
from database import Base
from semilla import UNIDADES_ESTANDAR

RAIZ = Path(__file__).resolve().parent.parent


def configuracion(**atributos) -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migraciones"))
    cfg.attributes.update(atributos)
    return cfg


@pytest.fixture()
def base_migrada():
    """Una base SQLite en memoria con TODAS las migraciones aplicadas."""
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with motor.begin() as conexion:
        command.upgrade(configuracion(connection=conexion), "head")
    yield motor
    motor.dispose()


def test_las_migraciones_dejan_el_mismo_esquema_que_los_modelos(base_migrada):
    with base_migrada.connect() as conexion:
        contexto = MigrationContext.configure(conexion, opts={"compare_type": True})
        diferencias = compare_metadata(contexto, Base.metadata)
    assert diferencias == [], f"Faltan migraciones para los modelos: {diferencias}"


def test_la_migracion_siembra_las_mismas_unidades_que_semilla(base_migrada):
    with base_migrada.connect() as conexion:
        filas = conexion.execute(text("SELECT codigo, familia, factor_a_base, es_base FROM unidades")).all()
    en_base = {c: (f, float(factor), bool(b)) for c, f, factor, b in filas}
    esperadas = {c: (fam.value, float(factor), b) for c, _, fam, factor, b in UNIDADES_ESTANDAR}
    assert en_base == esperadas


def test_se_puede_volver_atras_hasta_dejar_la_base_vacia():
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with motor.begin() as conexion:
        cfg = configuracion(connection=conexion)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
    assert set(inspect(motor).get_table_names()) <= {"alembic_version"}


def test_el_sql_para_postgresql_es_valido_y_portable():
    """Genera el SQL que correrá en Railway (sin conectarse) y revisa lo que más suele romperse."""
    salida = io.StringIO()
    cfg = configuracion()
    cfg.output_buffer = salida
    cfg.set_main_option("sqlalchemy.url", "postgresql://u:p@localhost/x")
    command.upgrade(cfg, "head", sql=True)
    sql = salida.getvalue()
    assert "CREATE TABLE empresas" in sql and "CREATE TABLE documentos_tributarios" in sql
    assert "BOOLEAN DEFAULT true" in sql and "BOOLEAN DEFAULT 1" not in sql      # SQLite usa 1/0; PostgreSQL no lo acepta
    assert "DEFAULT now()" in sql and "CURRENT_TIMESTAMP" not in sql
    assert "CREATE UNIQUE INDEX uq_pedido_mesa_abierta ON pedidos (mesa_id) WHERE estado IN" in sql
    assert "INSERT INTO unidades" in sql
