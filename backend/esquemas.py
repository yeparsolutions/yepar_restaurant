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
    mesa_id: Optional[int] = None          # sin mesa: mostrador o delivery
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


# ── Caja, cobro, propinas y cierre ───────────────────────────
class NombreIn(Entrada):
    nombre: str = Field(min_length=1, max_length=60)
    sucursal_id: Optional[int] = None


class CajaOut(BaseModel):
    id: int
    nombre: str
    sucursal_id: int


class TerminalOut(BaseModel):
    id: int
    nombre: str
    sucursal_id: int


class AbrirTurnoIn(Entrada):
    caja_id: int
    fondo: Decimal = Decimal("0")


class CerrarTurnoIn(Entrada):
    contado: Decimal
    nota: Optional[str] = Field(default=None, max_length=300)


class ArqueoOut(BaseModel):
    turno_id: int
    fondo: Dinero
    efectivo_cobrado: Dinero
    esperado: Dinero
    cantidad_pagos: int


class TurnoOut(BaseModel):
    id: int
    caja_id: int
    caja: str
    usuario_id: int
    estado: str
    abierto_en: Optional[datetime] = None
    fondo: Dinero
    cerrado_en: Optional[datetime] = None
    esperado: Optional[Dinero] = None
    contado: Optional[Dinero] = None
    diferencia: Optional[Dinero] = None
    nota: Optional[str] = None
    revisado_por_id: Optional[int] = None


class ConfigCobroIn(Entrada):
    propina_modo: Optional[Literal["por_mesa", "grupal"]] = None
    propina_sugerida_pct: Optional[Decimal] = None


class ConfigCobroOut(BaseModel):
    propina_modo: str
    propina_sugerida_pct: Porcentaje


class PropinaIn(Entrada):
    monto: Optional[Decimal] = None          # sin monto: la sugerida del restaurante


class DescuentoIn(Entrada):
    porcentaje: Decimal
    # Solo si el descuento pasa del tope del cajero: un supervisor teclea su PIN en la tablet.
    supervisor_id: Optional[int] = None
    pin_supervisor: Optional[str] = Field(default=None, max_length=6)


class PinIn(Entrada):
    pin: str = Field(min_length=4, max_length=6)
    password: str = Field(min_length=1, max_length=200)     # confirma que eres tú


class SupervisorOut(BaseModel):
    id: int
    nombre: str


class PagoIn(Entrada):
    medio: Literal["efectivo", "tarjeta", "transferencia"]
    monto: Decimal
    recibido: Optional[Decimal] = None       # solo efectivo
    numero_operacion: Optional[str] = Field(default=None, max_length=60)
    terminal_id: Optional[int] = None        # solo tarjeta
    pago_id: Optional[str] = Field(default=None, min_length=8, max_length=36)   # UUID de la tablet (modo sin conexión)


class PagoOut(BaseModel):
    id: str
    pedido_id: str
    medio: str
    monto: Dinero
    recibido: Optional[Dinero] = None
    vuelto: Optional[Dinero] = None
    numero_operacion: Optional[str] = None
    terminal_id: Optional[int] = None
    turno_id: Optional[int] = None
    pedido_estado: str
    cuenta: CuentaOut
    documento_estado: Optional[str] = None      # si se emitió sola la boleta al cerrar la mesa
    documento_folio: Optional[str] = None


class PropinaLibroOut(BaseModel):
    id: int
    pedido_id: Optional[str] = None
    mesero_id: Optional[int] = None
    modo: str
    monto: Dinero
    estado: str
    creado_en: Optional[datetime] = None


class SaldoPropinaOut(BaseModel):
    mesero_id: Optional[int] = None          # vacío = fondo grupal sin repartir
    monto: Dinero


class EntregaPropinaIn(Entrada):
    mesero_id: int


class EntregaPropinaOut(BaseModel):
    mesero_id: int
    entregado: Dinero


class RepartoIn(Entrada):
    """Partes iguales entre `participantes`, o proporcional con `pesos` ({id_usuario: peso}). Uno de los dos."""
    participantes: Optional[list[int]] = None
    pesos: Optional[dict[int, Decimal]] = None


class ParteRepartoOut(BaseModel):
    usuario_id: int
    monto: Dinero


class CuadreTerminalOut(BaseModel):
    terminal_id: int
    nombre: str
    cantidad: int
    total_registrado: Dinero
    total_reportado: Optional[Dinero] = None
    diferencia: Optional[Dinero] = None
    operaciones: list[list[str]]             # [[numero_operacion, monto], ...]


class TurnoConDiferenciaOut(BaseModel):
    turno_id: int
    diferencia: Dinero


class ResumenPeriodoOut(BaseModel):
    cerradas: int
    ventas: Dinero
    descuentos: Dinero
    propinas: Dinero
    total_cobrado: Dinero
    por_medio: dict[str, Dinero]
    turnos_con_diferencia: list[TurnoConDiferenciaOut]


# ── Facturación electrónica ──────────────────────────────────
class ConexionFacturacionIn(Entrada):
    proveedor: Literal["yepardte", "yeparfactura"]
    api_key: str = Field(min_length=8, max_length=200)


class ConexionFacturacionOut(BaseModel):
    proveedor: str
    activo: bool
    api_key_final: str                     # "••••1234": nunca se devuelve la clave completa
    emision_automatica: bool = False
    tipo_automatico: str = "boleta"


class ReceptorIn(Entrada):
    rut: Optional[str] = Field(default=None, max_length=20)
    nombre: Optional[str] = Field(default=None, max_length=200)
    cedula: Optional[str] = Field(default=None, max_length=30)      # Venezuela: cédula o pasaporte
    giro: Optional[str] = Field(default=None, max_length=200)
    direccion: Optional[str] = Field(default=None, max_length=300)
    email: Optional[str] = Field(default=None, max_length=200)
    telefono: Optional[str] = Field(default=None, max_length=40)


class EmitirDocumentoIn(Entrada):
    tipo: Literal["boleta", "factura"]
    receptor: Optional[ReceptorIn] = None


class AnularDocumentoIn(Entrada):
    motivo: str = Field(min_length=3, max_length=200)


class ConfigFacturacionIn(Entrada):
    emision_automatica: Optional[bool] = None
    tipo_automatico: Optional[Literal["boleta", "factura"]] = None


class DocumentoOut(BaseModel):
    id: int
    pedido_id: str
    proveedor: str
    tipo: str
    estado: str                            # pendiente | emitido | rechazado | anulado
    documento_origen_id: Optional[int] = None   # nota de crédito: el documento que anula
    motivo: Optional[str] = None
    folio: Optional[str] = None
    neto: Optional[Dinero] = None
    iva: Optional[Dinero] = None
    total: Optional[Dinero] = None
    pdf_url: Optional[str] = None
    moneda: Optional[str] = None            # moneda en que vendió el restaurante
    moneda_montos: Optional[str] = None     # moneda de neto/iva/total (Venezuela: VES)
    tasa_cambio: Optional[CostoUnitario] = None
    total_divisa: Optional[Dinero] = None
    intentos: int
    ultimo_error: Optional[str] = None


# ── Recepción de mercadería ──────────────────────────────────
class LineaFacturaIn(Entrada):
    """Una línea de la factura del proveedor (misma forma de cantidad y costo que CompraIn)."""
    item_id: int
    cantidad: Decimal
    unidad: Optional[str] = None
    presentacion_id: Optional[int] = None
    monto_neto: Optional[Decimal] = None
    costo_unitario_base: Optional[Decimal] = None


class FacturaCompraIn(Entrada):
    proveedor: str = Field(min_length=1, max_length=120)
    numero_documento: Optional[str] = Field(default=None, max_length=60)
    nota: Optional[str] = Field(default=None, max_length=500)
    lineas: list[LineaFacturaIn] = Field(min_length=1)


class LineaRecibidaIn(Entrada):
    linea_id: int
    cantidad: Decimal                      # lo que llegó; 0 si no llegó
    unidad: Optional[str] = None
    presentacion_id: Optional[int] = None


class RecepcionIn(Entrada):
    lineas: list[LineaRecibidaIn] = Field(min_length=1)


class CompraLineaOut(BaseModel):
    id: int
    item_id: int
    item: str
    unidad_base: str
    cantidad_facturada: Cantidad
    costo_unitario_base: CostoUnitario
    cantidad_recibida: Optional[Cantidad] = None
    diferencia: Optional[Cantidad] = None   # recibida − facturada (negativa = faltó)


class CompraRecepcionOut(BaseModel):
    id: int
    sucursal_id: int
    proveedor: str
    numero_documento: Optional[str] = None
    estado: str
    nota: Optional[str] = None
    lineas: list[CompraLineaOut]


class CompraResumenOut(BaseModel):
    id: int
    proveedor: str
    numero_documento: Optional[str] = None
    estado: str
    lineas: int


# Vista CIEGA para quien recibe: sin cantidades facturadas ni costos.
class PresentacionCiegaOut(BaseModel):
    id: int
    nombre: str


class LineaCiegaOut(BaseModel):
    linea_id: Optional[int] = None
    item_id: int
    item: str
    unidad_base: str
    presentaciones: list[PresentacionCiegaOut]
    contada: Optional[Cantidad] = None


class RecepcionCiegaOut(BaseModel):
    id: int
    proveedor: str
    lineas: list[LineaCiegaOut]


# ── Inventario físico ciego ──────────────────────────────────
class InventarioNuevoIn(Entrada):
    categoria_id: Optional[int] = None
    nota: Optional[str] = Field(default=None, max_length=500)


class ConteoIn(Entrada):
    item_id: int
    cantidad: Decimal
    unidad: Optional[str] = None
    presentacion_id: Optional[int] = None


class RecuentoIn(Entrada):
    item_ids: list[int] = Field(min_length=1)


class InventarioResumenOut(BaseModel):
    id: int
    sucursal_id: int
    estado: str
    categoria_id: Optional[int] = None
    nota: Optional[str] = None
    total_items: int
    contados: int


class ConteoCiegoOut(BaseModel):
    id: int
    estado: str
    total_items: int
    contados: int
    lineas: list[LineaCiegaOut]


class LineaRevisionOut(BaseModel):
    item_id: int
    item: str
    unidad_base: str
    cantidad_sistema: Cantidad
    cantidad_contada: Optional[Cantidad] = None
    diferencia: Cantidad
    valor_diferencia: Dinero


class RevisionOut(BaseModel):
    id: int
    estado: str
    lineas: list[LineaRevisionOut]
    con_diferencia: int
    valor_total_diferencia: Dinero


class CierreInventarioOut(BaseModel):
    id: int
    estado: str
    ajustes: int


# ── Sincronización de la tablet (modo sin conexión) ──────────
class RefPedidoIn(Entrada):
    pedido_id: str = Field(min_length=8, max_length=36)


class RefLineaIn(Entrada):
    linea_id: str = Field(min_length=8, max_length=36)


class TomarLineaSyncIn(TomarLineaIn):
    pedido_id: str = Field(min_length=8, max_length=36)


class AbrirPedidoSyncIn(AbrirPedidoIn):
    pedido_id: str = Field(min_length=8, max_length=36)       # sin conexión la tablet siempre lo genera


class OperacionIn(Entrada):
    op_id: str = Field(min_length=8, max_length=36)            # UUID de esta operación (la clave de idempotencia)
    tipo: Literal["abrir_pedido", "tomar_linea", "quitar_linea", "enviar", "cancelar_linea",
                  "pedir_cuenta", "anular_pedido"]
    datos: dict = {}


class SincronizarIn(Entrada):
    operaciones: list[OperacionIn] = Field(min_length=1, max_length=200)


class ResultadoOperacionOut(BaseModel):
    op_id: str
    tipo: str
    estado: str                         # aplicada | rechazada
    repetida: bool = False              # ya se había procesado antes: se devuelve el mismo resultado
    error: Optional[str] = None


class SincronizarOut(BaseModel):
    resultados: list[ResultadoOperacionOut]
    aplicadas: int
    rechazadas: int


# ── Carga masiva y asistente de arranque ─────────────────────
class ErrorFilaOut(BaseModel):
    hoja: str
    fila: int
    mensaje: str


class ReporteCargaOut(BaseModel):
    valido: bool
    aplicado: bool                       # True solo si se importó de verdad
    insumos: int
    platos: int
    recetas: int
    con_stock_inicial: int
    categorias_nuevas: int
    errores: list[ErrorFilaOut]


class PasoArranqueOut(BaseModel):
    clave: str
    titulo: str
    hecho: bool
    detalle: str


class AsistenteOut(BaseModel):
    pasos: list[PasoArranqueOut]
    completados: int
    total: int
    siguiente: Optional[str] = None      # título del primer paso pendiente


# ── Sucursales y personal ────────────────────────────────────
Rol = Literal["administrador", "cajero", "mesero", "cocinero"]


class SucursalIn(Entrada):
    nombre: str = Field(min_length=1, max_length=150)


class SucursalOut(BaseModel):
    id: int
    nombre: str


class PersonaIn(Entrada):
    nombre: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)
    roles: list[Rol] = Field(min_length=1)
    sucursal_id: Optional[int] = None
    estacion: Optional[Literal["cocina", "barra"]] = None
    descuento_max_pct: Decimal = Decimal("0")


class PersonaCambiosIn(Entrada):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    roles: Optional[list[Rol]] = Field(default=None, min_length=1)
    sucursal_id: Optional[int] = None
    estacion: Optional[Literal["cocina", "barra"]] = None
    descuento_max_pct: Optional[Decimal] = None
    activo: Optional[bool] = None


class PasswordNuevaIn(Entrada):
    password: str = Field(min_length=1, max_length=200)


class CambiarPasswordIn(Entrada):
    actual: str = Field(min_length=1, max_length=200)
    nueva: str = Field(min_length=1, max_length=200)


class PersonaOut(BaseModel):
    id: int
    nombre: str
    username: str
    roles: list[str]
    sucursal_id: Optional[int] = None
    estacion: Optional[str] = None
    descuento_max_pct: Porcentaje
    activo: bool
    tiene_pin: bool


# ── Delivery con Yepar Go ────────────────────────────────────
class ConexionDespachoIn(Entrada):
    api_key: str = Field(min_length=1, max_length=200)
    direccion_retiro: Optional[str] = Field(default=None, max_length=300)     # dónde retira el motorista (el local)
    centro_retiro_id: Optional[str] = Field(default=None, max_length=40)


class ConexionDespachoOut(BaseModel):
    proveedor: str = "yepargo"
    activo: bool
    api_key_final: str
    direccion_retiro: Optional[str] = None
    centro_retiro_id: Optional[str] = None


class CentroRetiroOut(BaseModel):
    id: str
    nombre: str
    direccion: Optional[str] = None


class DespachoIn(Entrada):
    destinatario: str = Field(min_length=2, max_length=150)
    direccion: str = Field(min_length=3, max_length=300)
    telefono: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=150)
    ciudad: Optional[str] = Field(default=None, max_length=100)
    region: Optional[str] = Field(default=None, max_length=100)
    latitud: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    longitud: Optional[Decimal] = Field(default=None, ge=-180, le=180)
    notas: Optional[str] = Field(default=None, max_length=300)


class DespachoOut(BaseModel):
    id: int
    pedido_id: str
    estado: str                                # pendiente | creado | rechazado
    destinatario: str
    direccion: str
    telefono: Optional[str] = None
    go_numero: Optional[str] = None            # número de la orden en Yepar Go (YGO-...)
    estado_go: Optional[str] = None            # estado vivo: pending | assigned | in_route | delivered | ...
    seguimiento_url: Optional[str] = None      # link que se le envía al cliente
    intentos: int
    ultimo_error: Optional[str] = None
