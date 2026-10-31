# ============================================================
# YEPAR RESTAURANT — backend/routers/sync.py
# Subida de lo que la tablet del mesero hizo sin conexión.
# Para BAJAR datos (plano, carta) la tablet usa GET /mesas y GET /carta.
# ============================================================

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from esquemas import SincronizarIn, SincronizarOut
from models import RolUsuario, Usuario
from seguridad import exigir_roles
from servicios import sincronizacion as svc

router = APIRouter(prefix="/sync", tags=["sincronización"])


@router.post("/operaciones", response_model=SincronizarOut)
def subir(datos: SincronizarIn, db: Session = Depends(get_db),
          usuario: Usuario = Depends(exigir_roles(RolUsuario.mesero))):
    """
    Aplica en orden las operaciones del mesero. Responde 200 aunque alguna se rechace: cada resultado dice
    `aplicada` o `rechazada` (con el motivo). Reenviar el mismo `op_id` devuelve el resultado anterior.
    """
    resultados = svc.sincronizar(db, usuario, [o.model_dump() for o in datos.operaciones])
    aplicadas = sum(1 for r in resultados if r["estado"] == "aplicada")
    return SincronizarOut(resultados=resultados, aplicadas=aplicadas, rechazadas=len(resultados) - aplicadas)
