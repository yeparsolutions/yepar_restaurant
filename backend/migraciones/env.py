# ============================================================
# YEPAR RESTAURANT — backend/migraciones/env.py
# Cómo corre Alembic: toma la base de DATABASE_URL (la misma que usa la app)
# y compara/crea el esquema a partir de los modelos.
#
# Analogía: las migraciones son el "libro de obras" del edificio: cada
# cambio al esquema queda anotado en orden, y cualquier base nueva (o
# atrasada) se pone al día reproduciendo esas obras, sin tocar datos.
# ============================================================

from alembic import context
from sqlalchemy import create_engine

import models  # noqa: F401  (registra todos los modelos en Base.metadata)
from database import DATABASE_URL, Base

config = context.config
target_metadata = Base.metadata


def _opciones() -> dict:
    return dict(
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite no sabe alterar tablas: Alembic las reconstruye ("batch"). En PostgreSQL no hace falta.
        render_as_batch=True,
    )


def migrar_sin_conexion() -> None:
    """Modo `--sql`: imprime el SQL en vez de ejecutarlo (sirve para revisar lo que correrá en PostgreSQL)."""
    context.configure(url=config.get_main_option("sqlalchemy.url") or DATABASE_URL, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, **_opciones())
    with context.begin_transaction():
        context.run_migrations()


def migrar_con_conexion() -> None:
    # Las pruebas pasan su propia conexión (config.attributes["connection"]); si no, se usa DATABASE_URL.
    conexion = config.attributes.get("connection")
    if conexion is not None:
        context.configure(connection=conexion, **_opciones())
        with context.begin_transaction():
            context.run_migrations()
        return
    motor = create_engine(DATABASE_URL)
    with motor.connect() as conexion:
        context.configure(connection=conexion, **_opciones())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    migrar_sin_conexion()
else:
    migrar_con_conexion()
