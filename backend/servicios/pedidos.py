# ============================================================
# YEPAR RESTAURANT — backend/servicios/pedidos.py
# El pedido de una mesa: abrir, tomar platos, enviar a cocina,
# cancelar, pedir la cuenta y traspasar de mesero.
#
# Analogía: el mesero con su libreta.
#   - TOMAR = anotar en la libreta (queda en cola, cocina no se entera).
#   - ENVIAR = arrancar la hoja y llevarla a cocina, todo junto, para
#     que no se enreden las comandas. Con la mesa abierta puede enviar
#     cuantas veces quiera (primero los pasapalos, luego lo demás).
#   - Al enviar, la cocina "aparta" los ingredientes (reserva de stock).
#
# Faltar un ingrediente NUNCA bloquea: solo se avisa (al tomar, al mesero;
# al enviar, se devuelven los faltantes para alertar al administrador).
# Los servicios no hacen commit (lo decide quien llama).
# ============================================================

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import (EstadoLinea, EstadoPedido, Extra, LineaExtra, LineaPedido,
                    LineaQuitado, Pedido, RolUsuario, TraspasoMesero, Usuario)
from servicios.disponibilidad import Disponibilidad, revisar_disponibilidad
from servicios.mesas import cargar_mesa
from servicios.reservas import (calcular_necesidad, liberar_reserva, mermar_reserva,
                                reservar_linea)
from servicios.stock import cargar_item, validar_sucursal

ROLES_DE_SALON = (RolUsuario.mesero, RolUsuario.administrador)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ResultadoTomar:
    linea: LineaPedido
    disponibilidad: Disponibilidad          # el "ok / falta X" que ve el mesero (solo avisa)


@dataclass
class ResultadoEnvio:
    lineas: list = field(default_factory=list)       # líneas que pasaron a 'enviada'
    faltantes: list = field(default_factory=list)    # Faltante de reservas.py, para alertar al admin


# ------------------------------------------------------------
# Ayudas
# ------------------------------------------------------------
def cargar_pedido(db: Session, empresa_id: int, pedido_id: str) -> Pedido:
    pedido = db.get(Pedido, pedido_id)
    if pedido is None or pedido.empresa_id != empresa_id:
        raise ErrorNoEncontrado("El pedido no existe.")
    return pedido


def cargar_linea(db: Session, empresa_id: int, linea_id: str) -> LineaPedido:
    linea = db.get(LineaPedido, linea_id)
    if linea is None or linea.empresa_id != empresa_id:
        raise ErrorNoEncontrado("El plato pedido no existe.")
    return linea


def _exigir_abierto(pedido: Pedido, *, permitir_cuenta_pedida: bool = False):
    validos = {EstadoPedido.abierto}
    if permitir_cuenta_pedida:
        validos.add(EstadoPedido.cuenta_pedida)
    if pedido.estado not in validos:
        raise ErrorNegocio(f"El pedido está '{pedido.estado.value}': ya no admite este cambio.")


def _cargar_personal(db: Session, empresa_id: int, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or usuario.empresa_id != empresa_id or not usuario.activo:
        raise ErrorNoEncontrado("El usuario no existe.")
    if not any(r.rol in ROLES_DE_SALON for r in usuario.roles):
        raise ErrorNegocio(f"'{usuario.nombre}' no es mesero: no puede atender mesas.")
    return usuario


# ------------------------------------------------------------
# Abrir el pedido de una mesa
# ------------------------------------------------------------
def abrir_pedido(db: Session, *, empresa_id: int, sucursal_id: int, mesero_id: int,
                 mesa_id: Optional[int] = None, comensales: Optional[int] = None,
                 pedido_id: Optional[str] = None) -> Pedido:
    """
    El mesero se ancla a una mesa libre. Sin `mesa_id` la cuenta es de mostrador o delivery (no ocupa mesa:
    puede haber varias abiertas a la vez). `pedido_id` permite que la tablet genere el UUID sin conexión
    y lo sincronice después.
    """
    validar_sucursal(db, empresa_id, sucursal_id)
    mesa = None
    if mesa_id is not None:
        mesa = cargar_mesa(db, empresa_id, mesa_id)
        if mesa.sucursal_id != sucursal_id or not mesa.activa:
            raise ErrorNoEncontrado("La mesa no existe.")
    _cargar_personal(db, empresa_id, mesero_id)
    if comensales is not None and comensales <= 0:
        raise ErrorNegocio("Los comensales deben ser al menos uno.")
    if pedido_id is not None and db.get(Pedido, pedido_id) is not None:
        raise ErrorNegocio("Ese pedido ya existe (¿se sincronizó dos veces?).")
    if mesa is not None:
        ocupada = db.query(Pedido).filter(
            Pedido.mesa_id == mesa.id,
            Pedido.estado.in_((EstadoPedido.abierto, EstadoPedido.cuenta_pedida))).first()
        if ocupada is not None:
            raise ErrorNegocio(f"La mesa '{mesa.nombre}' ya está ocupada.")

    pedido = Pedido(empresa_id=empresa_id, sucursal_id=sucursal_id, mesa_id=mesa.id if mesa else None, mesero_id=mesero_id,
                    comensales=comensales)
    if pedido_id is not None:
        pedido.id = pedido_id
    db.add(pedido)
    db.flush()
    return pedido


# ------------------------------------------------------------
# Tomar (anotar) un plato: queda en cola, NO se envía
# ------------------------------------------------------------
def tomar_linea(db: Session, *, empresa_id: int, pedido_id: str, item_id: int, cantidad: int = 1,
                comensal: Optional[int] = None, sin_ingredientes: Iterable[int] = (),
                extra_ids: Iterable[int] = (), nota: Optional[str] = None,
                linea_id: Optional[str] = None) -> ResultadoTomar:
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    _exigir_abierto(pedido)
    if not isinstance(cantidad, int) or cantidad <= 0:
        raise ErrorNegocio("La cantidad pedida debe ser un número entero mayor que cero.")
    if linea_id is not None and db.get(LineaPedido, linea_id) is not None:
        raise ErrorNegocio("Ese plato ya existe (¿se sincronizó dos veces?).")

    item = cargar_item(db, empresa_id, item_id)
    if not item.es_vendible or not item.activo:
        raise ErrorNegocio(f"'{item.nombre}' no está a la venta.")
    if item.precio_venta is None:
        raise ErrorNegocio(f"'{item.nombre}' no tiene precio de venta.")

    quitados, extras = list(sin_ingredientes), list(extra_ids)
    # Valida removibles y extras (y que el plato tenga receta) antes de guardar nada.
    calcular_necesidad(db, empresa_id=empresa_id, item_id=item_id, cantidad=cantidad,
                       sin_ingredientes=quitados, extra_ids=extras)
    disponibilidad = revisar_disponibilidad(
        db, empresa_id=empresa_id, sucursal_id=pedido.sucursal_id, item_id=item_id, cantidad=cantidad,
        sin_ingredientes=quitados, extra_ids=extras)

    linea = LineaPedido(
        empresa_id=empresa_id, pedido_id=pedido.id, item_id=item.id, cantidad=cantidad,
        precio_unitario=item.precio_venta, comensal=comensal, nota=nota,
        estacion=(item.estacion.value if item.estacion else "cocina"), estado=EstadoLinea.tomada)
    if linea_id is not None:
        linea.id = linea_id
    linea.quitados = [LineaQuitado(ingrediente_id=i) for i in dict.fromkeys(quitados)]
    linea.extras = [LineaExtra(extra_id=e, precio=db.get(Extra, e).precio) for e in extras]
    pedido.lineas.append(linea)
    db.flush()
    return ResultadoTomar(linea=linea, disponibilidad=disponibilidad)


def quitar_linea_tomada(db: Session, *, empresa_id: int, linea_id: str) -> None:
    """Borra un plato que aún está solo en la libreta (no se envió, no hay nada que devolver)."""
    linea = cargar_linea(db, empresa_id, linea_id)
    if linea.estado != EstadoLinea.tomada:
        raise ErrorNegocio("Este plato ya se envió: para sacarlo hay que cancelarlo.")
    linea.pedido.lineas.remove(linea)      # sale de la lista del pedido y (por delete-orphan) de la base
    db.flush()


# ------------------------------------------------------------
# Enviar a cocina / barra
# ------------------------------------------------------------
def enviar_pedido(db: Session, *, empresa_id: int, pedido_id: str) -> ResultadoEnvio:
    """Envía todo lo tomado de golpe y aparta los ingredientes (reserva de stock)."""
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    _exigir_abierto(pedido)
    por_enviar = [l for l in pedido.lineas if l.estado == EstadoLinea.tomada]
    if not por_enviar:
        raise ErrorNegocio("No hay platos tomados para enviar.")

    resultado = ResultadoEnvio()
    faltantes: dict = {}
    for linea in por_enviar:
        reserva = reservar_linea(
            db, empresa_id=empresa_id, sucursal_id=pedido.sucursal_id, referencia_id=linea.id,
            item_id=linea.item_id, cantidad=linea.cantidad,
            sin_ingredientes=[q.ingrediente_id for q in linea.quitados],
            extra_ids=[e.extra_id for e in linea.extras])
        for f in reserva.faltantes:
            faltantes[f.item_id] = f        # el último valor ya es el acumulado de todo lo reservado
        linea.estado = EstadoLinea.enviada
        linea.enviada_en = _ahora()
        resultado.lineas.append(linea)
    resultado.faltantes = list(faltantes.values())
    db.flush()
    return resultado


# ------------------------------------------------------------
# Cancelar un plato (lo hace el mesero, no necesita al admin)
# ------------------------------------------------------------
def cancelar_linea(db: Session, *, empresa_id: int, linea_id: str, usuario_id: Optional[int] = None) -> LineaPedido:
    """
    - tomada: solo se borra de la libreta.
    - enviada (estado 'nuevo'): vuelve a cocina, se libera la reserva.
    - en preparación: ya se cocinó algo, pasa a merma.
    - lista o entregada: ya salió; no se cancela por aquí.
    """
    linea = cargar_linea(db, empresa_id, linea_id)
    _exigir_abierto(linea.pedido, permitir_cuenta_pedida=True)
    if linea.estado == EstadoLinea.tomada:
        linea.estado = EstadoLinea.cancelada
    elif linea.estado == EstadoLinea.enviada:
        liberar_reserva(db, empresa_id=empresa_id, referencia_id=linea.id)
        linea.estado = EstadoLinea.cancelada
    elif linea.estado == EstadoLinea.en_preparacion:
        mermar_reserva(db, empresa_id=empresa_id, referencia_id=linea.id, usuario_id=usuario_id)
        linea.estado = EstadoLinea.cancelada
    else:
        raise ErrorNegocio(f"El plato está '{linea.estado.value}': ya salió de cocina y no se puede cancelar.")
    linea.cancelada_en = _ahora()
    db.flush()
    return linea


# ------------------------------------------------------------
# Cuenta, traspaso y anulación
# ------------------------------------------------------------
def pedir_cuenta(db: Session, *, empresa_id: int, pedido_id: str) -> Pedido:
    """El cliente pidió la cuenta: la mesa ya no admite más platos."""
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    _exigir_abierto(pedido)
    if any(l.estado == EstadoLinea.tomada for l in pedido.lineas):
        raise ErrorNegocio("Hay platos tomados sin enviar: envíalos o quítalos antes de pedir la cuenta.")
    if not any(l.estado != EstadoLinea.cancelada for l in pedido.lineas):
        raise ErrorNegocio("El pedido no tiene platos que cobrar.")
    pedido.estado = EstadoPedido.cuenta_pedida
    pedido.cuenta_pedida_en = _ahora()
    db.flush()
    return pedido


def traspasar_mesero(db: Session, *, empresa_id: int, pedido_id: str, nuevo_mesero_id: int) -> Pedido:
    """Cambia el mesero de una mesa abierta; queda registrado quién la tenía antes."""
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    _exigir_abierto(pedido, permitir_cuenta_pedida=True)
    nuevo = _cargar_personal(db, empresa_id, nuevo_mesero_id)
    if nuevo.id == pedido.mesero_id:
        raise ErrorNegocio("Esa mesa ya la atiende ese mesero.")
    pedido.traspasos.append(TraspasoMesero(de_usuario_id=pedido.mesero_id, a_usuario_id=nuevo.id))
    pedido.mesero_id = nuevo.id
    db.flush()
    return pedido


def anular_pedido(db: Session, *, empresa_id: int, pedido_id: str) -> Pedido:
    """Se abrió por error: solo si nadie consumió nada (todo cancelado o sin enviar)."""
    pedido = cargar_pedido(db, empresa_id, pedido_id)
    _exigir_abierto(pedido)
    if any(l.estado not in (EstadoLinea.tomada, EstadoLinea.cancelada) for l in pedido.lineas):
        raise ErrorNegocio("El pedido tiene platos enviados: cancélalos primero.")
    for linea in pedido.lineas:
        linea.estado = EstadoLinea.cancelada
    pedido.estado = EstadoPedido.anulado
    pedido.cerrado_en = _ahora()
    db.flush()
    return pedido
