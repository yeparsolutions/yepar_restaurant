# ============================================================
# YEPAR RESTAURANT — backend/servicios/mesas.py
# Plano del local: crear mesas, ubicarlas, anclarse por QR y ver su estado.
#
# Analogía: es el plano de sala que cuelga en la pared. Cada mesa
# tiene un lugar en el plano y una luz: libre (apagada), ocupada,
# lista (se enciende: hay comida para retirar) o cuenta pedida.
#
# Los servicios no hacen commit (lo decide quien llama).
# ============================================================

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import EstadoLinea, EstadoPedido, Mesa, Pedido
from servicios.stock import validar_sucursal

FORMAS = ("cuadrada", "redonda", "rectangular")

# Estados que muestra la luz de la mesa en el plano.
LIBRE, OCUPADA, LISTA, CUENTA_PEDIDA = "libre", "ocupada", "lista", "cuenta_pedida"


@dataclass
class EstadoMesa:
    mesa_id: int
    nombre: str
    estado: str                       # libre | ocupada | lista | cuenta_pedida
    pedido_id: Optional[str] = None
    mesero_id: Optional[int] = None
    lineas_listas: int = 0            # cuántos platos esperan ser retirados
    # Para dibujar el plano (el administrador las acomoda; la tablet las muestra donde corresponde).
    capacidad: int = 4
    pos_x: int = 0
    pos_y: int = 0
    ancho: int = 80
    alto: int = 80
    forma: str = "cuadrada"


def crear_mesa(db: Session, *, empresa_id: int, sucursal_id: int, nombre: str, capacidad: int = 4,
               pos_x: int = 0, pos_y: int = 0, ancho: int = 80, alto: int = 80,
               forma: str = "cuadrada") -> Mesa:
    validar_sucursal(db, empresa_id, sucursal_id)
    nombre = (nombre or "").strip()
    if not nombre:
        raise ErrorNegocio("La mesa necesita un nombre.")
    if capacidad <= 0:
        raise ErrorNegocio("La capacidad de la mesa debe ser mayor que cero.")
    if forma not in FORMAS:
        raise ErrorNegocio(f"Forma de mesa inválida: elige entre {', '.join(FORMAS)}.")
    if db.query(Mesa).filter_by(sucursal_id=sucursal_id, nombre=nombre).first() is not None:
        raise ErrorNegocio(f"Ya existe una mesa llamada '{nombre}' en este local.")
    mesa = Mesa(empresa_id=empresa_id, sucursal_id=sucursal_id, nombre=nombre, capacidad=capacidad,
                pos_x=pos_x, pos_y=pos_y, ancho=ancho, alto=alto, forma=forma)
    db.add(mesa)
    db.flush()
    return mesa


def cargar_mesa(db: Session, empresa_id: int, mesa_id: int) -> Mesa:
    """Una mesa de ESTE cliente; si es de otro, responde 'no existe'."""
    mesa = db.get(Mesa, mesa_id)
    if mesa is None or mesa.empresa_id != empresa_id:
        raise ErrorNoEncontrado("La mesa no existe.")
    return mesa


def posicionar_mesa(db: Session, *, empresa_id: int, mesa_id: int, pos_x: int, pos_y: int,
                    ancho: Optional[int] = None, alto: Optional[int] = None) -> Mesa:
    """El administrador arrastra la mesa en el plano."""
    mesa = cargar_mesa(db, empresa_id, mesa_id)
    mesa.pos_x, mesa.pos_y = pos_x, pos_y
    if ancho is not None:
        mesa.ancho = ancho
    if alto is not None:
        mesa.alto = alto
    db.flush()
    return mesa


def mesa_por_qr(db: Session, *, empresa_id: int, qr_token: str) -> Mesa:
    """El mesero escanea el QR de la mesa para anclarse a ella (atajo, no la única forma)."""
    mesa = db.query(Mesa).filter_by(empresa_id=empresa_id, qr_token=qr_token, activa=True).one_or_none()
    if mesa is None:
        raise ErrorNoEncontrado("La mesa no existe.")
    return mesa


def estado_mesas(db: Session, *, empresa_id: int, sucursal_id: int) -> list:
    """El plano con la luz de cada mesa (solo mesas activas de este local)."""
    validar_sucursal(db, empresa_id, sucursal_id)
    mesas = (db.query(Mesa).filter_by(empresa_id=empresa_id, sucursal_id=sucursal_id, activa=True)
             .order_by(Mesa.nombre).all())
    abiertos = {
        p.mesa_id: p for p in db.query(Pedido).filter(
            Pedido.empresa_id == empresa_id, Pedido.sucursal_id == sucursal_id,
            Pedido.estado.in_((EstadoPedido.abierto, EstadoPedido.cuenta_pedida)))
    }
    resultado = []
    for mesa in mesas:
        pedido = abiertos.get(mesa.id)
        plano = dict(capacidad=mesa.capacidad, pos_x=mesa.pos_x, pos_y=mesa.pos_y, ancho=mesa.ancho,
                     alto=mesa.alto, forma=mesa.forma)
        if pedido is None:
            resultado.append(EstadoMesa(mesa.id, mesa.nombre, LIBRE, **plano))
            continue
        listas = sum(1 for l in pedido.lineas if l.estado == EstadoLinea.lista)
        if listas:
            estado = LISTA
        elif pedido.estado == EstadoPedido.cuenta_pedida:
            estado = CUENTA_PEDIDA
        else:
            estado = OCUPADA
        resultado.append(EstadoMesa(mesa.id, mesa.nombre, estado, pedido.id, pedido.mesero_id, listas, **plano))
    return resultado
