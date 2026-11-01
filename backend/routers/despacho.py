# ============================================================
# YEPAR RESTAURANT — backend/routers/despacho.py
# Delivery con Yepar Go: conectar la cuenta (administrador), pedir el reparto de una cuenta
# (cajero, mesero en sus cuentas o administrador) y seguir las entregas.
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from esquemas import (CentroRetiroOut, ConexionDespachoIn, ConexionDespachoOut, DespachoIn, DespachoOut)
from models import Despacho, EstadoDespacho, RolUsuario, Usuario
from routers.comun import exigir_ser_el_mesero
from seguridad import exigir_roles, roles_de
from servicios import despacho as svc
from servicios import pedidos as svc_pedidos

router = APIRouter(tags=["delivery"])

solo_admin = exigir_roles()
personal_de_sala = exigir_roles(RolUsuario.cajero, RolUsuario.mesero)
solo_caja = exigir_roles(RolUsuario.cajero)


def despacho_out(d: Despacho) -> DespachoOut:
    return DespachoOut(id=d.id, pedido_id=d.pedido_id, estado=d.estado.value, destinatario=d.destinatario,
                       direccion=d.direccion, telefono=d.telefono, go_numero=d.go_numero, estado_go=d.estado_go,
                       seguimiento_url=d.seguimiento_url, intentos=d.intentos, ultimo_error=d.ultimo_error)


def conexion_out(integ) -> ConexionDespachoOut:
    return ConexionDespachoOut(activo=integ.activo, api_key_final=svc.api_key_final(integ),
                               direccion_retiro=integ.direccion_retiro, centro_retiro_id=integ.centro_retiro_id)


# ── Conexión con Yepar Go ────────────────────────────────────
@router.put("/despacho/conexion", response_model=ConexionDespachoOut)
def conectar(datos: ConexionDespachoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """El administrador pega la API Key de Yepar Go; se valida al instante y se guarda cifrada."""
    integ = svc.conectar(db, empresa_id=usuario.empresa_id, **datos.model_dump())
    db.commit()
    return conexion_out(integ)


@router.get("/despacho/conexion", response_model=ConexionDespachoOut)
def ver_conexion(db: Session = Depends(get_db), usuario: Usuario = Depends(personal_de_sala)):
    return conexion_out(svc.integracion_activa(db, usuario.empresa_id))


@router.delete("/despacho/conexion", status_code=204)
def desconectar(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    svc.desconectar(db, empresa_id=usuario.empresa_id)
    db.commit()


@router.get("/despacho/centros-retiro", response_model=list[CentroRetiroOut])
def centros(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """Los centros de retiro de tu cuenta de Yepar Go (para elegir cuál usar al conectar)."""
    return [CentroRetiroOut(id=c.get("id"), nombre=c.get("name") or "", direccion=c.get("address"))
            for c in svc.centros_de_retiro(db, usuario.empresa_id)]


# ── Despachos ────────────────────────────────────────────────
@router.post("/pedidos/{pedido_id}/despacho", response_model=DespachoOut, status_code=201)
def pedir_reparto(pedido_id: str, datos: DespachoIn, db: Session = Depends(get_db),
                  usuario: Usuario = Depends(personal_de_sala)):
    """
    Pide a Yepar Go el reparto de una cuenta. Repetirlo es seguro (no pide otro motorista).
    Respuestas: 201 creado (con el link de seguimiento) · 202 pendiente (Yepar Go no respondió; se reintenta) ·
    422 rechazado (con el motivo).
    """
    if RolUsuario.cajero not in roles_de(usuario):
        exigir_ser_el_mesero(usuario, svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id))
    d = svc.crear_despacho(db, empresa_id=usuario.empresa_id, usuario_id=usuario.id, pedido_id=pedido_id,
                           **datos.model_dump())
    db.commit()                                   # el intento queda registrado aunque haya fallado
    if d.estado == EstadoDespacho.rechazado:
        raise HTTPException(status_code=422, detail=d.ultimo_error or "Yepar Go rechazó el despacho.")
    if d.estado == EstadoDespacho.pendiente:
        return JSONResponse(status_code=202, content=despacho_out(d).model_dump(mode="json"))
    return despacho_out(d)


@router.get("/pedidos/{pedido_id}/despacho", response_model=DespachoOut)
def ver_despacho(pedido_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(personal_de_sala)):
    return despacho_out(svc.despacho_de_pedido(db, empresa_id=usuario.empresa_id, pedido_id=pedido_id))


@router.get("/despachos", response_model=list[DespachoOut])
def listar(estado: Optional[str] = None, en_curso: bool = False, db: Session = Depends(get_db),
           usuario: Usuario = Depends(solo_caja)):
    """Los despachos del restaurante. `en_curso=true`: solo los que siguen en la calle."""
    return [despacho_out(d) for d in svc.listar(
        db, empresa_id=usuario.empresa_id, estado=EstadoDespacho(estado) if estado else None, solo_en_curso=en_curso)]


@router.post("/despachos/actualizar", response_model=list[DespachoOut])
def actualizar_todos(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    """Consulta a Yepar Go cómo van todas las entregas en curso."""
    r = [despacho_out(d) for d in svc.actualizar_estado(db, empresa_id=usuario.empresa_id)]
    db.commit()
    return r


@router.post("/despachos/{despacho_id}/actualizar", response_model=DespachoOut)
def actualizar_uno(despacho_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    d = svc.actualizar_estado(db, empresa_id=usuario.empresa_id, despacho_id=despacho_id)[0]
    db.commit()
    return despacho_out(d)


@router.post("/despachos/reintentar", response_model=list[DespachoOut])
def reintentar(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    """Vuelve a pedir los despachos que Yepar Go no alcanzó a confirmar."""
    r = [despacho_out(d) for d in svc.reintentar_pendientes(db, empresa_id=usuario.empresa_id)]
    db.commit()
    return r
