# ============================================================
# YEPAR RESTAURANT — backend/routers/conteo.py
# Inventario físico ciego. El cocinero cuenta sin ver el stock del sistema;
# el administrador abre, revisa diferencias, pide recuentos y cierra.
# ============================================================

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from errores import ErrorNoEncontrado
from esquemas import (CierreInventarioOut, ConteoCiegoOut, ConteoIn, InventarioNuevoIn, InventarioResumenOut,
                      LineaCiegaOut, LineaRevisionOut, RecuentoIn, RevisionOut)
from models import EstadoInventarioFisico as E, InventarioFisico, RolUsuario, Usuario
from routers.recepcion import presentaciones_ciegas
from seguridad import es_admin, exigir_roles, resolver_sucursal
from servicios import conteo as svc

router = APIRouter(prefix="/inventario-fisico", tags=["inventario físico"])

solo_admin = exigir_roles()
admin_o_cocina = exigir_roles(RolUsuario.cocinero)


def resumen(inv: InventarioFisico) -> InventarioResumenOut:
    return InventarioResumenOut(
        id=inv.id, sucursal_id=inv.sucursal_id, estado=inv.estado.value, categoria_id=inv.alcance_categoria_id,
        nota=inv.nota, total_items=len(inv.lineas), contados=sum(1 for l in inv.lineas if l.cantidad_contada is not None))


def ciego(inv: InventarioFisico) -> ConteoCiegoOut:
    """Lo que ve quien cuenta: nombre, unidad y lo que él mismo ya anotó. Nada del sistema."""
    return ConteoCiegoOut(
        id=inv.id, estado=inv.estado.value, total_items=len(inv.lineas),
        contados=sum(1 for l in inv.lineas if l.cantidad_contada is not None),
        lineas=[LineaCiegaOut(item_id=l.item_id, item=l.item.nombre, unidad_base=l.item.unidad_base.codigo,
                              presentaciones=presentaciones_ciegas(l.item), contada=l.cantidad_contada)
                for l in inv.lineas])


@router.post("", response_model=InventarioResumenOut, status_code=201)
def abrir(datos: InventarioNuevoIn, sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
          usuario: Usuario = Depends(solo_admin)):
    inv = svc.abrir_inventario(db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id),
                               categoria_id=datos.categoria_id, nota=datos.nota, usuario_id=usuario.id)
    db.commit()
    return resumen(inv)


@router.get("", response_model=list[InventarioResumenOut])
def listar(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    q = db.query(InventarioFisico).filter_by(empresa_id=usuario.empresa_id).order_by(InventarioFisico.id.desc())
    return [resumen(i) for i in q.all()]


@router.get("/activo", response_model=ConteoCiegoOut)
def activo(sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
           usuario: Usuario = Depends(admin_o_cocina)):
    """La hoja de conteo del local (a ciegas). 404 si no hay inventario esperando conteo."""
    inv = svc.inventario_activo(db, usuario.empresa_id, resolver_sucursal(usuario, sucursal_id))
    if inv is None or inv.estado != E.contando:
        raise ErrorNoEncontrado("No hay un inventario esperando conteo.")
    return ciego(inv)


@router.post("/{inventario_id}/contar", response_model=ConteoCiegoOut)
def contar(inventario_id: int, datos: ConteoIn, db: Session = Depends(get_db),
           usuario: Usuario = Depends(admin_o_cocina)):
    inv = svc.cargar_inventario(db, usuario.empresa_id, inventario_id, _local(usuario))
    svc.contar_item(db, inv, usuario_id=usuario.id, **datos.model_dump())
    db.commit()
    return ciego(inv)


@router.post("/{inventario_id}/finalizar-conteo", response_model=ConteoCiegoOut)
def finalizar(inventario_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(admin_o_cocina)):
    inv = svc.cargar_inventario(db, usuario.empresa_id, inventario_id, _local(usuario))
    svc.finalizar_conteo(db, inv)
    db.commit()
    return ciego(inv)


@router.get("/{inventario_id}/revision", response_model=RevisionOut)
def revision(inventario_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """Sistema vs. contado, con la diferencia y su valor. Recién acá se ve el stock del sistema."""
    inv = svc.cargar_inventario(db, usuario.empresa_id, inventario_id)
    lineas, total, con_dif = [], Decimal("0"), 0
    for l in inv.lineas:
        dif = svc.diferencia(l) if l.cantidad_contada is not None else Decimal("0")
        valor = dif * l.costo_referencia
        total += valor
        con_dif += 1 if dif != 0 else 0
        lineas.append(LineaRevisionOut(
            item_id=l.item_id, item=l.item.nombre, unidad_base=l.item.unidad_base.codigo,
            cantidad_sistema=l.cantidad_sistema, cantidad_contada=l.cantidad_contada, diferencia=dif,
            valor_diferencia=valor.quantize(Decimal("0.01"))))
    return RevisionOut(id=inv.id, estado=inv.estado.value, lineas=lineas, con_diferencia=con_dif,
                       valor_total_diferencia=total.quantize(Decimal("0.01")))


@router.post("/{inventario_id}/recontar", response_model=InventarioResumenOut)
def recontar(inventario_id: int, datos: RecuentoIn, db: Session = Depends(get_db),
             usuario: Usuario = Depends(solo_admin)):
    inv = svc.cargar_inventario(db, usuario.empresa_id, inventario_id)
    svc.pedir_recuento(db, inv, datos.item_ids)
    db.commit()
    return resumen(inv)


@router.post("/{inventario_id}/cerrar", response_model=CierreInventarioOut)
def cerrar(inventario_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    inv = svc.cargar_inventario(db, usuario.empresa_id, inventario_id)
    ajustes = svc.cerrar_inventario(db, inv, usuario.id)
    db.commit()
    return CierreInventarioOut(id=inv.id, estado=inv.estado.value, ajustes=ajustes)


@router.post("/{inventario_id}/cancelar", response_model=InventarioResumenOut)
def cancelar(inventario_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    inv = svc.cargar_inventario(db, usuario.empresa_id, inventario_id)
    svc.cancelar_inventario(db, inv)
    db.commit()
    return resumen(inv)


def _local(usuario: Usuario) -> Optional[int]:
    """El personal de un local solo toca los inventarios de su local; el administrador, todos."""
    return None if es_admin(usuario) else usuario.sucursal_id
