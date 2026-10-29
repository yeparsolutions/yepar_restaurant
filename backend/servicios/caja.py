# ============================================================
# YEPAR RESTAURANT — backend/servicios/caja.py
# Cajas, turnos del cajero y cuadre al cierre.
#
# Analogía: el cajero abre el cajón con un fondo de cambio, cobra
# durante el turno y al cerrar cuenta billete por billete. Si lo
# contado no calza con lo esperado, tiene que dejar una nota; y el
# administrador después "revisa" el cuadre.
#
# Los servicios no hacen commit (lo decide quien llama).
# ============================================================

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from errores import ErrorNegocio
from models import (Caja, EstadoTurno, MedioPago, Pago, RolUsuario, TerminalPago,
                    TurnoCaja, Usuario)
from servicios.stock import validar_sucursal
from unidades import a_decimal

CERO = Decimal("0")
ROLES_DE_CAJA = (RolUsuario.cajero, RolUsuario.administrador)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _dinero(valor, nombre: str) -> Decimal:
    try:
        return a_decimal(valor).quantize(Decimal("0.01"))
    except Exception:
        raise ErrorNegocio(f"{nombre} no es un monto válido.")


def cargar_usuario(db: Session, empresa_id: int, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or usuario.empresa_id != empresa_id or not usuario.activo:
        raise ErrorNegocio("El usuario no existe.")
    return usuario


def tiene_rol(usuario: Usuario, *roles) -> bool:
    return any(r.rol in roles for r in usuario.roles)


@dataclass
class Arqueo:
    """El cuadre de un turno (también sirve mientras sigue abierto)."""
    turno_id: int
    fondo: Decimal
    efectivo_cobrado: Decimal         # suma del efectivo que quedó en el cajón (sin los vueltos)
    esperado: Decimal                 # fondo + efectivo cobrado
    cantidad_pagos: int


# ------------------------------------------------------------
# Cajas y terminales
# ------------------------------------------------------------
def crear_caja(db: Session, *, empresa_id: int, sucursal_id: int, nombre: str) -> Caja:
    validar_sucursal(db, empresa_id, sucursal_id)
    nombre = (nombre or "").strip()
    if not nombre:
        raise ErrorNegocio("La caja necesita un nombre.")
    if db.query(Caja).filter_by(sucursal_id=sucursal_id, nombre=nombre).first() is not None:
        raise ErrorNegocio(f"Ya existe una caja llamada '{nombre}' en este local.")
    caja = Caja(empresa_id=empresa_id, sucursal_id=sucursal_id, nombre=nombre)
    db.add(caja)
    db.flush()
    return caja


def crear_terminal(db: Session, *, empresa_id: int, sucursal_id: int, nombre: str) -> TerminalPago:
    validar_sucursal(db, empresa_id, sucursal_id)
    nombre = (nombre or "").strip()
    if not nombre:
        raise ErrorNegocio("El terminal necesita un nombre.")
    if db.query(TerminalPago).filter_by(sucursal_id=sucursal_id, nombre=nombre).first() is not None:
        raise ErrorNegocio(f"Ya existe un terminal llamado '{nombre}' en este local.")
    terminal = TerminalPago(empresa_id=empresa_id, sucursal_id=sucursal_id, nombre=nombre)
    db.add(terminal)
    db.flush()
    return terminal


# ------------------------------------------------------------
# Turnos
# ------------------------------------------------------------
def turno_abierto_de(db: Session, usuario_id: int) -> Optional[TurnoCaja]:
    return db.query(TurnoCaja).filter_by(usuario_id=usuario_id, estado=EstadoTurno.abierto).one_or_none()


def abrir_turno(db: Session, *, empresa_id: int, caja_id: int, usuario_id: int, fondo=0) -> TurnoCaja:
    """El cajero abre su turno con el fondo de cambio con que parte."""
    caja = db.get(Caja, caja_id)
    if caja is None or caja.empresa_id != empresa_id or not caja.activa:
        raise ErrorNegocio("La caja no existe.")
    usuario = cargar_usuario(db, empresa_id, usuario_id)
    if not tiene_rol(usuario, *ROLES_DE_CAJA):
        raise ErrorNegocio(f"'{usuario.nombre}' no es cajero: no puede abrir una caja.")
    fondo = _dinero(fondo, "El fondo")
    if fondo < 0:
        raise ErrorNegocio("El fondo no puede ser negativo.")
    if db.query(TurnoCaja).filter_by(caja_id=caja.id, estado=EstadoTurno.abierto).first() is not None:
        raise ErrorNegocio(f"La caja '{caja.nombre}' ya tiene un turno abierto.")
    if turno_abierto_de(db, usuario.id) is not None:
        raise ErrorNegocio(f"'{usuario.nombre}' ya tiene un turno abierto: ciérralo antes de abrir otro.")
    turno = TurnoCaja(empresa_id=empresa_id, sucursal_id=caja.sucursal_id, caja_id=caja.id,
                      usuario_id=usuario.id, fondo=fondo)
    db.add(turno)
    db.flush()
    return turno


def _cargar_turno(db: Session, empresa_id: int, turno_id: int) -> TurnoCaja:
    turno = db.get(TurnoCaja, turno_id)
    if turno is None or turno.empresa_id != empresa_id:
        raise ErrorNegocio("El turno no existe.")
    return turno


def arqueo_turno(db: Session, *, empresa_id: int, turno_id: int) -> Arqueo:
    """Cuánto debería haber en el cajón: fondo + efectivo cobrado (los vueltos ya salieron)."""
    turno = _cargar_turno(db, empresa_id, turno_id)
    total, cantidad = db.query(func.coalesce(func.sum(Pago.monto), 0), func.count(Pago.id)).filter(
        Pago.turno_id == turno.id, Pago.medio == MedioPago.efectivo).one()
    cobrado = Decimal(total).quantize(Decimal("0.01"))
    return Arqueo(turno_id=turno.id, fondo=turno.fondo, efectivo_cobrado=cobrado,
                  esperado=turno.fondo + cobrado, cantidad_pagos=cantidad)


def cerrar_turno(db: Session, *, empresa_id: int, turno_id: int, usuario_id: int, contado,
                 nota: Optional[str] = None) -> TurnoCaja:
    """
    Cierra el turno con lo que el cajero contó. Si no calza con lo esperado
    (sobra o falta), la nota explicando qué pasó es obligatoria.
    """
    turno = _cargar_turno(db, empresa_id, turno_id)
    if turno.estado != EstadoTurno.abierto:
        raise ErrorNegocio("Este turno ya está cerrado.")
    quien = cargar_usuario(db, empresa_id, usuario_id)
    if quien.id != turno.usuario_id and not tiene_rol(quien, RolUsuario.administrador):
        raise ErrorNegocio("Solo el cajero del turno o un administrador puede cerrarlo.")
    contado = _dinero(contado, "Lo contado")
    if contado < 0:
        raise ErrorNegocio("Lo contado no puede ser negativo.")

    arqueo = arqueo_turno(db, empresa_id=empresa_id, turno_id=turno.id)
    diferencia = contado - arqueo.esperado
    if diferencia != 0 and not (nota or "").strip():
        raise ErrorNegocio("Hay diferencia entre lo contado y lo esperado: escribe una nota explicando qué pasó.")

    turno.estado = EstadoTurno.cerrado
    turno.cerrado_en = _ahora()
    turno.cerrado_por_id = quien.id
    turno.esperado, turno.contado, turno.diferencia = arqueo.esperado, contado, diferencia
    turno.nota = (nota or "").strip() or None
    db.flush()
    return turno


def revisar_turno(db: Session, *, empresa_id: int, turno_id: int, usuario_id: int) -> TurnoCaja:
    """El administrador da por revisado el cuadre de un turno cerrado."""
    turno = _cargar_turno(db, empresa_id, turno_id)
    admin = cargar_usuario(db, empresa_id, usuario_id)
    if not tiene_rol(admin, RolUsuario.administrador):
        raise ErrorNegocio("Solo un administrador revisa los cuadres.")
    if turno.estado != EstadoTurno.cerrado:
        raise ErrorNegocio("El turno sigue abierto: se revisa después de cerrarlo.")
    turno.revisado_por_id = admin.id
    turno.revisado_en = _ahora()
    db.flush()
    return turno
