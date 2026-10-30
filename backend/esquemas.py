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
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, PlainSerializer


# Montos: siempre con 2 decimales y como TEXTO ("6500.00"); cantidades de stock con 3.
Dinero = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json")]
Cantidad = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.3f}", return_type=str, when_used="json")]
CostoUnitario = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.6f}", return_type=str, when_used="json")]
Porcentaje = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.1f}", return_type=str, when_used="json")]


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


# ── Catálogo ─────────────────────────────────────────────────
class UnidadOut(BaseModel):
    codigo: str
    nombre: str
    familia: str
    factor_a_base: Decimal
    es_base: bool


class CategoriaIn(Entrada):
    nombre: str = Field(min_length=1, max_length=100)
    orden: int = 0


class CategoriaOut(BaseModel):
    id: int
    nombre: str
    orden: int


class ItemIn(Entrada):
    tipo: Literal["materia_prima", "componente", "vendible_preparado", "vendible_reventa"]
    nombre: str = Field(min_length=1, max_length=200)
    unidad_base: str                           # 'g', 'ml' o 'und'
    precio_venta: Optional[Decimal] = None
    categoria_id: Optional[int] = None
    stock_minimo: Decimal = Decimal("0")
    estacion: Optional[Literal["cocina", "barra"]] = None   # solo vendibles
    foto_url: Optional[str] = Field(default=None, max_length=500)
    codigo_barra: Optional[str] = Field(default=None, max_length=100)


class ItemCambiosIn(Entrada):
    """Solo se cambia lo que se envía (el tipo y la unidad base no se modifican)."""
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=200)
    precio_venta: Optional[Decimal] = None
    categoria_id: Optional[int] = None
    stock_minimo: Optional[Decimal] = None
    estacion: Optional[Literal["cocina", "barra"]] = None
    foto_url: Optional[str] = Field(default=None, max_length=500)
    codigo_barra: Optional[str] = Field(default=None, max_length=100)
    activo: Optional[bool] = None


class ItemOut(BaseModel):
    id: int
    tipo: str
    nombre: str
    unidad_base: str
    categoria_id: Optional[int] = None
    precio_venta: Optional[Dinero] = None
    estacion: Optional[str] = None
    foto_url: Optional[str] = None
    codigo_barra: Optional[str] = None
    stock_minimo: Cantidad
    costo_promedio: CostoUnitario
    costo_ultimo: CostoUnitario
    costo_referencia: CostoUnitario
    agotado_manual: bool
    activo: bool
    tiene_receta: bool


class PresentacionIn(Entrada):
    nombre: str = Field(min_length=1, max_length=60)
    cantidad_en_base: Decimal
    es_defecto: bool = False


class PresentacionOut(BaseModel):
    id: int
    item_id: int
    nombre: str
    cantidad_en_base: Cantidad
    es_defecto: bool


class ExtraIn(Entrada):
    nombre: str = Field(min_length=1, max_length=100)
    precio: Decimal
    ingrediente_id: int
    cantidad: Decimal
    aplica_a_todos: bool = True
    plato_ids: list[int] = []


class ExtraOut(BaseModel):
    id: int
    nombre: str
    precio: Dinero
    ingrediente_id: int
    cantidad: Cantidad
    aplica_a_todos: bool
    plato_ids: list[int]
    activo: bool


# ── Recetas y costos ─────────────────────────────────────────
class LineaRecetaIn(Entrada):
    ingrediente_id: int
    cantidad: Decimal
    unidad: Optional[str] = None               # 'kg', 'g'...; sin unidad = ya viene en la unidad base
    es_removible: bool = False


class RecetaIn(Entrada):
    rendimiento: Decimal
    rendimiento_unidad: Optional[str] = None
    instrucciones: Optional[str] = None
    lineas: list[LineaRecetaIn]


class LineaRecetaOut(BaseModel):
    ingrediente_id: int
    nombre: str
    cantidad: Cantidad                         # en la unidad base del ingrediente
    unidad: str
    es_removible: bool
    orden: int


class RecetaOut(BaseModel):
    item_id: int
    nombre: str
    rendimiento: Cantidad
    unidad: str
    instrucciones: Optional[str] = None
    lineas: list[LineaRecetaOut]


class CostoLineaOut(BaseModel):
    ingrediente_id: int
    nombre: str
    cantidad: Cantidad
    costo_unitario: CostoUnitario
    costo_linea: Dinero


class CostoRecetaOut(BaseModel):
    item_id: int
    nombre: str
    rendimiento: Cantidad
    costo_total: Dinero
    costo_unitario: CostoUnitario
    precio_venta: Optional[Dinero] = None
    margen_pct: Optional[Porcentaje] = None    # (precio − costo) / precio, solo en vendibles con precio
    lineas: list[CostoLineaOut]


# ── Inventario ───────────────────────────────────────────────
class CompraIn(Entrada):
    """Ingreso de mercadería. Cantidad: con `unidad`, con `presentacion_id` o ya en base.
    Costo: `monto_neto` (toda la línea, sin IVA) O `costo_unitario_base`."""
    item_id: int
    cantidad: Decimal
    unidad: Optional[str] = None
    presentacion_id: Optional[int] = None
    monto_neto: Optional[Decimal] = None
    costo_unitario_base: Optional[Decimal] = None
    nota: Optional[str] = Field(default=None, max_length=255)


class CompraOut(BaseModel):
    movimiento_id: int
    item_id: int
    cantidad_base: Cantidad
    costo_unitario_base: CostoUnitario
    costo_promedio: CostoUnitario
    costo_referencia: CostoUnitario
    stock_nuevo: Cantidad


class ProduccionIn(Entrada):
    item_id: int
    cantidad_producida: Optional[Decimal] = None      # en unidad base; si falta, el rendimiento de la receta
    nota: Optional[str] = Field(default=None, max_length=255)


class ProduccionOut(BaseModel):
    lote_id: int
    item_id: int
    cantidad_producida: Cantidad
    costo_total: Dinero
    costo_unitario: CostoUnitario
    faltantes: list[str]


class MermaIn(Entrada):
    item_id: int
    cantidad: Decimal                                  # positiva, en unidad base
    motivo: Literal["vencido", "danado", "error_preparacion", "sobrante", "derrame"]
    nota: Optional[str] = Field(default=None, max_length=255)


class MovimientoOut(BaseModel):
    id: int
    item_id: int
    tipo: str
    cantidad: Cantidad
    stock_anterior: Cantidad
    stock_nuevo: Cantidad
    motivo_merma: Optional[str] = None
    referencia_tipo: Optional[str] = None
    referencia_id: Optional[str] = None
    nota: Optional[str] = None


class StockOut(BaseModel):
    item_id: int
    nombre: str
    tipo: str
    unidad: str
    fisico: Cantidad
    reservado: Cantidad
    disponible: Cantidad
    stock_minimo: Cantidad


class AlertaOut(BaseModel):
    item_id: int
    nombre: str
    tipo: str
    disponible: Cantidad
    stock_minimo: Cantidad
    se_produce: bool


class LineaCompraOut(BaseModel):
    item_id: int
    nombre: str
    cantidad_base: Cantidad
    unidad: str
    presentacion: Optional[str] = None
    cantidad_presentacion: Optional[int] = None
    costo_estimado: Dinero


class ListaComprasOut(BaseModel):
    lineas: list[LineaCompraOut]
    costo_total_estimado: Dinero
