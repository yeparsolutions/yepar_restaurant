# ============================================================
# YEPAR RESTAURANT — backend/routers/carga_masiva.py
# Carga masiva por Excel y asistente de arranque (solo administrador).
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from errores import ErrorNegocio
from esquemas import AsistenteOut, ErrorFilaOut, PasoArranqueOut, ReporteCargaOut
from models import Usuario
from seguridad import exigir_roles, resolver_sucursal
from servicios import carga_masiva as svc

router = APIRouter(prefix="/carga-masiva", tags=["carga masiva"])

solo_admin = exigir_roles()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def reporte_out(rep: svc.Reporte, aplicado: bool) -> ReporteCargaOut:
    return ReporteCargaOut(
        valido=rep.valido, aplicado=aplicado, insumos=rep.insumos, platos=rep.platos, recetas=rep.recetas,
        con_stock_inicial=rep.con_stock_inicial, categorias_nuevas=rep.categorias_nuevas,
        errores=[ErrorFilaOut(hoja=e.hoja, fila=e.fila, mensaje=e.mensaje) for e in rep.errores])


async def _procesar(archivo: UploadFile, sucursal_id: Optional[int], db: Session, usuario: Usuario):
    contenido = await archivo.read(svc.MAX_BYTES + 1)
    if not (archivo.filename or "").lower().endswith(".xlsx"):
        raise ErrorNegocio("Sube un archivo Excel .xlsx (descarga la plantilla).")
    try:
        sucursal = resolver_sucursal(usuario, sucursal_id)
    except Exception:
        sucursal = None                      # sin sucursal solo falla si la planilla trae stock inicial
    return svc.procesar(db, empresa_id=usuario.empresa_id, sucursal_id=sucursal, contenido=contenido)


@router.get("/plantilla")
def plantilla(usuario: Usuario = Depends(solo_admin)):
    return Response(content=svc.plantilla_xlsx(), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="plantilla_yepar_restaurant.xlsx"'})


@router.post("/validar", response_model=ReporteCargaOut)
async def validar(archivo: UploadFile = File(...), sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
                  usuario: Usuario = Depends(solo_admin)):
    """Revisa la planilla completa y dice qué entraría y qué falla. No guarda nada."""
    try:
        rep = await _procesar(archivo, sucursal_id, db, usuario)
    finally:
        db.rollback()
    return reporte_out(rep, aplicado=False)


@router.post("/importar", response_model=ReporteCargaOut, status_code=201)
async def importar(archivo: UploadFile = File(...), sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
                   usuario: Usuario = Depends(solo_admin)):
    """Importa todo o nada: con un solo error no se guarda nada y se responde 422 con las filas con problema."""
    try:
        rep = await _procesar(archivo, sucursal_id, db, usuario)
    except Exception:
        db.rollback()
        raise
    if not rep.valido:
        db.rollback()
        cuerpo = reporte_out(rep, aplicado=False).model_dump()
        cuerpo["detalle"] = f"La planilla tiene {len(rep.errores)} error(es): no se guardó nada."
        return JSONResponse(status_code=422, content=cuerpo)
    db.commit()
    return reporte_out(rep, aplicado=True)


@router.get("/asistente", response_model=AsistenteOut)
def asistente(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """Los pasos para dejar el restaurante andando, marcando lo que ya está hecho."""
    pasos = svc.estado_arranque(db, usuario.empresa_id)
    pendiente = next((p for p in pasos if not p["hecho"]), None)
    return AsistenteOut(pasos=[PasoArranqueOut(**p) for p in pasos], completados=sum(p["hecho"] for p in pasos),
                        total=len(pasos), siguiente=pendiente["titulo"] if pendiente else None)
