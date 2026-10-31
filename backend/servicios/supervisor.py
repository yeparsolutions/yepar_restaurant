# ============================================================
# YEPAR RESTAURANT — backend/servicios/supervisor.py
# PIN de supervisor: la "llave maestra" del administrador para autorizar
# lo que el cajero no puede hacer solo (hoy: descuentos sobre su tope).
#
# Analogía: en una tienda, el cajero llama al encargado, que pasa su llave
# por la caja. Aquí el encargado teclea su PIN en la tablet del cajero, y
# el sistema deja anotado QUIÉN lo autorizó.
#
# Seguridad: PIN de 4 a 6 dígitos guardado con bcrypt; 5 fallos seguidos
# bloquean ese PIN 15 minutos (un PIN corto sin bloqueo se adivina a fuerza bruta).
# ============================================================

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import RolUsuario, Usuario
from seguridad import encriptar_password, verificar_password

MAX_FALLOS = 5
MINUTOS_BLOQUEO = 15


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _es_admin(u: Usuario) -> bool:
    return any(r.rol == RolUsuario.administrador for r in u.roles)


def _pin_debil(pin: str) -> bool:
    return len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210"


def definir_pin(db: Session, usuario: Usuario, *, pin: str, password: str) -> None:
    """El administrador crea o cambia su propio PIN, confirmando con su contraseña."""
    if not _es_admin(usuario):
        raise ErrorNegocio("Solo un administrador tiene PIN de supervisor.")
    if not verificar_password(password, usuario.password_hash):
        raise ErrorNegocio("La contraseña no es correcta.")
    if not (pin.isascii() and pin.isdigit() and 4 <= len(pin) <= 6):
        raise ErrorNegocio("El PIN son entre 4 y 6 dígitos.")
    if _pin_debil(pin):
        raise ErrorNegocio("Ese PIN es muy fácil de adivinar (0000, 1234...): elige otro.")
    usuario.pin_hash = encriptar_password(pin)
    usuario.pin_fallos = 0
    usuario.pin_bloqueado_hasta = None
    db.flush()


def quitar_pin(db: Session, usuario: Usuario) -> None:
    usuario.pin_hash = None
    usuario.pin_fallos = 0
    usuario.pin_bloqueado_hasta = None
    db.flush()


def listar_supervisores(db: Session, empresa_id: int) -> list[Usuario]:
    """Los administradores activos con PIN: a quién puede llamar el cajero."""
    todos = db.query(Usuario).filter(Usuario.empresa_id == empresa_id, Usuario.activo.is_(True),
                                     Usuario.pin_hash.isnot(None)).order_by(Usuario.nombre).all()
    return [u for u in todos if _es_admin(u)]


def autorizar(db: Session, *, empresa_id: int, supervisor_id: int, pin: str) -> Usuario:
    """
    Verifica el PIN del supervisor y lo devuelve. Un intento FALLIDO se confirma (commit) antes de avisar:
    si no, el contador de fallos se perdería con el rollback de la petición y el bloqueo no serviría.
    """
    s = db.get(Usuario, supervisor_id)
    if s is None or s.empresa_id != empresa_id or not s.activo or not _es_admin(s) or not s.pin_hash:
        raise ErrorNegocio("Ese supervisor no existe o no tiene PIN.")
    bloqueado = s.pin_bloqueado_hasta
    if bloqueado is not None:
        bloqueado = bloqueado if bloqueado.tzinfo else bloqueado.replace(tzinfo=timezone.utc)
        if bloqueado > _ahora():
            minutos = int((bloqueado - _ahora()).total_seconds() // 60) + 1
            raise ErrorNegocio(f"El PIN de '{s.nombre}' está bloqueado por intentos fallidos: reintenta en {minutos} min.")
    if not verificar_password(pin or "", s.pin_hash):
        s.pin_fallos = (s.pin_fallos or 0) + 1
        if s.pin_fallos >= MAX_FALLOS:
            s.pin_bloqueado_hasta = _ahora() + timedelta(minutes=MINUTOS_BLOQUEO)
            s.pin_fallos = 0
        db.commit()
        raise ErrorNegocio("PIN incorrecto.")
    s.pin_fallos = 0
    s.pin_bloqueado_hasta = None
    db.flush()
    return s
