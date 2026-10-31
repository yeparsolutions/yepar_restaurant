# ============================================================
# YEPAR RESTAURANT — backend/routers/caja.py
# Caja y cobro: cajas, terminales, turnos con arqueo, propina, descuento,
# pagos, libro de propinas y cierre (cuadre por terminal, resumen del período).
#
# Analogía: es el mostrador de la caja. El mesero trae la cuenta, el cajero
# cobra y cuenta el cajón al final del turno, y el dueño revisa que todo calce.
# ============================================================

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from esquemas import (AbrirTurnoIn, ArqueoOut, CajaOut, ConfigCobroIn, ConfigCobroOut, CerrarTurnoIn,
                      CuadreTerminalOut, DescuentoIn, EntregaPropinaIn, EntregaPropinaOut, NombreIn, PagoIn,
                      PagoOut, ParteRepartoOut, PedidoOut, PropinaIn, PropinaLibroOut, RepartoIn,
                      ResumenPeriodoOut, SaldoPropinaOut, TerminalOut, TurnoConDiferenciaOut, TurnoOut)
from models import EstadoPedido, EstadoPropina, MedioPago, ModoPropina, RolUsuario, Usuario
from routers.comun import exigir_ser_el_mesero, pedido_out
from seguridad import es_admin, exigir_roles, resolver_sucursal, roles_de
from servicios import caja as svc_caja
from servicios import cierre as svc_cierre
from servicios import cobro as svc_cobro
from servicios import pedidos as svc_pedidos
from servicios import propinas as svc_propinas
from servicios.facturacion import emision as svc_facturacion

router = APIRouter(tags=["caja"])

solo_admin = exigir_roles()
solo_caja = exigir_roles(RolUsuario.cajero)
personal_de_cobro = exigir_roles(RolUsuario.cajero, RolUsuario.mesero)


def _como_utc(fecha: datetime) -> datetime:
    """Una fecha sin zona horaria se entiende en UTC (lo recomendable es enviarla con su offset)."""
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def _rango(desde: datetime, hasta: datetime) -> tuple:
    desde, hasta = _como_utc(desde), _como_utc(hasta)
    if hasta <= desde:
        raise HTTPException(status_code=422, detail="'hasta' debe ser posterior a 'desde'.")
    return desde, hasta


def turno_out(t) -> TurnoOut:
    return TurnoOut(id=t.id, caja_id=t.caja_id, caja=t.caja.nombre, usuario_id=t.usuario_id, estado=t.estado.value,
                    abierto_en=t.abierto_en, fondo=t.fondo, cerrado_en=t.cerrado_en, esperado=t.esperado,
                    contado=t.contado, diferencia=t.diferencia, nota=t.nota, revisado_por_id=t.revisado_por_id)


def arqueo_out(a) -> ArqueoOut:
    return ArqueoOut(**a.__dict__)


def _exigir_turno_propio_o_admin(usuario: Usuario, turno):
    if not es_admin(usuario) and turno.usuario_id != usuario.id:
        raise HTTPException(status_code=403, detail="Ese turno es de otro cajero.")


# ── Cajas y terminales ───────────────────────────────────────
@router.post("/cajas", response_model=CajaOut, status_code=201)
def crear_caja(datos: NombreIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    caja = svc_caja.crear_caja(db, empresa_id=usuario.empresa_id,
                               sucursal_id=resolver_sucursal(usuario, datos.sucursal_id), nombre=datos.nombre)
    db.commit()
    return CajaOut(id=caja.id, nombre=caja.nombre, sucursal_id=caja.sucursal_id)


@router.get("/cajas", response_model=list[CajaOut])
def cajas(sucursal_id: Optional[int] = None, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    return [CajaOut(id=c.id, nombre=c.nombre, sucursal_id=c.sucursal_id) for c in svc_caja.listar_cajas(
        db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id))]


@router.post("/terminales", response_model=TerminalOut, status_code=201)
def crear_terminal(datos: NombreIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    t = svc_caja.crear_terminal(db, empresa_id=usuario.empresa_id,
                                sucursal_id=resolver_sucursal(usuario, datos.sucursal_id), nombre=datos.nombre)
    db.commit()
    return TerminalOut(id=t.id, nombre=t.nombre, sucursal_id=t.sucursal_id)


@router.get("/terminales", response_model=list[TerminalOut])
def terminales(sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
               usuario: Usuario = Depends(personal_de_cobro)):
    return [TerminalOut(id=t.id, nombre=t.nombre, sucursal_id=t.sucursal_id) for t in svc_caja.listar_terminales(
        db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id))]


# ── Turnos ───────────────────────────────────────────────────
@router.post("/turnos", response_model=TurnoOut, status_code=201)
def abrir_turno(datos: AbrirTurnoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    """El cajero abre su turno con el fondo de cambio."""
    turno = svc_caja.abrir_turno(db, empresa_id=usuario.empresa_id, caja_id=datos.caja_id,
                                 usuario_id=usuario.id, fondo=datos.fondo)
    db.commit()
    return turno_out(turno)


@router.get("/turnos/actual", response_model=TurnoOut)
def turno_actual(db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    """Mi turno abierto (404 si no tengo)."""
    turno = svc_caja.turno_abierto_de(db, usuario.id)
    if turno is None:
        raise HTTPException(status_code=404, detail="No tienes un turno de caja abierto.")
    return turno_out(turno)


@router.get("/turnos/{turno_id}/arqueo", response_model=ArqueoOut)
def arqueo(turno_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    """Cuánto debería haber en el cajón ahora (sirve con el turno abierto)."""
    turno = svc_caja.turno_para_ver(db, empresa_id=usuario.empresa_id, turno_id=turno_id)
    _exigir_turno_propio_o_admin(usuario, turno)
    return arqueo_out(svc_caja.arqueo_turno(db, empresa_id=usuario.empresa_id, turno_id=turno.id))


@router.post("/turnos/{turno_id}/cerrar", response_model=TurnoOut)
def cerrar_turno(turno_id: int, datos: CerrarTurnoIn, db: Session = Depends(get_db),
                 usuario: Usuario = Depends(solo_caja)):
    """Cierra con lo contado. Si hay diferencia, la nota es obligatoria."""
    turno = svc_caja.cerrar_turno(db, empresa_id=usuario.empresa_id, turno_id=turno_id, usuario_id=usuario.id,
                                  contado=datos.contado, nota=datos.nota)
    db.commit()
    return turno_out(turno)


@router.post("/turnos/{turno_id}/revisar", response_model=TurnoOut)
def revisar_turno(turno_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    turno = svc_caja.revisar_turno(db, empresa_id=usuario.empresa_id, turno_id=turno_id, usuario_id=usuario.id)
    db.commit()
    return turno_out(turno)


# ── Configuración de cobro ───────────────────────────────────
@router.get("/configuracion/cobro", response_model=ConfigCobroOut)
def ver_configuracion(db: Session = Depends(get_db), usuario: Usuario = Depends(personal_de_cobro)):
    c = svc_cobro.obtener_configuracion(db, usuario.empresa_id)
    db.commit()                      # la primera vez se crea con valores por defecto
    return ConfigCobroOut(propina_modo=c.propina_modo.value, propina_sugerida_pct=c.propina_sugerida_pct)


@router.put("/configuracion/cobro", response_model=ConfigCobroOut)
def cambiar_configuracion(datos: ConfigCobroIn, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_admin)):
    c = svc_cobro.configurar_cobro(
        db, empresa_id=usuario.empresa_id,
        propina_modo=ModoPropina(datos.propina_modo) if datos.propina_modo else None,
        propina_sugerida_pct=datos.propina_sugerida_pct)
    db.commit()
    return ConfigCobroOut(propina_modo=c.propina_modo.value, propina_sugerida_pct=c.propina_sugerida_pct)


# ── Cuenta: propina, descuento y pagos ───────────────────────
@router.post("/pedidos/{pedido_id}/propina", response_model=PedidoOut)
def anotar_propina(pedido_id: str, datos: PropinaIn, db: Session = Depends(get_db),
                   usuario: Usuario = Depends(personal_de_cobro)):
    """Anota la propina de la cuenta (sin monto: la sugerida). El mesero solo en sus mesas."""
    pedido = svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id)
    if RolUsuario.cajero not in roles_de(usuario):
        exigir_ser_el_mesero(usuario, pedido)
    svc_cobro.anotar_propina(db, empresa_id=usuario.empresa_id, pedido_id=pedido.id, monto=datos.monto)
    db.commit()
    return pedido_out(db, pedido)


@router.post("/pedidos/{pedido_id}/descuento", response_model=PedidoOut)
def aplicar_descuento(pedido_id: str, datos: DescuentoIn, db: Session = Depends(get_db),
                      usuario: Usuario = Depends(solo_caja)):
    """Descuento en % (el cajero hasta su tope personal; el administrador sin tope)."""
    pedido = svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id)
    svc_cobro.aplicar_descuento(db, empresa_id=usuario.empresa_id, pedido_id=pedido.id, usuario_id=usuario.id,
                                porcentaje=datos.porcentaje)
    db.commit()
    return pedido_out(db, pedido)


@router.post("/pedidos/{pedido_id}/pagos", response_model=PagoOut, status_code=201)
def pagar(pedido_id: str, datos: PagoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(personal_de_cobro)):
    """Registra un pago (total o parcial). Al cubrir la cuenta, la mesa se cierra."""
    pedido = svc_pedidos.cargar_pedido(db, usuario.empresa_id, pedido_id)
    if RolUsuario.cajero not in roles_de(usuario):
        exigir_ser_el_mesero(usuario, pedido)
    pago = svc_cobro.registrar_pago(
        db, empresa_id=usuario.empresa_id, pedido_id=pedido.id, usuario_id=usuario.id, medio=MedioPago(datos.medio),
        monto=datos.monto, recibido=datos.recibido, numero_operacion=datos.numero_operacion,
        terminal_id=datos.terminal_id, pago_id=datos.pago_id)
    db.commit()                                        # el cobro queda firme pase lo que pase con la factura
    documento = None
    if pedido.estado == EstadoPedido.cerrado:
        documento = svc_facturacion.emitir_automatico(db, empresa_id=usuario.empresa_id, usuario_id=usuario.id,
                                                      pedido_id=pedido.id)
        db.commit()
    vuelto = (pago.recibido - pago.monto) if pago.recibido is not None else None
    cuenta = pedido_out(db, pedido)
    return PagoOut(id=pago.id, pedido_id=pago.pedido_id, medio=pago.medio.value, monto=pago.monto,
                   recibido=pago.recibido, vuelto=vuelto, numero_operacion=pago.numero_operacion,
                   terminal_id=pago.terminal_id, turno_id=pago.turno_id, pedido_estado=cuenta.estado,
                   cuenta=cuenta.cuenta,
                   documento_estado=documento.estado.value if documento else None,
                   documento_folio=documento.folio if documento else None)


# ── Propinas ─────────────────────────────────────────────────
@router.get("/propinas", response_model=list[PropinaLibroOut])
def libro(sucursal_id: Optional[int] = None, estado: Optional[EstadoPropina] = None,
          db: Session = Depends(get_db), usuario: Usuario = Depends(personal_de_cobro)):
    """El libro de propinas. El mesero ve solo las suyas; cajero y administrador, todas."""
    solo_las_mias = usuario.id if RolUsuario.cajero not in roles_de(usuario) and not es_admin(usuario) else None
    filas = svc_propinas.libro_propinas(db, empresa_id=usuario.empresa_id,
                                        sucursal_id=resolver_sucursal(usuario, sucursal_id),
                                        mesero_id=solo_las_mias, estado=estado)
    return [PropinaLibroOut(id=p.id, pedido_id=p.pedido_id, mesero_id=p.mesero_id, modo=p.modo.value,
                            monto=p.monto, estado=p.estado.value, creado_en=p.creado_en) for p in filas]


@router.get("/propinas/saldos", response_model=list[SaldoPropinaOut])
def saldos(sucursal_id: Optional[int] = None, db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    """Cuánto se le debe a cada persona; sin mesero = fondo grupal sin repartir."""
    s = svc_propinas.saldos_por_entregar(db, empresa_id=usuario.empresa_id,
                                         sucursal_id=resolver_sucursal(usuario, sucursal_id))
    return [SaldoPropinaOut(mesero_id=m, monto=v) for m, v in s.items()]


@router.post("/propinas/entregar", response_model=EntregaPropinaOut)
def entregar(datos: EntregaPropinaIn, sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
             usuario: Usuario = Depends(solo_caja)):
    """Entrega al mesero todo lo que tiene pendiente."""
    monto = svc_propinas.entregar_propinas(db, empresa_id=usuario.empresa_id,
                                           sucursal_id=resolver_sucursal(usuario, sucursal_id),
                                           mesero_id=datos.mesero_id, usuario_id=usuario.id)
    db.commit()
    return EntregaPropinaOut(mesero_id=datos.mesero_id, entregado=monto)


@router.post("/propinas/repartir", response_model=list[ParteRepartoOut])
def repartir(datos: RepartoIn, sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
             usuario: Usuario = Depends(solo_admin)):
    """Reparte el fondo grupal: partes iguales (`participantes`) o proporcional (`pesos`)."""
    if (datos.participantes is None) == (datos.pesos is None):
        raise HTTPException(status_code=422, detail="Indica 'participantes' (partes iguales) O 'pesos' (proporcional).")
    partes = svc_propinas.repartir_fondo_grupal(
        db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id),
        usuario_id=usuario.id, participantes=datos.participantes if datos.participantes is not None else datos.pesos)
    db.commit()
    return [ParteRepartoOut(usuario_id=u, monto=m) for u, m in partes.items()]


# ── Cierre ───────────────────────────────────────────────────
@router.get("/cierre/terminal/{terminal_id}", response_model=CuadreTerminalOut)
def cuadre_terminal(terminal_id: int, desde: datetime, hasta: datetime, reportado: Optional[Decimal] = Query(default=None),
                    db: Session = Depends(get_db), usuario: Usuario = Depends(solo_caja)):
    """Lo registrado con ese terminal vs. el total del comprobante del terminal (`reportado`)."""
    desde, hasta = _rango(desde, hasta)
    c = svc_cierre.cuadre_terminal(db, empresa_id=usuario.empresa_id, terminal_id=terminal_id, desde=desde,
                                   hasta=hasta, reportado=reportado)
    return CuadreTerminalOut(
        terminal_id=c.terminal_id, nombre=c.nombre, cantidad=c.cantidad, total_registrado=c.total_registrado,
        total_reportado=c.total_reportado, diferencia=c.diferencia,
        operaciones=[[op, f"{m:.2f}"] for op, m in c.operaciones])


@router.get("/cierre/resumen", response_model=ResumenPeriodoOut)
def resumen(desde: datetime, hasta: datetime, sucursal_id: Optional[int] = None, db: Session = Depends(get_db),
            usuario: Usuario = Depends(solo_admin)):
    """Ventas, descuentos, propinas y cobros por medio del período, más los turnos que no cuadraron."""
    desde, hasta = _rango(desde, hasta)
    r = svc_cierre.resumen_periodo(db, empresa_id=usuario.empresa_id, sucursal_id=resolver_sucursal(usuario, sucursal_id),
                                   desde=desde, hasta=hasta)
    return ResumenPeriodoOut(
        cerradas=r.cerradas, ventas=r.ventas, descuentos=r.descuentos, propinas=r.propinas,
        total_cobrado=r.total_cobrado, por_medio=r.por_medio,
        turnos_con_diferencia=[TurnoConDiferenciaOut(turno_id=t, diferencia=d) for t, d in r.turnos_con_diferencia])
