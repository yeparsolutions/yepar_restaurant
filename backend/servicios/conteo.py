# ============================================================
# YEPAR RESTAURANT — backend/servicios/conteo.py
# Inventario físico ciego: abrir, contar, revisar, recontar y cerrar.
#
# Analogía: el cocinero cuenta con una hoja SIN la columna "debería haber".
# Cuando termina, el administrador recién ve las dos columnas juntas,
# pide recontar lo que no le cuadra y, si todo está bien, "cierra caja":
# el sistema ajusta el stock por la diferencia.
# ============================================================

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import (EstadoInventarioFisico as E, InventarioFisico, InventarioFisicoLinea, Item,
                    TipoItem, TipoMovimientoStock)
from servicios.compras import convertir_cantidad
from servicios.stock import aplicar_movimiento, obtener_stock, validar_sucursal
from unidades import costo_de_referencia

# Lo que se cuenta en bodega: insumos y bebidas de reventa (los platos no tienen existencia propia).
TIPOS_CONTABLES = (TipoItem.materia_prima, TipoItem.componente, TipoItem.vendible_reventa)
ACTIVOS = (E.contando, E.en_revision)


def cargar_inventario(db: Session, empresa_id: int, inventario_id: int,
                      sucursal_id: Optional[int] = None) -> InventarioFisico:
    inv = db.get(InventarioFisico, inventario_id)
    if inv is None or inv.empresa_id != empresa_id or (sucursal_id is not None and inv.sucursal_id != sucursal_id):
        raise ErrorNoEncontrado(f"El inventario {inventario_id} no existe.")
    return inv


def inventario_activo(db: Session, empresa_id: int, sucursal_id: int) -> Optional[InventarioFisico]:
    return (db.query(InventarioFisico)
              .filter(InventarioFisico.empresa_id == empresa_id, InventarioFisico.sucursal_id == sucursal_id,
                      InventarioFisico.estado.in_(ACTIVOS)).first())


def abrir_inventario(db: Session, *, empresa_id: int, sucursal_id: int, categoria_id: Optional[int] = None,
                     nota: Optional[str] = None, usuario_id: Optional[int] = None) -> InventarioFisico:
    validar_sucursal(db, empresa_id, sucursal_id)
    if inventario_activo(db, empresa_id, sucursal_id) is not None:
        raise ErrorNegocio("Ya hay un inventario en curso en esta sucursal: ciérralo o cancélalo primero.")
    consulta = db.query(Item).filter(Item.empresa_id == empresa_id, Item.activo.is_(True),
                                     Item.tipo.in_(TIPOS_CONTABLES))
    if categoria_id is not None:
        consulta = consulta.filter(Item.categoria_id == categoria_id)
    items = consulta.order_by(Item.nombre).all()
    if not items:
        raise ErrorNegocio("No hay ítems para contar con ese alcance.")

    inv = InventarioFisico(empresa_id=empresa_id, sucursal_id=sucursal_id, alcance_categoria_id=categoria_id,
                           nota=nota, creado_por_id=usuario_id, estado=E.contando)
    for item in items:
        stock = obtener_stock(db, empresa_id, item.id, sucursal_id)
        inv.lineas.append(InventarioFisicoLinea(
            item_id=item.id, cantidad_sistema=stock.cantidad_fisica or Decimal("0"),
            costo_referencia=costo_de_referencia(item.costo_promedio, item.costo_ultimo)))
    db.add(inv)
    db.flush()
    return inv


def contar_item(db: Session, inv: InventarioFisico, *, item_id: int, cantidad, unidad=None,
                presentacion_id=None, usuario_id: Optional[int] = None) -> InventarioFisicoLinea:
    if inv.estado != E.contando:
        raise ErrorNegocio("Este inventario no está en conteo.")
    linea = next((l for l in inv.lineas if l.item_id == item_id), None)
    if linea is None:
        raise ErrorNoEncontrado(f"El ítem {item_id} no está en este inventario.")
    linea.cantidad_contada = convertir_cantidad(db, linea.item, cantidad=cantidad, unidad=unidad,
                                                presentacion_id=presentacion_id, permitir_cero=True)
    linea.contada_por_id = usuario_id
    linea.contada_en = datetime.now(timezone.utc)
    db.flush()
    return linea


def finalizar_conteo(db: Session, inv: InventarioFisico) -> InventarioFisico:
    if inv.estado != E.contando:
        raise ErrorNegocio("Este inventario no está en conteo.")
    faltan = [l.item.nombre for l in inv.lineas if l.cantidad_contada is None]
    if faltan:
        raise ErrorNegocio(f"Faltan {len(faltan)} ítems por contar: " + ", ".join(faltan[:5])
                           + ("…" if len(faltan) > 5 else "") + ".")
    inv.estado = E.en_revision
    db.flush()
    return inv


def diferencia(l: InventarioFisicoLinea) -> Decimal:
    return (l.cantidad_contada or Decimal("0")) - l.cantidad_sistema


def pedir_recuento(db: Session, inv: InventarioFisico, item_ids: list[int]) -> InventarioFisico:
    if inv.estado != E.en_revision:
        raise ErrorNegocio("Solo se pide recuento mientras el inventario está en revisión.")
    if not item_ids:
        raise ErrorNegocio("Indica qué ítems recontar.")
    por_item = {l.item_id: l for l in inv.lineas}
    for i in item_ids:
        if i not in por_item:
            raise ErrorNoEncontrado(f"El ítem {i} no está en este inventario.")
    for i in item_ids:
        por_item[i].cantidad_contada = None
        por_item[i].contada_por_id = None
        por_item[i].contada_en = None
    inv.estado = E.contando
    db.flush()
    return inv


def cerrar_inventario(db: Session, inv: InventarioFisico, usuario_id: Optional[int] = None) -> int:
    """
    Aplica las diferencias como ajustes de stock. Se aplica el DELTA (contado − foto del sistema), no un
    valor absoluto: si hubo ventas mientras se contaba, esas salidas se conservan. Devuelve cuántos ajustes hizo.
    """
    if inv.estado != E.en_revision:
        raise ErrorNegocio("Solo se cierra un inventario que está en revisión.")
    ajustes = 0
    for l in inv.lineas:
        delta = diferencia(l)
        if delta == 0:
            continue
        stock = obtener_stock(db, inv.empresa_id, l.item_id, inv.sucursal_id)
        aplicar_movimiento(db, stock=stock, tipo=TipoMovimientoStock.ajuste_inventario, cantidad=delta,
                           costo_unitario=l.costo_referencia, usuario_id=usuario_id,
                           referencia_tipo="inventario_fisico", referencia_id=inv.id,
                           nota="Ajuste por inventario físico")
        ajustes += 1
    inv.estado = E.cerrado
    inv.cerrado_en = datetime.now(timezone.utc)
    db.flush()
    return ajustes


def cancelar_inventario(db: Session, inv: InventarioFisico) -> InventarioFisico:
    if inv.estado not in ACTIVOS:
        raise ErrorNegocio("Solo se cancela un inventario en curso.")
    inv.estado = E.cancelado
    inv.cerrado_en = datetime.now(timezone.utc)
    db.flush()
    return inv
