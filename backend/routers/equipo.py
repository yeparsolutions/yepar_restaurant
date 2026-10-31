# ============================================================
# YEPAR RESTAURANT — backend/routers/equipo.py
# Sucursales y personal (solo administrador) y cambio de contraseña propio.
# ============================================================

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from database import get_db
from esquemas import (CambiarPasswordIn, PasswordNuevaIn, PersonaCambiosIn, PersonaIn, PersonaOut, SucursalIn,
                      SucursalOut)
from models import Sucursal, Usuario
from seguridad import exigir_roles, usuario_actual
from servicios import equipo as svc

router = APIRouter(tags=["equipo"])

solo_admin = exigir_roles()


def persona_out(u: Usuario) -> PersonaOut:
    return PersonaOut(id=u.id, nombre=u.nombre, username=u.username, roles=sorted(r.rol.value for r in u.roles),
                      sucursal_id=u.sucursal_id, estacion=u.estacion.value if u.estacion else None,
                      descuento_max_pct=u.descuento_max_pct, activo=u.activo, tiene_pin=bool(u.pin_hash))


def sucursal_out(s: Sucursal) -> SucursalOut:
    return SucursalOut(id=s.id, nombre=s.nombre)


# ── Sucursales ───────────────────────────────────────────────
@router.get("/sucursales", response_model=list[SucursalOut])
def listar_sucursales(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    return [sucursal_out(s) for s in svc.listar_sucursales(db, usuario.empresa_id)]


@router.post("/sucursales", response_model=SucursalOut, status_code=201)
def crear_sucursal(datos: SucursalIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    s = svc.crear_sucursal(db, empresa_id=usuario.empresa_id, nombre=datos.nombre)
    db.commit()
    return sucursal_out(s)


@router.patch("/sucursales/{sucursal_id}", response_model=SucursalOut)
def renombrar_sucursal(sucursal_id: int, datos: SucursalIn, db: Session = Depends(get_db),
                       usuario: Usuario = Depends(solo_admin)):
    s = svc.renombrar_sucursal(db, empresa_id=usuario.empresa_id, sucursal_id=sucursal_id, nombre=datos.nombre)
    db.commit()
    return sucursal_out(s)


# ── Personal ─────────────────────────────────────────────────
@router.get("/personal", response_model=list[PersonaOut])
def listar_personal(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    return [persona_out(u) for u in svc.listar_personal(db, usuario.empresa_id)]


@router.post("/personal", response_model=PersonaOut, status_code=201)
def crear_persona(datos: PersonaIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    u = svc.crear_persona(db, empresa_id=usuario.empresa_id, **datos.model_dump())
    db.commit()
    return persona_out(u)


@router.patch("/personal/{usuario_id}", response_model=PersonaOut)
def actualizar_persona(usuario_id: int, datos: PersonaCambiosIn, db: Session = Depends(get_db),
                       usuario: Usuario = Depends(solo_admin)):
    """Cambia solo lo enviado (rol, local, estación, tope de descuento) o da de baja con `activo: false`."""
    u = svc.actualizar_persona(db, empresa_id=usuario.empresa_id, usuario_id=usuario_id,
                               cambios=datos.model_dump(exclude_unset=True))
    db.commit()
    return persona_out(u)


@router.post("/personal/{usuario_id}/password", status_code=204)
def restablecer_password(usuario_id: int, datos: PasswordNuevaIn, db: Session = Depends(get_db),
                         usuario: Usuario = Depends(solo_admin)):
    svc.restablecer_password(db, empresa_id=usuario.empresa_id, usuario_id=usuario_id, password=datos.password)
    db.commit()
    return Response(status_code=204)


@router.post("/auth/cambiar-password", status_code=204)
def cambiar_password(datos: CambiarPasswordIn, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    """Cualquier persona del equipo cambia su propia contraseña."""
    svc.cambiar_password(db, usuario, actual=datos.actual, nueva=datos.nueva)
    db.commit()
    return Response(status_code=204)
