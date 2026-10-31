# ============================================================
# YEPAR RESTAURANT — backend/routers/supervisor.py
# PIN de supervisor: el administrador lo define; el cajero ve a quién puede llamar.
# El PIN se usa al aplicar un descuento sobre el tope (POST /pedidos/{id}/descuento).
# ============================================================

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from database import get_db
from esquemas import PinIn, SupervisorOut
from models import RolUsuario, Usuario
from seguridad import exigir_roles
from servicios import supervisor as svc

router = APIRouter(tags=["supervisor"])

solo_admin = exigir_roles()
admin_o_cajero = exigir_roles(RolUsuario.cajero)


@router.put("/supervisor/pin", status_code=204)
def definir_pin(datos: PinIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """Crea o cambia tu PIN de supervisor (4 a 6 dígitos), confirmando con tu contraseña."""
    svc.definir_pin(db, usuario, pin=datos.pin, password=datos.password)
    db.commit()
    return Response(status_code=204)


@router.delete("/supervisor/pin", status_code=204)
def quitar_pin(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    svc.quitar_pin(db, usuario)
    db.commit()
    return Response(status_code=204)


@router.get("/supervisores", response_model=list[SupervisorOut])
def supervisores(db: Session = Depends(get_db), usuario: Usuario = Depends(admin_o_cajero)):
    """A quién puede llamar el cajero para autorizar un descuento (administradores con PIN)."""
    return [SupervisorOut(id=s.id, nombre=s.nombre) for s in svc.listar_supervisores(db, usuario.empresa_id)]
