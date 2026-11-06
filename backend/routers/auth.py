# ============================================================
# YEPAR RESTAURANT — backend/routers/auth.py
# Inicio de sesión. Cada restaurante entra con su código de acceso
# (la app es multi-cliente) más su usuario y contraseña.
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from esquemas import CorreoIn, LoginIn, TokenOut, UsuarioOut
from models import Empresa, Usuario
from errores import ErrorNoEncontrado
from routers.comun import usuario_out
from seguridad import crear_token, usuario_actual, verificar_password
from servicios import acceso

router = APIRouter(prefix="/auth", tags=["auth"])

# Un hash válido de una contraseña que nadie conoce: se verifica contra él cuando el usuario no
# existe, para que tardar lo mismo no delate si el usuario existe o no.
_HASH_FALSO = "$2b$04$C6UzMDM.H6dfI/f/IKcEeO5zJ1Hk8Q3nJmY2cBvX0lE3Q9uZyqKqW"


def _buscar_para_login(datos: LoginIn, db: Session) -> tuple[Optional[Usuario], str]:
    """Quién intenta entrar, según la forma usada, y el mensaje de error que corresponde a esa forma."""
    if datos.email:
        return acceso.usuario_por_correo(db, datos.email), "Correo o contraseña incorrectos."
    if datos.vinculo:
        try:
            empresa = acceso.empresa_de_vinculo(db, datos.vinculo)
        except ErrorNoEncontrado:
            empresa = None
        mensaje = "Nombre o contraseña incorrectos."
    else:
        empresa = db.query(Empresa).filter_by(codigo_acceso=(datos.codigo_empresa or "").strip().upper()).one_or_none()
        mensaje = "Código, usuario o contraseña incorrectos."
    if empresa is None:
        return None, mensaje
    return db.query(Usuario).filter_by(empresa_id=empresa.id, username=(datos.username or "").strip()).one_or_none(), mensaje


@router.post("/login", response_model=TokenOut)
def login(datos: LoginIn, db: Session = Depends(get_db)):
    usuario, mensaje = _buscar_para_login(datos, db)
    correcto = verificar_password(datos.password, usuario.password_hash if usuario else _HASH_FALSO)
    if usuario is None or not correcto or not usuario.activo:
        raise HTTPException(status_code=401, detail=mensaje)
    return TokenOut(access_token=crear_token(usuario), usuario=usuario_out(usuario))


@router.post("/correo", response_model=UsuarioOut)
def poner_mi_correo(datos: CorreoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    """Cada persona puede registrar su correo (con su clave) para entrar con él, sin código."""
    if not verificar_password(datos.password, usuario.password_hash):
        raise HTTPException(status_code=401, detail="La contraseña no es correcta.")
    acceso.poner_correo(db, usuario, datos.email)
    db.commit()
    return usuario_out(usuario)


@router.get("/yo", response_model=UsuarioOut)
def yo(usuario: Usuario = Depends(usuario_actual)):
    return usuario_out(usuario)
