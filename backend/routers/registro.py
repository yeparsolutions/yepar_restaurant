# ============================================================
# YEPAR RESTAURANT — backend/routers/registro.py
# Registro público: el dueño crea su restaurante desde la web (restaurante + primera sucursal + administrador)
# y queda con la sesión iniciada. Es lo mismo que hace crear_restaurante.py, pero abierto por internet.
#
# Como cualquiera puede llamarlo, lleva dos candados:
#   · REGISTRO_ABIERTO=0 lo cierra del todo (para cuando solo Yepar da de alta clientes).
#   · Un tope de altas por hora y por dirección de red, para que nadie llene la base de restaurantes falsos.
#
# Analogía: es la ventanilla de "clientes nuevos" a la entrada del edificio. Se puede cerrar con llave,
# y el guardia no deja pasar a la misma persona cien veces seguidas.
# ============================================================

import os
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy.orm import Session

from database import get_db
from errores import ErrorNegocio
from esquemas import Entrada, TokenOut
from pydantic import BaseModel
from routers.comun import usuario_out
from semilla import sembrar_unidades
from seguridad import crear_token
from servicios.equipo import crear_restaurante

router = APIRouter(tags=["registro"])

_VENTANA_SEGUNDOS = 3600
_intentos: dict[str, deque] = defaultdict(deque)       # dirección → momentos de sus altas recientes


class RegistroIn(Entrada):
    nombre_restaurante: str = Field(min_length=1, max_length=120)
    sucursal: str = Field(default="Casa matriz", min_length=1, max_length=120)
    admin_nombre: str = Field(min_length=1, max_length=120)
    admin_usuario: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)
    pais: str = Field(default="CL", min_length=2, max_length=2)
    moneda: str = Field(default="CLP", min_length=3, max_length=3)


class RegistroOut(TokenOut):
    codigo_acceso: str            # el código con el que todo el equipo entra al restaurante


def _registro_abierto() -> bool:
    return os.environ.get("REGISTRO_ABIERTO", "1").strip().lower() not in ("0", "false", "no", "")


def _tope_por_hora() -> int:
    return int(os.environ.get("REGISTRO_MAX_POR_HORA", "5"))


def _direccion(request: Request) -> str:
    """Detrás del proxy de Railway la dirección real viene en X-Forwarded-For (la primera es la del cliente)."""
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "desconocida"


def _controlar_ritmo(direccion: str) -> None:
    ahora = time.monotonic()
    cola = _intentos[direccion]
    while cola and ahora - cola[0] > _VENTANA_SEGUNDOS:
        cola.popleft()
    if len(cola) >= _tope_por_hora():
        raise HTTPException(status_code=429, detail="Demasiados registros desde esta conexión. Intenta más tarde.")
    cola.append(ahora)


@router.get("/registro/estado")
def estado_registro():
    """La web lo consulta para saber si muestra el botón «Crear mi restaurante»."""
    return {"abierto": _registro_abierto()}


@router.post("/registro", response_model=RegistroOut, status_code=201)
def registrar(datos: RegistroIn, request: Request, db: Session = Depends(get_db)):
    if not _registro_abierto():
        raise HTTPException(status_code=403, detail="El registro está cerrado. Pide el alta a Yepar.")
    _controlar_ritmo(_direccion(request))
    sembrar_unidades(db)                                   # sin las unidades (g, kg, ml…) nada funciona
    try:
        empresa, _sucursal, admin = crear_restaurante(
            db, nombre=datos.nombre_restaurante, sucursal=datos.sucursal, admin_nombre=datos.admin_nombre,
            admin_usuario=datos.admin_usuario, admin_password=datos.password, pais=datos.pais, moneda=datos.moneda)
    except ErrorNegocio:
        db.rollback()                                      # que no quede un restaurante a medio crear
        raise
    db.commit()
    return RegistroOut(access_token=crear_token(admin), usuario=usuario_out(admin), codigo_acceso=empresa.codigo_acceso)
