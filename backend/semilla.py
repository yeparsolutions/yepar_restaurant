# ============================================================
# YEPAR RESTAURANT — backend/semilla.py
# Datos iniciales que el sistema necesita para funcionar.
#
# Hoy: el catálogo global de unidades de medida. Se puede ejecutar
# muchas veces sin duplicar nada ("idempotente").
#
# Analogía: antes de abrir el restaurante hay que dejar las reglas de
# medir (gramo, litro, unidad) colgadas en la pared de la bodega.
#
# Uso:  python semilla.py
# ============================================================

from decimal import Decimal

from sqlalchemy.orm import Session

from models.enums import FamiliaUnidad
from models.inventario import Unidad

# (código, nombre, familia, factor a la unidad base de su familia, ¿es base?)
UNIDADES_ESTANDAR = [
    ("mg",  "Miligramo",           FamiliaUnidad.peso,    Decimal("0.001"), False),
    ("g",   "Gramo",               FamiliaUnidad.peso,    Decimal("1"),     True),
    ("kg",  "Kilogramo",           FamiliaUnidad.peso,    Decimal("1000"),  False),
    ("ml",  "Mililitro",           FamiliaUnidad.volumen, Decimal("1"),     True),
    ("cc",  "Centímetro cúbico",   FamiliaUnidad.volumen, Decimal("1"),     False),   # 1 cc = 1 ml
    ("l",   "Litro",               FamiliaUnidad.volumen, Decimal("1000"),  False),
    ("und", "Unidad",              FamiliaUnidad.unidad,  Decimal("1"),     True),
]


def sembrar_unidades(db: Session) -> dict:
    """
    Crea las unidades estándar que falten y devuelve un diccionario
    {codigo: Unidad}. Si una ya existe, no la toca.
    """
    existentes = {u.codigo: u for u in db.query(Unidad).all()}
    for codigo, nombre, familia, factor, es_base in UNIDADES_ESTANDAR:
        if codigo not in existentes:
            unidad = Unidad(codigo=codigo, nombre=nombre, familia=familia,
                            factor_a_base=factor, es_base=es_base)
            db.add(unidad)
            existentes[codigo] = unidad
    db.commit()
    return existentes


if __name__ == "__main__":
    # Crea las tablas (si no existen) y siembra las unidades.
    from database import Base, SessionLocal, engine
    import models  # noqa: F401  (registra todos los modelos antes de crear tablas)

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as sesion:
        unidades = sembrar_unidades(sesion)
    print(f"Unidades listas: {', '.join(sorted(unidades))}")
