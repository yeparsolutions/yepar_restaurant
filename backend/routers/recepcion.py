# ============================================================
# YEPAR RESTAURANT — backend/routers/recepcion.py
# Facturas de compra y recepción física a ciegas.
# Administrador: registra, revisa diferencias y anula. Cocinero: ve la lista CIEGA y cuenta lo que llegó.
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from esquemas import (CompraLineaOut, CompraRecepcionOut, CompraResumenOut, FacturaCompraIn, LineaCiegaOut,
                      PresentacionCiegaOut, RecepcionCiegaOut, RecepcionIn)
from models import Compra, EstadoCompra, RolUsuario, Usuario
from seguridad import es_admin, exigir_roles, resolver_sucursal
from servicios import recepcion as svc

router = APIRouter(prefix="/compras", tags=["recepción de mercadería"])

solo_admin = exigir_roles()
admin_o_cocina = exigir_roles(RolUsuario.cocinero)


def _local_del_usuario(usuario: Usuario) -> Optional[int]:
    """El personal de un local solo ve las compras de su local; el administrador ve todas."""
    return None if es_admin(usuario) else usuario.sucursal_id


def compra_out(c: Compra) -> CompraRecepcionOut:
    return CompraRecepcionOut(
        id=c.id, sucursal_id=c.sucursal_id, proveedor=c.proveedor, numero_documento=c.numero_documento,
        estado=c.estado.value, nota=c.nota,
        lineas=[CompraLineaOut(
            id=l.id, item_id=l.item_id, item=l.item.nombre, unidad_base=l.item.unidad_base.codigo,
            cantidad_facturada=l.cantidad_facturada, costo_unitario_base=l.costo_unitario_base,
            cantidad_recibida=l.cantidad_recibida,
            diferencia=None if l.cantidad_recibida is None else l.cantidad_recibida - l.cantidad_facturada)
            for l in c.lineas])


def presentaciones_ciegas(item) -> list[PresentacionCiegaOut]:
    return [PresentacionCiegaOut(id=p.id, nombre=p.nombre) for p in item.presentaciones]


@router.post("", response_model=CompraRecepcionOut, status_code=201)
def registrar(datos: FacturaCompraIn, sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
              usuario: Usuario = Depends(solo_admin)):
    """Primera llave: registra la factura del proveedor. No sube stock hasta que se reciba."""
    c = svc.registrar_compra(
        db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id),
        proveedor=datos.proveedor.strip(), numero_documento=datos.numero_documento, nota=datos.nota,
        lineas=[l.model_dump() for l in datos.lineas], usuario_id=usuario.id)
    db.commit()
    return compra_out(c)


@router.get("", response_model=list[CompraResumenOut])
def listar(estado: Optional[str] = None, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    q = db.query(Compra).filter(Compra.empresa_id == usuario.empresa_id)
    if estado:
        q = q.filter(Compra.estado == EstadoCompra(estado))
    return [CompraResumenOut(id=c.id, proveedor=c.proveedor, numero_documento=c.numero_documento,
                             estado=c.estado.value, lineas=len(c.lineas))
            for c in q.order_by(Compra.id.desc()).all()]


@router.get("/por-recibir", response_model=list[CompraResumenOut])
def por_recibir(db: Session = Depends(get_db), usuario: Usuario = Depends(admin_o_cocina)):
    """Lo que está esperando en la puerta (sin cantidades ni costos)."""
    q = db.query(Compra).filter(Compra.empresa_id == usuario.empresa_id, Compra.estado == EstadoCompra.por_recibir)
    if _local_del_usuario(usuario) is not None:
        q = q.filter(Compra.sucursal_id == usuario.sucursal_id)
    return [CompraResumenOut(id=c.id, proveedor=c.proveedor, numero_documento=None, estado=c.estado.value,
                             lineas=len(c.lineas))
            for c in q.order_by(Compra.id).all()]


@router.get("/{compra_id}/recepcion", response_model=RecepcionCiegaOut)
def hoja_ciega(compra_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(admin_o_cocina)):
    """La hoja para contar: qué ítems esperar, SIN cuánto dice la factura ni cuánto costó."""
    c = svc.cargar_compra(db, usuario.empresa_id, compra_id, _local_del_usuario(usuario))
    return RecepcionCiegaOut(id=c.id, proveedor=c.proveedor, lineas=[
        LineaCiegaOut(linea_id=l.id, item_id=l.item_id, item=l.item.nombre, unidad_base=l.item.unidad_base.codigo,
                      presentaciones=presentaciones_ciegas(l.item)) for l in c.lineas])


@router.post("/{compra_id}/recibir", response_model=CompraRecepcionOut)
def recibir(compra_id: int, datos: RecepcionIn, db: Session = Depends(get_db),
            usuario: Usuario = Depends(admin_o_cocina)):
    """Segunda llave: declara lo que llegó. El stock sube con lo contado, al costo de la factura."""
    c = svc.cargar_compra(db, usuario.empresa_id, compra_id, _local_del_usuario(usuario))
    svc.recibir_compra(db, empresa_id=usuario.empresa_id, compra=c,
                       recibidas=[l.model_dump() for l in datos.lineas], usuario_id=usuario.id)
    db.commit()
    # Quien recibe es el cocinero: no se le devuelven los montos de la factura (siguen a ciegas).
    if es_admin(usuario):
        return compra_out(c)
    return CompraRecepcionOut(id=c.id, sucursal_id=c.sucursal_id, proveedor=c.proveedor,
                              numero_documento=None, estado=c.estado.value, lineas=[])


@router.get("/{compra_id}", response_model=CompraRecepcionOut)
def ver(compra_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    """Factura vs. recibido, con la diferencia de cada línea."""
    return compra_out(svc.cargar_compra(db, usuario.empresa_id, compra_id))


@router.post("/{compra_id}/anular", response_model=CompraRecepcionOut)
def anular(compra_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    c = svc.cargar_compra(db, usuario.empresa_id, compra_id)
    svc.anular_compra(db, c)
    db.commit()
    return compra_out(c)
