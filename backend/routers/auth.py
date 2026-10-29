# ============================================================
# YEPAR RESTAURANT — backend/routers/auth.py
# Inicio de sesión. Cada restaurante entra con su código de acceso
# (la app es multi-cliente) más su usuario y contraseña.
# ============================================================

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from esquemas import LoginIn, TokenOut, UsuarioOut
from models import Empresa, Usuario
from routers.comun import usuario_out
from seguridad import crear_token, usuario_actual, verificar_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Un hash válido de una contraseña que nadie conoce: se verifica contra él cuando el usuario no
# existe, para que tardar lo mismo no delate si el usuario existe o no.
_HASH_FALSO = "$2b$04$C6UzMDM.H6dfI/f/IKcEeO5zJ1Hk8Q3nJmY2cBvX0lE3Q9uZyqKqW"


@router.post("/login", response_model=TokenOut)
def login(datos: LoginIn, db: Session = Depends(get_db)):
    empresa = db.query(Empresa).filter_by(codigo_acceso=datos.codigo_empresa.strip().upper()).one_or_none()
    usuario = (db.query(Usuario).filter_by(empresa_id=empresa.id, username=datos.username.strip()).one_or_none()
               if empresa is not None else None)
    correcto = verificar_password(datos.password, usuario.password_hash if usuario else _HASH_FALSO)
    if usuario is None or not correcto or not usuario.activo:
        raise HTTPException(status_code=401, detail="Código, usuario o contraseña incorrectos.")
    return TokenOut(access_token=crear_token(usuario), usuario=usuario_out(usuario))


@router.get("/yo", response_model=UsuarioOut)
def yo(usuario: Usuario = Depends(usuario_actual)):
    return usuario_out(usuario)
