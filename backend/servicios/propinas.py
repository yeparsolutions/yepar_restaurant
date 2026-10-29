# ============================================================
# YEPAR RESTAURANT — backend/servicios/propinas.py
# El libro de propinas: lo que el restaurante debe entregar a su equipo.
#
# Analogía: el "chanchito" de propinas con su cuaderno. Cada mesa
# cobrada anota cuánto dejó y para quién. Según cómo lo decida el
# administrador:
#   - POR MESA: la propina es del mesero de esa mesa.
#   - GRUPAL:   todo cae al chanchito común y el administrador lo
#               reparte entre el equipo cuando quiera.
# Cuando se le entrega el dinero a alguien, se tacha en el cuaderno.
#
# Supuesto: si la mesa cambió de mesero, la propina es del que la tenía
# al momento de cobrar. Los servicios no hacen commit.
# ============================================================

from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import (EstadoPropina, ModoPropina, Pedido, PropinaPorEntregar, RolUsuario)
from servicios.caja import cargar_usuario, tiene_rol
from servicios.stock import validar_sucursal

CENTAVO = Decimal("0.01")
CERO = Decimal("0")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def registrar_propina_de_pedido(db: Session, pedido: Pedido, modo: ModoPropina) -> Optional[PropinaPorEntregar]:
    """La llama el cobro cuando la mesa se cierra. Sin propina no deja nada en el libro."""
    if pedido.propina <= 0:
        return None
    propina = PropinaPorEntregar(
        empresa_id=pedido.empresa_id, sucursal_id=pedido.sucursal_id, pedido_id=pedido.id,
        mesero_id=pedido.mesero_id if modo == ModoPropina.por_mesa else None,
        modo=modo, monto=pedido.propina)
    db.add(propina)
    db.flush()
    return propina


def libro_propinas(db: Session, *, empresa_id: int, sucursal_id: int, mesero_id: Optional[int] = None,
                   estado: Optional[EstadoPropina] = None) -> list:
    """Las filas del libro, la más antigua primero. Con `mesero_id` solo las de esa persona."""
    validar_sucursal(db, empresa_id, sucursal_id)
    consulta = db.query(PropinaPorEntregar).filter_by(empresa_id=empresa_id, sucursal_id=sucursal_id)
    if mesero_id is not None:
        consulta = consulta.filter_by(mesero_id=mesero_id)
    if estado is not None:
        consulta = consulta.filter_by(estado=estado)
    return consulta.order_by(PropinaPorEntregar.creado_en, PropinaPorEntregar.id).all()


def saldos_por_entregar(db: Session, *, empresa_id: int, sucursal_id: int) -> dict:
    """
    Cuánto se le debe a cada persona ({usuario_id: monto}); la clave None es el fondo
    grupal todavía sin repartir.
    """
    validar_sucursal(db, empresa_id, sucursal_id)
    filas = (db.query(PropinaPorEntregar.mesero_id, func.sum(PropinaPorEntregar.monto))
             .filter_by(empresa_id=empresa_id, sucursal_id=sucursal_id, estado=EstadoPropina.pendiente)
             .group_by(PropinaPorEntregar.mesero_id).all())
    return {mesero: Decimal(total).quantize(CENTAVO) for mesero, total in filas}


def _exigir_cajero_o_admin(db: Session, empresa_id: int, usuario_id: int):
    usuario = cargar_usuario(db, empresa_id, usuario_id)
    if not tiene_rol(usuario, RolUsuario.cajero, RolUsuario.administrador):
        raise ErrorNegocio(f"'{usuario.nombre}' no puede entregar propinas.")
    return usuario


def entregar_propinas(db: Session, *, empresa_id: int, sucursal_id: int, mesero_id: int,
                      usuario_id: int) -> Decimal:
    """Se le entrega al mesero todo lo que tiene pendiente; devuelve cuánto fue."""
    validar_sucursal(db, empresa_id, sucursal_id)
    entrega = _exigir_cajero_o_admin(db, empresa_id, usuario_id)
    mesero = cargar_usuario(db, empresa_id, mesero_id)
    pendientes = (db.query(PropinaPorEntregar)
                  .filter_by(empresa_id=empresa_id, sucursal_id=sucursal_id, mesero_id=mesero.id,
                             estado=EstadoPropina.pendiente).all())
    if not pendientes:
        raise ErrorNegocio(f"'{mesero.nombre}' no tiene propinas pendientes.")
    for p in pendientes:
        p.estado = EstadoPropina.entregada
        p.entregada_en = _ahora()
        p.entregada_por_id = entrega.id
    db.flush()
    return sum((p.monto for p in pendientes), CERO)


def repartir_fondo_grupal(db: Session, *, empresa_id: int, sucursal_id: int, usuario_id: int,
                          participantes) -> dict:
    """
    Reparte el fondo grupal entre las personas indicadas y deja a cada una su parte
    PENDIENTE de entrega en el libro (devuelve {usuario_id: monto}).

    `participantes` puede ser una lista de usuarios (partes iguales) o un diccionario
    {usuario_id: peso} para repartir proporcionalmente (ej. por horas trabajadas).
    Las monedas que sobran por redondeo van a la primera persona de la lista.
    """
    validar_sucursal(db, empresa_id, sucursal_id)
    admin = cargar_usuario(db, empresa_id, usuario_id)
    if not tiene_rol(admin, RolUsuario.administrador):
        raise ErrorNegocio("Solo un administrador reparte el fondo de propinas.")
    pesos = dict(participantes) if isinstance(participantes, dict) else {u: Decimal("1") for u in participantes}
    if not pesos:
        raise ErrorNegocio("Indica entre quiénes se reparte el fondo.")
    pesos = {u: Decimal(str(p)) for u, p in pesos.items()}
    if any(p <= 0 for p in pesos.values()):
        raise ErrorNegocio("Los pesos de reparto deben ser mayores que cero.")
    for u in pesos:
        cargar_usuario(db, empresa_id, u)

    fondo = (db.query(PropinaPorEntregar)
             .filter_by(empresa_id=empresa_id, sucursal_id=sucursal_id, mesero_id=None,
                        estado=EstadoPropina.pendiente).all())
    total = sum((f.monto for f in fondo), CERO)
    if total <= 0:
        raise ErrorNegocio("No hay fondo grupal pendiente de repartir.")

    suma_pesos = sum(pesos.values())
    partes = {u: (total * p / suma_pesos).quantize(CENTAVO, rounding=ROUND_DOWN) for u, p in pesos.items()}
    primero = next(iter(partes))
    partes[primero] += total - sum(partes.values())                    # lo que sobra por redondeo
    for f in fondo:
        f.estado = EstadoPropina.repartida
        f.entregada_en = _ahora()
        f.entregada_por_id = admin.id
    for usuario, monto in partes.items():
        if monto > 0:
            db.add(PropinaPorEntregar(empresa_id=empresa_id, sucursal_id=sucursal_id, mesero_id=usuario,
                                      modo=ModoPropina.grupal, monto=monto))
    db.flush()
    return partes
