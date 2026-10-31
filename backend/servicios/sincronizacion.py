# ============================================================
# YEPAR RESTAURANT — backend/servicios/sincronizacion.py
# Procesa lo que la tablet hizo sin conexión, en el mismo orden en que ocurrió.
#
# Reglas:
#   - Cada operación es independiente: se confirma o se descarta sola (una mala no frena las demás).
#   - El `op_id` es la clave de idempotencia: reenviar lo mismo devuelve el resultado anterior sin repetirlo.
#   - Una operación rechazada queda registrada con su motivo para que la tablet se lo muestre al mesero.
# ============================================================

from typing import Optional

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from errores import ErrorNegocio
from esquemas import (AbrirPedidoSyncIn, RefLineaIn, RefPedidoIn, TomarLineaSyncIn)
from models import OperacionSync, Usuario
from seguridad import es_admin, resolver_sucursal
from servicios import pedidos as svc


def _es_su_mesa(usuario: Usuario, pedido) -> None:
    if not es_admin(usuario) and pedido.mesero_id != usuario.id:
        raise ErrorNegocio("Esta mesa la atiende otro mesero.")


def _abrir(db, u, d):
    d = AbrirPedidoSyncIn(**d)
    svc.abrir_pedido(db, empresa_id=u.empresa_id, sucursal_id=resolver_sucursal(u, d.sucursal_id),
                     mesa_id=d.mesa_id, mesero_id=u.id, comensales=d.comensales, pedido_id=d.pedido_id)


def _tomar(db, u, d):
    d = TomarLineaSyncIn(**d)
    _es_su_mesa(u, svc.cargar_pedido(db, u.empresa_id, d.pedido_id))
    svc.tomar_linea(db, empresa_id=u.empresa_id, **d.model_dump())


def _quitar(db, u, d):
    d = RefLineaIn(**d)
    _es_su_mesa(u, svc.cargar_linea(db, u.empresa_id, d.linea_id).pedido)
    svc.quitar_linea_tomada(db, empresa_id=u.empresa_id, linea_id=d.linea_id)


def _enviar(db, u, d):
    d = RefPedidoIn(**d)
    _es_su_mesa(u, svc.cargar_pedido(db, u.empresa_id, d.pedido_id))
    svc.enviar_pedido(db, empresa_id=u.empresa_id, pedido_id=d.pedido_id)


def _cancelar(db, u, d):
    d = RefLineaIn(**d)
    _es_su_mesa(u, svc.cargar_linea(db, u.empresa_id, d.linea_id).pedido)
    svc.cancelar_linea(db, empresa_id=u.empresa_id, linea_id=d.linea_id, usuario_id=u.id)


def _cuenta(db, u, d):
    d = RefPedidoIn(**d)
    _es_su_mesa(u, svc.cargar_pedido(db, u.empresa_id, d.pedido_id))
    svc.pedir_cuenta(db, empresa_id=u.empresa_id, pedido_id=d.pedido_id)


def _anular(db, u, d):
    d = RefPedidoIn(**d)
    _es_su_mesa(u, svc.cargar_pedido(db, u.empresa_id, d.pedido_id))
    svc.anular_pedido(db, empresa_id=u.empresa_id, pedido_id=d.pedido_id)


MANEJADORES = {
    "abrir_pedido": _abrir, "tomar_linea": _tomar, "quitar_linea": _quitar, "enviar": _enviar,
    "cancelar_linea": _cancelar, "pedir_cuenta": _cuenta, "anular_pedido": _anular,
}


def _resumen_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
    if isinstance(e, HTTPException):
        return str(e.detail)
    return str(e)


def _resultado(op: OperacionSync, repetida: bool) -> dict:
    return {"op_id": op.op_id, "tipo": op.tipo, "estado": op.estado, "repetida": repetida, "error": op.error}


def _previa(db: Session, empresa_id: int, op_id: str) -> Optional[OperacionSync]:
    return db.query(OperacionSync).filter_by(empresa_id=empresa_id, op_id=op_id).one_or_none()


def sincronizar(db: Session, usuario: Usuario, operaciones: list[dict]) -> list[dict]:
    """Aplica las operaciones en orden. Confirma cada una por separado (este servicio sí hace commit)."""
    empresa_id, usuario_id = usuario.empresa_id, usuario.id
    resultados = []
    for o in operaciones:
        previa = _previa(db, empresa_id, o["op_id"])
        if previa is not None:
            resultados.append(_resultado(previa, True))
            continue
        error = None
        try:
            MANEJADORES[o["tipo"]](db, usuario, o["datos"])
        except (ErrorNegocio, HTTPException, ValidationError, TypeError) as e:
            db.rollback()                   # descarta lo que esta operación alcanzó a escribir
            error = _resumen_error(e)
        registro = OperacionSync(empresa_id=empresa_id, usuario_id=usuario_id, op_id=o["op_id"], tipo=o["tipo"],
                                 estado="rechazada" if error else "aplicada", error=error)
        db.add(registro)
        try:
            db.commit()
        except IntegrityError:              # otra petición procesó el mismo op_id un instante antes
            db.rollback()
            previa = _previa(db, empresa_id, o["op_id"])
            resultados.append(_resultado(previa, True))
            continue
        resultados.append(_resultado(registro, False))
    return resultados
