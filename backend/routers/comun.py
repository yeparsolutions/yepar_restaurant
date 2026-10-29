# ============================================================
# YEPAR RESTAURANT — backend/routers/comun.py
# Piezas compartidas por los routers: convertir modelos a respuestas
# y reglas de "de quién es este pedido".
# ============================================================

from fastapi import HTTPException

from models import LineaPedido, Pedido, Usuario
from seguridad import es_admin
from servicios.cobro import calcular_cuenta
from servicios.disponibilidad import Disponibilidad
from esquemas import (CuentaOut, DisponibilidadOut, FaltaOut, LineaOut, PedidoOut, UsuarioOut)


def usuario_out(u: Usuario) -> UsuarioOut:
    return UsuarioOut(id=u.id, nombre=u.nombre, roles=sorted(r.rol.value for r in u.roles),
                      estacion=u.estacion.value if u.estacion else None, sucursal_id=u.sucursal_id)


def linea_out(l: LineaPedido) -> LineaOut:
    return LineaOut(
        id=l.id, item_id=l.item_id, nombre=l.item.nombre, cantidad=l.cantidad,
        precio_unitario=l.precio_unitario, comensal=l.comensal, nota=l.nota, estado=l.estado.value,
        estacion=l.estacion, quitados=[q.ingrediente_id for q in l.quitados],
        extras=[e.extra_id for e in l.extras], total=l.total)


def disponibilidad_out(d: Disponibilidad) -> DisponibilidadOut:
    return DisponibilidadOut(
        item_id=d.item_id, nombre=d.nombre, alcanza=d.alcanza,
        faltas=[FaltaOut(item_id=f.item_id, nombre=f.nombre, falta=f.falta, agotado_manual=f.agotado_manual)
                for f in d.faltas])


def pedido_out(db, pedido: Pedido) -> PedidoOut:
    c = calcular_cuenta(db, empresa_id=pedido.empresa_id, pedido_id=pedido.id)
    return PedidoOut(
        id=pedido.id, mesa_id=pedido.mesa_id, mesa=pedido.mesa.nombre if pedido.mesa else None,
        mesero_id=pedido.mesero_id, estado=pedido.estado.value, comensales=pedido.comensales,
        lineas=[linea_out(l) for l in pedido.lineas],
        cuenta=CuentaOut(subtotal=c.subtotal, descuento=c.descuento, propina=c.propina, total=c.total,
                         pagado=c.pagado, pendiente=c.pendiente))


def exigir_ser_el_mesero(usuario: Usuario, pedido: Pedido):
    """Un pedido lo maneja SU mesero (o un administrador): los demás no lo tocan."""
    if not es_admin(usuario) and pedido.mesero_id != usuario.id:
        raise HTTPException(status_code=403, detail="Esta mesa la atiende otro mesero.")
