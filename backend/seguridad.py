# ============================================================
# YEPAR RESTAURANT — backend/seguridad.py
# Contraseñas, tokens de sesión y control de acceso por rol.
#
# Analogía: es el portero del restaurante. Al entrar se identifica
# (login) y recibe una pulsera con su nombre y rol (el token). En cada
# puerta interna el portero mira la pulsera: "¿eres cocinero? la cocina
# es por allá". Y SIEMPRE vuelve a confirmar en el libro de personal que
# la persona sigue activa (así un despedido pierde acceso al tiro).
#
# Mismo esquema que YeparStock (Carora): JWT firmado + bcrypt.
# ============================================================

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import DATABASE_URL, get_db
from models import RolUsuario, Usuario

_CLAVE_POR_DEFECTO = "clave-de-desarrollo-cambiar-en-produccion"
SECRET_KEY = os.environ.get("SECRET_KEY", _CLAVE_POR_DEFECTO)
ALGORITHM = os.environ.get("ALGORITHM", "HS256")
MINUTOS_DE_SESION = int(os.environ.get("ACCESS_TOKEN_MINUTES", "720"))     # un turno de trabajo

# En producción (PostgreSQL) NO se permite firmar con la clave de ejemplo.
if not DATABASE_URL.startswith("sqlite") and SECRET_KEY == _CLAVE_POR_DEFECTO:
    raise RuntimeError("Define la variable de entorno SECRET_KEY antes de usar una base de datos real.")

_contexto = CryptContext(schemes=["bcrypt"], deprecated="auto",
                         bcrypt__rounds=int(os.environ.get("BCRYPT_ROUNDS", "12")))
_esquema = HTTPBearer(auto_error=False)


def encriptar_password(password: str) -> str:
    return _contexto.hash(password)


def verificar_password(password: str, hash_guardado: str) -> bool:
    try:
        return _contexto.verify(password, hash_guardado)
    except ValueError:
        return False            # hash mal formado: tratarlo como contraseña incorrecta


def crear_token(usuario: Usuario) -> str:
    vence = datetime.now(timezone.utc) + timedelta(minutes=MINUTOS_DE_SESION)
    return jwt.encode({"sub": str(usuario.id), "emp": usuario.empresa_id, "exp": vence},
                      SECRET_KEY, algorithm=ALGORITHM)


def usuario_actual(
    credenciales: Optional[HTTPAuthorizationCredentials] = Depends(_esquema),
    db: Session = Depends(get_db),
) -> Usuario:
    """La persona de la sesión. Se revalida contra la base en cada petición."""
    sin_acceso = HTTPException(status_code=401, detail="Sesión inválida o vencida: vuelve a iniciar sesión.",
                               headers={"WWW-Authenticate": "Bearer"})
    if credenciales is None:
        raise sin_acceso
    try:
        datos = jwt.decode(credenciales.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        usuario_id, empresa_id = int(datos["sub"]), int(datos["emp"])
    except (JWTError, KeyError, ValueError):
        raise sin_acceso
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.activo or usuario.empresa_id != empresa_id:
        raise sin_acceso
    return usuario


def roles_de(usuario: Usuario) -> set:
    return {r.rol for r in usuario.roles}


def exigir_roles(*permitidos: RolUsuario):
    """
    Dependencia: deja pasar solo a quien tenga alguno de esos roles.
    El administrador entra siempre (controla todo).
    """
    admitidos = set(permitidos) | {RolUsuario.administrador}

    def _revisar(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if not roles_de(usuario) & admitidos:
            raise HTTPException(status_code=403, detail="Tu rol no tiene permiso para esta acción.")
        return usuario

    return _revisar


def es_admin(usuario: Usuario) -> bool:
    return RolUsuario.administrador in roles_de(usuario)


def resolver_sucursal(usuario: Usuario, sucursal_id: Optional[int]) -> int:
    """
    El personal trabaja en UN local (su sucursal). El administrador sin local fijo
    debe indicar cuál con `sucursal_id`.
    """
    if usuario.sucursal_id is not None and not es_admin(usuario):
        return usuario.sucursal_id
    elegido = sucursal_id if sucursal_id is not None else usuario.sucursal_id
    if elegido is None:
        raise HTTPException(status_code=422, detail="Indica la sucursal (sucursal_id).")
    return elegido
