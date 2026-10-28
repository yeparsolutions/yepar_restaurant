# ============================================================
# YEPAR RESTAURANT — backend/database.py
# Conexión a la base de datos y base declarativa de SQLAlchemy.
#
# Analogía: este archivo es la "llave maestra" del edificio.
# Todos los modelos se declaran sobre `Base`, y toda la app pide
# su conexión con `get_db()` — nadie abre su propia puerta.
#
# En desarrollo usa SQLite (un archivo local, sin instalar nada).
# En producción (más adelante, Railway) se define DATABASE_URL
# apuntando a PostgreSQL y el resto del código no cambia.
# ============================================================

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./yepar_restaurant_dev.db")

# Railway entrega "postgres://", pero SQLAlchemy 2 exige "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite necesita este permiso extra para usarse desde varios hilos.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)

# expire_on_commit=False: después de guardar, los objetos siguen
# siendo legibles sin volver a consultar la base.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Clase base de la que heredan todos los modelos."""


def get_db():
    """Dependencia de FastAPI: abre una sesión y la cierra al terminar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
