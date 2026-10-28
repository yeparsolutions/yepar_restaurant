# ============================================================
# YEPAR RESTAURANT — backend/errores.py
# Errores de negocio compartidos por todo el backend.
#
# Analogía: es el "libro de reclamos" del sistema. Cuando una regla
# no se cumple (una unidad incompatible, un ingrediente de otro
# cliente, una receta circular), se levanta un ErrorNegocio con un
# mensaje claro. La capa de la API lo convertirá en una respuesta
# HTTP 422 legible, en vez de un error 500 misterioso.
# ============================================================


class ErrorNegocio(ValueError):
    """Una regla de negocio no se cumple (dato inválido, ítem ajeno, etc.)."""
