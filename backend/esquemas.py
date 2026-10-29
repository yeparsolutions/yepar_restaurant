# ============================================================
# YEPAR RESTAURANT — backend/esquemas.py
# Formas de los datos que entran y salen por la API.
#
# Analogía: son los "formularios" que se llenan en la ventanilla.
# Los montos y cantidades viajan como TEXTO ("6500.00") para no perder
# decimales en el camino (un número JSON puede redondear); la tablet
# los muestra tal cual o los convierte al mostrarlos.
# ============================================================

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, Field, PlainSerializer


# Montos: siempre con 2 decimales y como TEXTO ("6500.00"); cantidades de stock con 3.
Dinero = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json")]
Cantidad = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.3f}", return_type=str, when_used="json")]


class Entrada(BaseModel):
    """Base de lo que envía el cliente: rechaza campos desconocidos (evita typos silenciosos)."""
    model_config = {"extra": "forbid"}


# ── Auth ─────────────────────────────────────────────────────
class LoginIn(Entrada):
    codigo_empresa: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class UsuarioOut(BaseModel):
    id: int
    nombre: str
    roles: list[str]
    estacion: Optional[str] = None
    sucursal_id: Optional[int] = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioOut


# ── Mesas ────────────────────────────────────────────────────
class MesaIn(Entrada):
    nombre: str = Field(min_length=1, max_length=40)
    capacidad: int = 4
    pos_x: int = 0
    pos_y: int = 0
    ancho: int = 80
    alto: int = 80
    forma: str = "cuadrada"
    sucursal_id: Optional[int] = None


class PosicionIn(Entrada):
    pos_x: int
    pos_y: int
    ancho: Optional[int] = None
    alto: Optional[int] = None


class MesaOut(BaseModel):
    id: int
    sucursal_id: int
    nombre: str
    capacidad: int
    pos_x: int
    pos_y: int
    ancho: int
    alto: int
    forma: str
    qr_token: str


class EstadoMesaOut(BaseModel):
    mesa_id: int
    nombre: str
    estado: str                       # libre | ocupada | lista | cuenta_pedida
    pedido_id: Optional[str] = None
    mesero_id: Optional[int] = None
    lineas_listas: int = 0


# ── Carta y disponibilidad ───────────────────────────────────
class FaltaOut(BaseModel):
    item_id: int
    nombre: str
    falta: Cantidad
    agotado_manual: bool


class DisponibilidadOut(BaseModel):
    item_id: int
    nombre: str
    alcanza: bool
    faltas: list[FaltaOut]


class ItemCartaOut(BaseModel):
    item_id: int
    nombre: str
    precio_venta: Optional[Dinero] = None
    foto_url: Optional[str] = None
    estacion: str
    alcanza: bool
    faltas: list[FaltaOut]


# ── Pedidos ──────────────────────────────────────────────────
class AbrirPedidoIn(Entrada):
    mesa_id: int
    comensales: Optional[int] = None
    pedido_id: Optional[str] = Field(default=None, max_length=36)      # UUID generado por la tablet (sin conexión)
    sucursal_id: Optional[int] = None


class TomarLineaIn(Entrada):
    item_id: int
    cantidad: int = 1
    comensal: Optional[int] = None
    sin_ingredientes: list[int] = []
    extra_ids: list[int] = []
    nota: Optional[str] = Field(default=None, max_length=255)
    linea_id: Optional[str] = Field(default=None, max_length=36)


class TraspasoIn(Entrada):
    nuevo_mesero_id: int


class LineaOut(BaseModel):
    id: str
    item_id: int
    nombre: str
    cantidad: int
    precio_unitario: Dinero
    comensal: Optional[int] = None
    nota: Optional[str] = None
    estado: str
    estacion: str
    quitados: list[int]
    extras: list[int]
    total: Dinero


class CuentaOut(BaseModel):
    subtotal: Dinero
    descuento: Dinero
    propina: Dinero
    total: Dinero
    pagado: Dinero
    pendiente: Dinero


class PedidoOut(BaseModel):
    id: str
    mesa_id: Optional[int] = None
    mesa: Optional[str] = None
    mesero_id: Optional[int] = None
    estado: str
    comensales: Optional[int] = None
    lineas: list[LineaOut]
    cuenta: CuentaOut


class TomarLineaOut(BaseModel):
    linea: LineaOut
    disponibilidad: DisponibilidadOut


class FaltanteOut(BaseModel):
    item_id: int
    nombre: str
    falta: Cantidad


class EnvioOut(BaseModel):
    lineas: list[LineaOut]
    faltantes: list[FaltanteOut]          # para alertar al administrador


class RetiroOut(BaseModel):
    linea_id: str
    pedido_id: str
    mesa: str
    plato: str
    cantidad: int
    estacion: str
    lista_en: Optional[datetime] = None


# ── Cocina ───────────────────────────────────────────────────
class ComandaOut(BaseModel):
    linea_id: str
    pedido_id: str
    mesa: str
    mesero_id: Optional[int] = None
    plato: str
    cantidad: int
    estado: str
    comensal: Optional[int] = None
    nota: Optional[str] = None
    sin: list[str]
    extras: list[str]
    enviada_en: Optional[datetime] = None
    receta_id: Optional[int] = None


class ListoOut(BaseModel):
    linea: LineaOut
    sin_stock: list[str]                  # ingredientes que quedaron en negativo


class AgotadoOut(BaseModel):
    platos_agotados: list[str]
