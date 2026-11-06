# ============================================================
# YEPAR RESTAURANT — backend/routers/acceso.py
# Vinculación de tablets: el administrador genera un enlace, la tablet lo abre una vez y queda recordada.
# Después el personal solo toca su nombre. Si se pierde una tablet, se desvinculan todas de un golpe.
# ============================================================

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from database import get_db
from esquemas import PersonaTabletOut, TabletOut, VinculoOut
from models import Empresa, Usuario
from seguridad import exigir_roles
from servicios import acceso

router = APIRouter(prefix="/acceso", tags=["acceso"])
solo_admin = exigir_roles()


@router.post("/vinculo", response_model=VinculoOut, status_code=201)
def crear_vinculo(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """El enlace para vincular una tablet. Sirve para todas las tablets del restaurante hasta que se desvinculen."""
    return VinculoOut(token=acceso.crear_vinculo(db.get(Empresa, usuario.empresa_id)))


@router.delete("/vinculos", status_code=204)
def desvincular_todas(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """Todas las tablets vinculadas y todos los enlaces entregados dejan de funcionar."""
    acceso.revocar_vinculos(db, db.get(Empresa, usuario.empresa_id))
    db.commit()
    return Response(status_code=204)


@router.get("/vinculo/{token}", response_model=TabletOut)
def ver_vinculo(token: str, db: Session = Depends(get_db)):
    """Público (lo abre la tablet): confirma que el enlace sirve y muestra quién del equipo puede entrar."""
    empresa = acceso.empresa_de_vinculo(db, token)
    return TabletOut(
        restaurante=empresa.nombre,
        personal=[PersonaTabletOut(nombre=u.nombre, username=u.username, roles=sorted(r.rol.value for r in u.roles),
                                   estacion=u.estacion.value if u.estacion else None)
                  for u in acceso.personal_de_tablet(db, empresa.id)])
