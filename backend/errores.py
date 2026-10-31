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


class ErrorNoEncontrado(ErrorNegocio):
    """
    El dato no existe PARA ESTE CLIENTE (o no existe a secas). La API lo responde
    con 404. Para datos de otro cliente se usa el mismo error: nunca confirmamos
    que existen. Sigue siendo un ErrorNegocio, así que quien lo capture como
    ErrorNegocio lo seguirá viendo.
    """
