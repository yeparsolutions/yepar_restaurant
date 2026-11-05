# ============================================================
# YEPAR RESTAURANT — backend/servicios/acceso.py
# Cómo se identifica a una persona sin escribir el código del restaurante:
#   · El administrador entra con su CORREO (único en todo el sistema).
#   · Las tablets se VINCULAN una vez con un enlace firmado; después el personal solo toca su nombre.
#
# Analogía: el correo es la credencial personal del dueño. El enlace de vinculación es la llave de una
# tablet: se entrega una sola vez y, si se pierde, el administrador cambia la cerradura de todas
# (sube la versión) y las llaves viejas dejan de abrir.
# ============================================================

import re

from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import Empresa, RolUsuario, Usuario, UsuarioRol
from seguridad import ALGORITHM, SECRET_KEY

_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_CORREO = 150


def normalizar_correo(correo: str) -> str:
    """Minúsculas y sin espacios: 'Ana@X.cl ' y 'ana@x.cl' son la misma cuenta."""
    c = (correo or "").strip().lower()
    if not _CORREO.match(c) or len(c) > MAX_CORREO:
        raise ErrorNegocio("Escribe un correo válido (ej. nombre@correo.com).")
    return c


def correo_libre(db: Session, correo: str, *, excepto_usuario_id: int | None = None) -> None:
    """El correo no puede estar en uso por nadie, de ningún restaurante."""
    q = db.query(Usuario.id).filter(func.lower(Usuario.email) == correo)
    if excepto_usuario_id is not None:
        q = q.filter(Usuario.id != excepto_usuario_id)
    if q.first() is not None:
        raise ErrorNegocio("Ese correo ya está registrado. Inicia sesión o usa otro.")


def poner_correo(db: Session, usuario: Usuario, correo: str) -> Usuario:
    correo = normalizar_correo(correo)
    correo_libre(db, correo, excepto_usuario_id=usuario.id)
    usuario.email = correo
    db.flush()
    return usuario


def usuario_por_correo(db: Session, correo: str) -> Usuario | None:
    """Para iniciar sesión: la persona dueña de ese correo, o None."""
    c = (correo or "").strip().lower()
    return db.query(Usuario).filter(func.lower(Usuario.email) == c).one_or_none() if c else None


# ── Vinculación de tablets ───────────────────────────────────
def crear_vinculo(empresa: Empresa) -> str:
    """Enlace firmado de la tablet. No vence: se invalida subiendo la versión (ver revocar_vinculos)."""
    return jwt.encode({"tipo": "vinculo", "emp": empresa.id, "v": empresa.vinculo_version}, SECRET_KEY, algorithm=ALGORITHM)


def empresa_de_vinculo(db: Session, token: str) -> Empresa:
    """El restaurante al que apunta un enlace, si sigue vigente."""
    invalido = ErrorNoEncontrado("Este enlace ya no es válido. Pide uno nuevo al administrador.")
    try:
        datos = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if datos.get("tipo") != "vinculo":
            raise invalido
        empresa_id, version = int(datos["emp"]), int(datos["v"])
    except (JWTError, KeyError, ValueError):
        raise invalido
    empresa = db.get(Empresa, empresa_id)
    if empresa is None or not empresa.activa or empresa.vinculo_version != version:
        raise invalido
    return empresa


def revocar_vinculos(db: Session, empresa: Empresa) -> None:
    """Invalida todos los enlaces y tablets vinculadas hasta ahora."""
    empresa.vinculo_version += 1
    db.flush()


def personal_de_tablet(db: Session, empresa_id: int) -> list[Usuario]:
    """Quién aparece en la pantalla de la tablet: el equipo activo. Los administradores entran por correo."""
    admin_ids = db.query(UsuarioRol.usuario_id).filter(UsuarioRol.rol == RolUsuario.administrador)
    return (db.query(Usuario).filter(Usuario.empresa_id == empresa_id, Usuario.activo.is_(True),
                                     Usuario.id.notin_(admin_ids)).order_by(Usuario.nombre).all())
