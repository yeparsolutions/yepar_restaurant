"""Catálogo global de unidades de medida (g, kg, ml, cc, l, und, mg).

Sin estas filas nada funciona (stock, recetas y compras convierten con ellas), por eso se siembran
con la migración y no a mano. Es idempotente: si una unidad ya existe, no se toca.

Revisión: 0002
Anterior: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# (código, nombre, familia, factor a la unidad base de su familia, ¿es base?)
# Copia fija a propósito: una migración no debe cambiar si mañana cambia semilla.py.
UNIDADES = [
    ("mg",  "Miligramo",         "peso",    "0.001", False),
    ("g",   "Gramo",             "peso",    "1",     True),
    ("kg",  "Kilogramo",         "peso",    "1000",  False),
    ("ml",  "Mililitro",         "volumen", "1",     True),
    ("cc",  "Centímetro cúbico", "volumen", "1",     False),
    ("l",   "Litro",             "volumen", "1000",  False),
    ("und", "Unidad",            "unidad",  "1",     True),
]


def upgrade() -> None:
    # INSERT ... WHERE NOT EXISTS: idempotente y válido tanto en SQLite como en PostgreSQL,
    # y también en modo "solo mostrar SQL" (alembic upgrade head --sql), donde no hay conexión para consultar.
    for codigo, nombre, familia, factor, es_base in UNIDADES:
        op.execute(sa.text(
            f"INSERT INTO unidades (codigo, nombre, familia, factor_a_base, es_base) "
            f"SELECT '{codigo}', '{nombre}', '{familia}', {factor}, {'true' if es_base else 'false'} "
            f"WHERE NOT EXISTS (SELECT 1 FROM unidades WHERE codigo = '{codigo}')"))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM unidades WHERE codigo IN ('mg','g','kg','ml','cc','l','und')"))
