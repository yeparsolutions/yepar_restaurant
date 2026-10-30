# ============================================================
# YEPAR RESTAURANT — backend/routers/inventario.py
# Compras, producción de componentes, mermas, stock, alertas y lista de compras.
# Compras y listas: administrador. Producción, mermas y stock: cocinero o administrador.
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from esquemas import (AlertaOut, CompraIn, CompraOut, LineaCompraOut, ListaComprasOut, MermaIn,
                      MovimientoOut, ProduccionIn, ProduccionOut, StockOut)
from models import RolUsuario, Usuario
from seguridad import exigir_roles, resolver_sucursal
from servicios import disponibilidad as svc_disp
from servicios import mermas as svc_mermas
from servicios.compras import ingresar_compra
from servicios.produccion import producir_componente

router = APIRouter(prefix="/inventario", tags=["inventario"])

solo_admin = exigir_roles()
admin_o_cocina = exigir_roles(RolUsuario.cocinero)


def movimiento_out(m) -> MovimientoOut:
    return MovimientoOut(
        id=m.id, item_id=m.item_id, tipo=m.tipo.value, cantidad=m.cantidad, stock_anterior=m.stock_anterior,
        stock_nuevo=m.stock_nuevo, motivo_merma=m.motivo_merma.value if m.motivo_merma else None,
        referencia_tipo=m.referencia_tipo, referencia_id=m.referencia_id, nota=m.nota)


@router.post("/compras", response_model=CompraOut, status_code=201)
def comprar(datos: CompraIn, sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
            usuario: Usuario = Depends(solo_admin)):
    """Ingresa mercadería: sube el stock y recalcula el costo promedio del ítem."""
    r = ingresar_compra(db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id),
                        usuario_id=usuario.id, **datos.model_dump())
    db.commit()
    return CompraOut(movimiento_id=r.movimiento.id, item_id=r.movimiento.item_id, cantidad_base=r.cantidad_base,
                     costo_unitario_base=r.costo_unitario_base, costo_promedio=r.costo_promedio,
                     costo_referencia=r.costo_referencia, stock_nuevo=r.movimiento.stock_nuevo)


@router.post("/produccion", response_model=ProduccionOut, status_code=201)
def producir(datos: ProduccionIn, sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
             usuario: Usuario = Depends(admin_o_cocina)):
    """Produce un lote de un componente: gasta los insumos de su receta y suma el componente."""
    r = producir_componente(db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id),
                            usuario_id=usuario.id, **datos.model_dump())
    db.commit()
    lote = r.lote
    return ProduccionOut(lote_id=lote.id, item_id=lote.item_id, cantidad_producida=lote.cantidad_producida,
                         costo_total=lote.costo_total, costo_unitario=lote.costo_unitario, faltantes=r.faltantes)


@router.post("/mermas", response_model=MovimientoOut, status_code=201)
def merma(datos: MermaIn, sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
          usuario: Usuario = Depends(admin_o_cocina)):
    """Anota una pérdida (vencido, dañado, derrame...). La cantidad va positiva; el sistema la resta."""
    m = svc_mermas.registrar_merma(db, empresa_id=usuario.empresa_id,
                                   sucursal_id=resolver_sucursal(usuario, sucursal_id),
                                   usuario_id=usuario.id, **datos.model_dump())
    db.commit()
    return movimiento_out(m)


@router.get("/stock", response_model=list[StockOut])
def stock(sucursal_id: Optional[int] = None, solo_bajo_minimo: bool = False, db: Session = Depends(get_db),
          usuario: Usuario = Depends(admin_o_cocina)):
    """Foto del stock de la sucursal (físico, reservado y disponible). Sin costos."""
    filas = svc_mermas.listar_stock(db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id),
                                    solo_bajo_minimo=solo_bajo_minimo)
    return [StockOut(item_id=i.id, nombre=i.nombre, tipo=i.tipo.value, unidad=i.unidad_base.codigo, fisico=f,
                     reservado=r, disponible=d, stock_minimo=i.stock_minimo) for i, f, r, d in filas]


@router.get("/movimientos", response_model=list[MovimientoOut])
def movimientos(sucursal_id: Optional[int] = None, item_id: Optional[int] = None,
                limite: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
                usuario: Usuario = Depends(solo_admin)):
    """El libro de movimientos (lo más reciente primero)."""
    return [movimiento_out(m) for m in svc_mermas.listar_movimientos(
        db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id),
        item_id=item_id, limite=limite)]


@router.get("/alertas", response_model=list[AlertaOut])
def alertas(sucursal_id: Optional[int] = None, db: Session = Depends(get_db), usuario: Usuario = Depends(admin_o_cocina)):
    """Ingredientes bajo su stock mínimo, los más críticos primero."""
    return [AlertaOut(item_id=a.item_id, nombre=a.nombre, tipo=a.tipo.value, disponible=a.disponible,
                      stock_minimo=a.stock_minimo, se_produce=a.se_produce)
            for a in svc_disp.alertas_stock_bajo(db, empresa_id=usuario.empresa_id,
                                                 sucursal_id=resolver_sucursal(usuario, sucursal_id))]


@router.get("/lista-compras", response_model=ListaComprasOut)
def lista_compras(sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
                  usuario: Usuario = Depends(solo_admin)):
    """Qué comprar: cada ingrediente bajo mínimo se repone hasta 2× su mínimo."""
    lista = svc_disp.lista_compras_sugerida(db, empresa_id=usuario.empresa_id,
                                            sucursal_id=resolver_sucursal(usuario, sucursal_id))
    return ListaComprasOut(
        lineas=[LineaCompraOut(**l.__dict__) for l in lista.lineas], costo_total_estimado=lista.costo_total_estimado)
