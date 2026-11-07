# ============================================================
# YEPAR RESTAURANT — backend/routers/salon.py
# Lo que usa el MESERO en su tablet: plano de mesas, carta con
# disponibilidad, tomar / enviar / cancelar, pedir la cuenta,
# traspasar la mesa y retirar los platos listos.
#
# Cada endpoint llama a un servicio y confirma (commit) al final:
# los servicios nunca confirman solos.
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from esquemas import (AbrirPedidoIn, EnvioOut, EstadoMesaOut, FaltanteOut, ItemCartaOut, LineaOut, MeseroOut, OpcionCartaOut,
                      MesaIn, MesaOut, PedidoOut, PosicionIn, RetiroOut, TomarLineaIn, TomarLineaOut,
                      TraspasoIn)
from models import Extra, ExtraPlato, Item, RecetaLinea, RolUsuario, Usuario
from routers.comun import (disponibilidad_out, exigir_ser_el_mesero, linea_out, pedido_out)
from seguridad import exigir_roles, resolver_sucursal, roles_de
from servicios import cocina as svc_cocina
from servicios import mesas as svc_mesas
from servicios import pedidos as svc_pedidos
from servicios.disponibilidad import catalogo_mesero

router = APIRouter(tags=["salón"])

solo_personal_de_sala = exigir_roles(RolUsuario.mesero, RolUsuario.cajero)
solo_mesero = exigir_roles(RolUsuario.mesero)
solo_admin = exigir_roles()


# ── Mesas ────────────────────────────────────────────────────
@router.get("/mesas", response_model=list[EstadoMesaOut])
def plano(sucursal_id: Optional[int] = Query(default=None), db: Session = Depends(get_db),
          usuario: Usuario = Depends(solo_personal_de_sala)):
    """El plano con la luz de cada mesa: libre, ocupada, lista o cuenta pedida."""
    estados = svc_mesas.estado_mesas(db, empresa_id=usuario.empresa_id,
                                     sucursal_id=resolver_sucursal(usuario, sucursal_id))
    return [EstadoMesaOut(**e.__dict__) for e in estados]


@router.post("/mesas", response_model=MesaOut, status_code=201)
def crear_mesa(datos: MesaIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    campos = datos.model_dump(exclude={"sucursal_id"})
    mesa = svc_mesas.crear_mesa(db, empresa_id=usuario.empresa_id,
                                sucursal_id=resolver_sucursal(usuario, datos.sucursal_id), **campos)
    db.commit()
    return MesaOut.model_validate(mesa, from_attributes=True)


@router.patch("/mesas/{mesa_id}/posicion", response_model=MesaOut)
def mover_mesa(mesa_id: int, datos: PosicionIn, db: Session = Depends(get_db),
               usuario: Usuario = Depends(solo_admin)):
    mesa = svc_mesas.posicionar_mesa(db, empresa_id=usuario.empresa_id, mesa_id=mesa_id, **datos.model_dump())
    db.commit()
    return MesaOut.model_validate(mesa, from_attributes=True)


@router.get("/mesas/qr/{qr_token}", response_model=MesaOut)
def mesa_por_qr(qr_token: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_mesero)):
    """El mesero escanea el QR de la mesa para anclarse a ella."""
    mesa = svc_mesas.mesa_por_qr(db, empresa_id=usuario.empresa_id, qr_token=qr_token)
    return MesaOut.model_validate(mesa, from_attributes=True)


# ── Carta ────────────────────────────────────────────────────
@router.get("/carta", response_model=list[ItemCartaOut])
def carta(sucursal_id: Optional[int] = Query(default=None), db: Session = Depends(get_db),
          usuario: Usuario = Depends(solo_mesero)):
    """Lo que ve el mesero: solo vendibles, cada uno con su semáforo (alcanza / qué falta)."""
    resultado = []
    sucursal = resolver_sucursal(usuario, sucursal_id)
    # Sin barman en el local, las bebidas las busca el mesero: se entregan directo.
    hay_barra = svc_cocina.hay_personal_en(db, empresa_id=usuario.empresa_id, sucursal_id=sucursal, estacion="barra")
    extras = db.query(Extra).filter(Extra.empresa_id == usuario.empresa_id, Extra.activo.is_(True)).all()
    por_plato: dict[int, set[int]] = {}
    for ep in db.query(ExtraPlato).filter(ExtraPlato.extra_id.in_([e.id for e in extras] or [0])).all():
        por_plato.setdefault(ep.extra_id, set()).add(ep.item_id)
    for d in catalogo_mesero(db, empresa_id=usuario.empresa_id,
                             sucursal_id=resolver_sucursal(usuario, sucursal_id)):
        item = db.get(Item, d.item_id)
        base = disponibilidad_out(d)
        removibles = []
        if item.receta is not None:
            removibles = [OpcionCartaOut(id=l.ingrediente_id, nombre=l.ingrediente.nombre)
                          for l in item.receta.lineas if l.es_removible]
        ofrecidos = [OpcionCartaOut(id=e.id, nombre=e.nombre, precio=e.precio) for e in extras
                     if e.aplica_a_todos or item.id in por_plato.get(e.id, set())]
        resultado.append(ItemCartaOut(
            categoria=item.categoria.nombre if item.categoria else None, directo=(item.estacion is not None and item.estacion.value == "barra" and not hay_barra),
            removibles=removibles, extras=ofrecidos,
            item_id=item.id, nombre=item.nombre, precio_venta=item.precio_venta, foto_url=item.foto_url,
            estacion=item.estacion.value if item.estacion else "cocina", alcanza=base.alcanza, faltas=base.faltas))
    return resultado


# ── Pedidos ──────────────────────────────────────────────────
@router.post("/pedidos", response_model=PedidoOut, status_code=201)
def abrir_pedido(datos: AbrirPedidoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_mesero)):
    """El mesero se ancla a una mesa libre y abre la cuenta."""
    pedido = svc_pedidos.abrir_pedido(
        db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, datos.sucursal_id),
        mesa_id=datos.mesa_id, mesero_id=usuario.id, comensales=datos.comensales, pedido_id=datos.pedido_id)
    db.commit()
    return pedido_out(db, pedido)


@router.get("/pedidos/{pedido_id}", response_model=PedidoOut)
def ver_pedido(pedido_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_personal_de_sala)):
    pedido = svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id)
    return pedido_out(db, pedido)


@router.post("/pedidos/{pedido_id}/lineas", response_model=TomarLineaOut, status_code=201)
def tomar_plato(pedido_id: str, datos: TomarLineaIn, db: Session = Depends(get_db),
                usuario: Usuario = Depends(solo_mesero)):
    """Anota un plato (queda en cola, NO se envía). Avisa si falta algo, pero no bloquea."""
    pedido = svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id)
    exigir_ser_el_mesero(usuario, pedido)
    r = svc_pedidos.tomar_linea(db, empresa_id=usuario.empresa_id, pedido_id=pedido.id, **datos.model_dump())
    db.commit()
    return TomarLineaOut(linea=linea_out(r.linea), disponibilidad=disponibilidad_out(r.disponibilidad))


@router.delete("/lineas/{linea_id}", status_code=204)
def quitar_plato_anotado(linea_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_mesero)):
    """Borra un plato que todavía no se envió."""
    linea = svc_pedidos.cargar_linea(db, usuario.empresa_id, linea_id)
    exigir_ser_el_mesero(usuario, linea.pedido)
    svc_pedidos.quitar_linea_tomada(db, empresa_id=usuario.empresa_id, linea_id=linea.id)
    db.commit()


@router.post("/pedidos/{pedido_id}/enviar", response_model=EnvioOut)
def enviar(pedido_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_mesero)):
    """Envía a cocina y barra todo lo anotado, de una vez."""
    pedido = svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id)
    exigir_ser_el_mesero(usuario, pedido)
    r = svc_pedidos.enviar_pedido(db, empresa_id=usuario.empresa_id, pedido_id=pedido.id)
    db.commit()
    return EnvioOut(lineas=[linea_out(l) for l in r.lineas],
                    faltantes=[FaltanteOut(item_id=f.item_id, nombre=f.nombre, falta=f.falta) for f in r.faltantes])


@router.post("/lineas/{linea_id}/cancelar", response_model=LineaOut)
def cancelar_plato(linea_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_mesero)):
    """Cancela un plato: si está nuevo vuelve a cocina, si ya se prepara pasa a merma."""
    linea = svc_pedidos.cargar_linea(db, usuario.empresa_id, linea_id)
    exigir_ser_el_mesero(usuario, linea.pedido)
    linea = svc_pedidos.cancelar_linea(db, empresa_id=usuario.empresa_id, linea_id=linea.id, usuario_id=usuario.id)
    db.commit()
    return linea_out(linea)


@router.post("/pedidos/{pedido_id}/cuenta", response_model=PedidoOut)
def pedir_cuenta(pedido_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_mesero)):
    pedido = svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id)
    exigir_ser_el_mesero(usuario, pedido)
    svc_pedidos.pedir_cuenta(db, empresa_id=usuario.empresa_id, pedido_id=pedido.id)
    db.commit()
    return pedido_out(db, pedido)


@router.get("/meseros", response_model=list[MeseroOut])
def meseros(sucursal_id: Optional[int] = Query(default=None), db: Session = Depends(get_db),
            usuario: Usuario = Depends(solo_personal_de_sala)):
    """Los otros meseros activos del local: a quién se le puede pasar una mesa."""
    sucursal = resolver_sucursal(usuario, sucursal_id)
    gente = db.query(Usuario).filter(Usuario.empresa_id == usuario.empresa_id, Usuario.activo.is_(True),
                                     Usuario.id != usuario.id).order_by(Usuario.nombre).all()
    return [MeseroOut(id=u.id, nombre=u.nombre) for u in gente
            if RolUsuario.mesero in roles_de(u) and u.sucursal_id in (None, sucursal)]


@router.post("/pedidos/{pedido_id}/traspaso", response_model=PedidoOut)
def traspasar(pedido_id: str, datos: TraspasoIn, db: Session = Depends(get_db),
              usuario: Usuario = Depends(solo_mesero)):
    """Pasa la mesa a otro mesero (queda registrado quién la tenía)."""
    pedido = svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id)
    exigir_ser_el_mesero(usuario, pedido)
    svc_pedidos.traspasar_mesero(db, empresa_id=usuario.empresa_id, pedido_id=pedido.id,
                                 nuevo_mesero_id=datos.nuevo_mesero_id)
    db.commit()
    return pedido_out(db, pedido)


@router.post("/pedidos/{pedido_id}/anular", response_model=PedidoOut)
def anular(pedido_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_mesero)):
    pedido = svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id)
    exigir_ser_el_mesero(usuario, pedido)
    svc_pedidos.anular_pedido(db, empresa_id=usuario.empresa_id, pedido_id=pedido.id)
    db.commit()
    return pedido_out(db, pedido)


# ── Retiro de platos listos ──────────────────────────────────
@router.get("/retiros", response_model=list[RetiroOut])
def retiros(sucursal_id: Optional[int] = Query(default=None), db: Session = Depends(get_db),
            usuario: Usuario = Depends(solo_mesero)):
    """Platos listos esperando retiro, de las mesas de este mesero."""
    lista = svc_cocina.retiros_pendientes(db, empresa_id=usuario.empresa_id,
                                          sucursal_id=resolver_sucursal(usuario, sucursal_id),
                                          mesero_id=usuario.id)
    return [RetiroOut(**r.__dict__) for r in lista]


@router.post("/lineas/{linea_id}/entregar", response_model=LineaOut)
def entregar(linea_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_mesero)):
    """El mesero retiró el plato y lo llevó a la mesa (cualquier mesero puede retirar por otro)."""
    linea = svc_cocina.marcar_entregada(db, empresa_id=usuario.empresa_id, linea_id=linea_id, usuario_id=usuario.id)
    db.commit()
    return linea_out(linea)
