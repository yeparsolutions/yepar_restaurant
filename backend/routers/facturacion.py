# ============================================================
# YEPAR RESTAURANT — backend/routers/facturacion.py
# Facturación electrónica: conectar YeparDTE (Chile) o YeparFactura
# (Venezuela) y emitir la boleta/factura de una cuenta pagada.
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from esquemas import (ConexionFacturacionIn, ConexionFacturacionOut, DocumentoOut, EmitirDocumentoIn)
from models import EstadoDocumento, ProveedorFacturacion, RolUsuario, TipoDocumento, Usuario
from seguridad import exigir_roles
from servicios.facturacion import emision as svc

router = APIRouter(tags=["facturación"])

solo_admin = exigir_roles()
solo_caja = exigir_roles(RolUsuario.cajero)


def documento_out(d) -> DocumentoOut:
    return DocumentoOut(
        id=d.id, pedido_id=d.pedido_id, proveedor=d.proveedor.value, tipo=d.tipo.value, estado=d.estado.value,
        folio=d.folio, neto=d.neto, iva=d.iva, total=d.total, pdf_url=d.pdf_url, moneda=d.moneda,
        tasa_cambio=d.tasa_cambio, intentos=d.intentos, ultimo_error=d.ultimo_error)


def conexion_out(integ) -> ConexionFacturacionOut:
    return ConexionFacturacionOut(proveedor=integ.proveedor.value, activo=integ.activo, api_key_final=svc.api_key_final(integ))


# ── Conexión con el facturador ───────────────────────────────
@router.put("/facturacion/conexion", response_model=ConexionFacturacionOut)
def conectar(datos: ConexionFacturacionIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """El administrador pega la API Key de su facturador; se valida al instante y se guarda cifrada."""
    integ = svc.conectar(db, empresa_id=usuario.empresa_id, proveedor=ProveedorFacturacion(datos.proveedor),
                         api_key=datos.api_key)
    db.commit()
    return conexion_out(integ)


@router.get("/facturacion/conexion", response_model=ConexionFacturacionOut)
def ver_conexion(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    return conexion_out(svc.integracion_activa(db, usuario.empresa_id))


@router.delete("/facturacion/conexion", status_code=204)
def desconectar(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    svc.desconectar(db, empresa_id=usuario.empresa_id)
    db.commit()


# ── Documentos ───────────────────────────────────────────────
@router.post("/pedidos/{pedido_id}/documento", response_model=DocumentoOut, status_code=201)
def emitir(pedido_id: str, datos: EmitirDocumentoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    """
    Emite la boleta/factura de una cuenta pagada. Repetirlo es seguro (no duplica el folio).
    Respuestas: 201 emitido · 202 pendiente (el facturador no respondió; se reintenta) · 422 rechazado.
    """
    doc = svc.emitir_documento(
        db, empresa_id=usuario.empresa_id, usuario_id=usuario.id, pedido_id=pedido_id, tipo=TipoDocumento(datos.tipo),
        receptor=datos.receptor.model_dump(exclude_none=True) if datos.receptor else None, tasa_cambio=datos.tasa_cambio)
    db.commit()                                  # el intento queda registrado aunque haya fallado
    salida = documento_out(doc)
    if doc.estado == EstadoDocumento.rechazado:
        raise HTTPException(status_code=422, detail=doc.ultimo_error or "El facturador rechazó el documento.")
    if doc.estado == EstadoDocumento.pendiente:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=202, content=salida.model_dump(mode="json"))
    return salida


@router.get("/pedidos/{pedido_id}/documento", response_model=DocumentoOut)
def ver_documento(pedido_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    return documento_out(svc.documento_de_pedido(db, empresa_id=usuario.empresa_id, pedido_id=pedido_id))


@router.get("/documentos", response_model=list[DocumentoOut])
def listar(estado: Optional[EstadoDocumento] = None, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    return [documento_out(d) for d in svc.listar_documentos(db, empresa_id=usuario.empresa_id, estado=estado)]


@router.post("/documentos/reintentar", response_model=list[DocumentoOut])
def reintentar(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    """Reintenta los documentos pendientes (al volver la conexión). No duplica folios."""
    docs = svc.reintentar_pendientes(db, empresa_id=usuario.empresa_id)
    db.commit()
    return [documento_out(d) for d in docs]
