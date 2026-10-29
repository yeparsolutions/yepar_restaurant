# ============================================================
# YEPAR RESTAURANT — backend/routers/cocina.py
# Lo que usa el COCINERO y el BARMAN: pantalla de comandas,
# empezar, marcar listo y el botón "se acabó".
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from esquemas import AgotadoOut, ComandaOut, LineaOut, ListoOut
from models import EstacionCocina, RolUsuario, Usuario
from routers.comun import linea_out
from seguridad import exigir_roles, resolver_sucursal
from servicios import cocina as svc_cocina

router = APIRouter(prefix="/cocina", tags=["cocina"])

solo_cocina = exigir_roles(RolUsuario.cocinero)


@router.get("/comandas", response_model=list[ComandaOut])
def comandas(estacion: Optional[EstacionCocina] = Query(default=None), sucursal_id: Optional[int] = Query(default=None),
             db: Session = Depends(get_db), usuario: Usuario = Depends(solo_cocina)):
    """
    La pantalla de comandas. Un cocinero con estación fija ve solo la suya
    (el barman, la barra); el administrador puede elegir con `estacion`.
    """
    if usuario.estacion is not None and RolUsuario.administrador not in {r.rol for r in usuario.roles}:
        estacion = usuario.estacion
    lista = svc_cocina.comandas_pendientes(db, empresa_id=usuario.empresa_id,
                                           sucursal_id=resolver_sucursal(usuario, sucursal_id), estacion=estacion)
    return [ComandaOut(**{**c.__dict__, "estado": c.estado.value}) for c in lista]


@router.post("/lineas/{linea_id}/iniciar", response_model=LineaOut)
def iniciar(linea_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_cocina)):
    """El cocinero toma la comanda (pasa a 'en preparación')."""
    linea = svc_cocina.iniciar_preparacion(db, empresa_id=usuario.empresa_id, linea_id=linea_id,
                                           usuario_id=usuario.id)
    db.commit()
    return linea_out(linea)


@router.post("/lineas/{linea_id}/lista", response_model=ListoOut)
def lista(linea_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_cocina)):
    """La campanita: el plato está listo. Descuenta el stock y enciende la mesa del mesero."""
    r = svc_cocina.marcar_lista(db, empresa_id=usuario.empresa_id, linea_id=linea_id, usuario_id=usuario.id)
    db.commit()
    return ListoOut(linea=linea_out(r.linea), sin_stock=r.sin_stock)


@router.post("/items/{item_id}/agotado", response_model=AgotadoOut)
def agotar(item_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_cocina)):
    """Botón 'se acabó': deja agotados para el mesero los platos que lo usan."""
    platos = svc_cocina.marcar_agotado(db, empresa_id=usuario.empresa_id, item_id=item_id, usuario_id=usuario.id)
    db.commit()
    return AgotadoOut(platos_agotados=platos)


@router.delete("/items/{item_id}/agotado", status_code=204)
def reponer(item_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_cocina)):
    svc_cocina.reponer_agotado(db, empresa_id=usuario.empresa_id, item_id=item_id, usuario_id=usuario.id)
    db.commit()
