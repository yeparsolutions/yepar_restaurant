# ============================================================
# YEPAR RESTAURANT — backend/models/inventario.py
# NÚCLEO DEL INVENTARIO: ítems, unidades, recetas, stock y movimientos.
# Es el corazón del producto; todo lo demás (pedidos, cocina, cobro)
# se apoya en estas tablas.
#
# REGLAS DE DISEÑO (acordadas en el documento de definición):
#
#  1. Todo el stock y todas las recetas se guardan en la UNIDAD BASE
#     del ítem (gramos, mililitros o unidades). Compras en kilos, cajas
#     o litros se convierten al entrar; las recetas ya vienen en base.
#     Analogía: la bodega mide todo con UNA sola regla; las demás reglas
#     (kilo, caja, litro) se traducen al entrar y nunca se guardan.
#
#  2. Las cantidades son Numeric (decimal exacto), NUNCA Float, para que
#     1000 g - 80 g - 80 g... no acumule errores de redondeo.
#     (En Carora eran Integer; por eso este núcleo no se reutiliza.)
#
#  3. Faltar un ingrediente solo ALERTA, no bloquea el pedido. Por eso
#     el stock físico PUEDE quedar negativo: no hay CHECK >= 0 a propósito.
#
#  4. El costo se guarda por unidad base (ej. $/gramo) y el costo de
#     referencia para platos y precios es el MAYOR entre el promedio
#     ponderado y el último precio de compra.
#
#  5. Los movimientos de stock son un libro contable: solo se agregan
#     filas, nunca se editan ni se borran.
# ============================================================

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index,
                        Integer, Numeric, String, Text, UniqueConstraint, false,
                        func, true)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.enums import (TIPOS_CON_RECETA, TIPOS_VENDIBLES, FamiliaUnidad,
                          MotivoMerma, TipoItem, TipoMovimientoStock,
                          columna_enum)

# Tipos de columna reutilizados en todo el archivo.
CANTIDAD = Numeric(14, 3)    # cantidades en unidad base (hasta milésimas)
COSTO_UNITARIO = Numeric(18, 6)   # $ por unidad base (ej. 1,5 $/g); necesita más decimales
DINERO = Numeric(16, 2)      # montos totales en moneda local


# ============================================================
# TABLA: unidades  (catálogo GLOBAL, igual para todos los clientes)
# ============================================================
class Unidad(Base):
    """
    Una unidad de medida estándar. `factor_a_base` dice cuántas unidades
    base de su familia vale UNA de esta unidad:
        kg → 1000 (porque 1 kg = 1000 g)      l → 1000 (1 l = 1000 ml)
        cc → 1    (1 cc = 1 ml)               g, ml, und → 1 (son las base)
    Las conversiones propias de un ítem (caja de 12, saco de 25 kg)
    van en `ItemPresentacion`, no acá.
    """
    __tablename__ = "unidades"
    __table_args__ = (
        CheckConstraint("factor_a_base > 0", name="ck_unidad_factor_positivo"),
        # Una unidad marcada como base SIEMPRE vale 1 (es la regla de medir).
        CheckConstraint("NOT es_base OR factor_a_base = 1", name="ck_unidad_base_vale_uno"),
    )

    id:            Mapped[int]            = mapped_column(primary_key=True)
    codigo:        Mapped[str]            = mapped_column(String(10), unique=True)   # 'g', 'kg', 'ml', 'cc', 'l', 'und'
    nombre:        Mapped[str]            = mapped_column(String(40))
    familia:       Mapped[FamiliaUnidad]  = mapped_column(columna_enum(FamiliaUnidad))
    factor_a_base: Mapped[Decimal]        = mapped_column(Numeric(18, 6))
    es_base:       Mapped[bool]           = mapped_column(Boolean, default=False)


# ============================================================
# TABLA: categorias_item
# Sirven para inventariar por categoría (ej. solo "Congelados").
# ============================================================
class CategoriaItem(Base):
    __tablename__ = "categorias_item"
    __table_args__ = (UniqueConstraint("empresa_id", "nombre", name="uq_categoria_item_empresa_nombre"),)

    id:         Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    nombre:     Mapped[str] = mapped_column(String(100))
    orden:      Mapped[int] = mapped_column(Integer, default=0)


# ============================================================
# TABLA: items
# Un solo catálogo para los cuatro tipos (ver TipoItem). El mesero
# solo ve los de tipo vendible; el resto vive en bodega y cocina.
# ============================================================
class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("empresa_id", "nombre", name="uq_item_empresa_nombre"),
        UniqueConstraint("empresa_id", "codigo_barra", name="uq_item_empresa_codigo_barra"),
        CheckConstraint("precio_venta IS NULL OR precio_venta >= 0", name="ck_item_precio_no_negativo"),
        CheckConstraint("stock_minimo >= 0", name="ck_item_stock_minimo_no_negativo"),
        Index("ix_item_empresa_tipo", "empresa_id", "tipo"),
    )

    id:             Mapped[int]           = mapped_column(primary_key=True)
    empresa_id:     Mapped[int]           = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    tipo:           Mapped[TipoItem]      = mapped_column(columna_enum(TipoItem))
    nombre:         Mapped[str]           = mapped_column(String(200))
    codigo_barra:   Mapped[Optional[str]] = mapped_column(String(100))    # útil en reventa (bebidas)
    categoria_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("categorias_item.id", ondelete="SET NULL"), index=True)

    # Unidad en la que se guarda TODO el stock de este ítem. Debe ser una
    # unidad base (g, ml o und); lo valida unidades.exigir_unidad_base().
    unidad_base_id: Mapped[int]           = mapped_column(ForeignKey("unidades.id"))

    # ── Solo vendibles ──────────────────────────────────────
    precio_venta:   Mapped[Optional[Decimal]] = mapped_column(DINERO)
    foto_url:       Mapped[Optional[str]]     = mapped_column(String(500))   # recomendada, no obligatoria

    # ── Costos, por unidad base (ej. $ por gramo) ───────────
    costo_promedio: Mapped[Decimal] = mapped_column(COSTO_UNITARIO, default=Decimal("0"), server_default="0")
    costo_ultimo:   Mapped[Decimal] = mapped_column(COSTO_UNITARIO, default=Decimal("0"), server_default="0")

    # Bajo este nivel (por sucursal, en unidad base) se alerta al admin
    # y el ítem entra en la lista de compras sugerida.
    stock_minimo:   Mapped[Decimal] = mapped_column(CANTIDAD, default=Decimal("0"), server_default="0")

    # Botón "se acabó" del cocinero: marca el ítem agotado aunque el sistema
    # crea que hay stock. Los platos que lo usan quedan agotados para el mesero.
    agotado_manual: Mapped[bool]    = mapped_column(Boolean, default=False, server_default=false())

    activo:         Mapped[bool]     = mapped_column(Boolean, default=True, server_default=true())
    creado_en:      Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    unidad_base:    Mapped["Unidad"]                    = relationship()
    categoria:      Mapped[Optional["CategoriaItem"]]   = relationship()
    presentaciones: Mapped[list["ItemPresentacion"]]    = relationship(back_populates="item", cascade="all, delete-orphan")
    receta:         Mapped[Optional["Receta"]]          = relationship(back_populates="item", uselist=False, cascade="all, delete-orphan")

    @property
    def es_vendible(self) -> bool:
        """True si el mesero lo ve en la carta."""
        return self.tipo in TIPOS_VENDIBLES

    @property
    def lleva_receta(self) -> bool:
        """True si debe tener una Receta (componentes y vendibles preparados)."""
        return self.tipo in TIPOS_CON_RECETA

    @property
    def costo_referencia(self) -> Decimal:
        """
        Costo que usan los platos y el precio sugerido: el MAYOR entre el
        promedio ponderado y el último precio de compra. Así, cuando un
        proveedor sube el precio, el margen no se infla con precios viejos.
        """
        return max(self.costo_promedio or Decimal("0"), self.costo_ultimo or Decimal("0"))


# ============================================================
# TABLA: item_presentaciones
# Las "reglas extra" de compra de UN ítem: caja de 12 unidades, saco
# de 25 kg, bandeja de 30 huevos. Las unidades estándar (kg, l, cc)
# NO se guardan acá: salen del catálogo `unidades`.
# ============================================================
class ItemPresentacion(Base):
    __tablename__ = "item_presentaciones"
    __table_args__ = (
        UniqueConstraint("item_id", "nombre", name="uq_presentacion_item_nombre"),
        CheckConstraint("cantidad_en_base > 0", name="ck_presentacion_cantidad_positiva"),
    )

    id:               Mapped[int]     = mapped_column(primary_key=True)
    item_id:          Mapped[int]     = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    nombre:           Mapped[str]     = mapped_column(String(60))            # "Caja 12 un", "Saco 25 kg"
    # Cuántas unidades BASE trae UNA presentación (saco 25 kg de harina → 25000 g).
    cantidad_en_base: Mapped[Decimal] = mapped_column(CANTIDAD)
    es_defecto:       Mapped[bool]    = mapped_column(Boolean, default=False, server_default=false())

    item: Mapped["Item"] = relationship(back_populates="presentaciones")


# ============================================================
# TABLA: recetas  +  receta_lineas
# Una receta por ítem (componente o vendible preparado). Las
# cantidades de cada línea van en la unidad BASE del ingrediente.
#
# Un componente puede ser ingrediente de otro (la salsa de ajo
# entra en la hamburguesa). Evitar ciclos (A usa B y B usa A) es
# responsabilidad del servicio que guarda la receta.
# ============================================================
class Receta(Base):
    __tablename__ = "recetas"
    __table_args__ = (
        UniqueConstraint("item_id", name="uq_receta_item"),
        CheckConstraint("rendimiento > 0", name="ck_receta_rendimiento_positivo"),
    )

    id:         Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    item_id:    Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))

    # Cuánto SALE de producir esta receta, en la unidad base del ítem producido.
    #   Componente: 1 lote de salsa de ajo rinde 1000 ml.
    #   Plato o trago: rinde 1 und (una hamburguesa, un trago).
    # El costo unitario es (suma del costo de las líneas) / rendimiento.
    rendimiento:   Mapped[Decimal]       = mapped_column(CANTIDAD, default=Decimal("1"))
    instrucciones: Mapped[Optional[str]] = mapped_column(Text)    # lo que lee el cocinero
    creado_en:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    item:   Mapped["Item"]               = relationship(back_populates="receta")
    lineas: Mapped[list["RecetaLinea"]]  = relationship(
        back_populates="receta", cascade="all, delete-orphan", order_by="RecetaLinea.orden"
    )


class RecetaLinea(Base):
    __tablename__ = "receta_lineas"
    __table_args__ = (
        UniqueConstraint("receta_id", "ingrediente_id", name="uq_receta_linea_ingrediente"),
        CheckConstraint("cantidad > 0", name="ck_receta_linea_cantidad_positiva"),
    )

    id:             Mapped[int]     = mapped_column(primary_key=True)
    receta_id:      Mapped[int]     = mapped_column(ForeignKey("recetas.id", ondelete="CASCADE"), index=True)
    ingrediente_id: Mapped[int]     = mapped_column(ForeignKey("items.id"), index=True)    # materia prima o componente
    # En la unidad base del INGREDIENTE (80 → 80 g de tomate).
    cantidad:       Mapped[Decimal] = mapped_column(CANTIDAD)
    # Si es True, el mesero puede quitarlo al pedir ("sin cebolla"): no se
    # descuenta su stock ni su costo, pero el precio de venta no cambia.
    es_removible:   Mapped[bool]    = mapped_column(Boolean, default=False, server_default=false())
    orden:          Mapped[int]     = mapped_column(Integer, default=0)

    receta:      Mapped["Receta"] = relationship(back_populates="lineas")
    ingrediente: Mapped["Item"]   = relationship()


# ============================================================
# TABLA: extras  +  extra_platos
# Agregados que se cobran aparte ("extra tocineta"). A diferencia de
# un ingrediente removible, un extra SÍ suma precio y SÍ descuenta stock.
# ============================================================
class Extra(Base):
    __tablename__ = "extras"
    __table_args__ = (
        UniqueConstraint("empresa_id", "nombre", name="uq_extra_empresa_nombre"),
        CheckConstraint("precio >= 0", name="ck_extra_precio_no_negativo"),
        CheckConstraint("cantidad > 0", name="ck_extra_cantidad_positiva"),
    )

    id:             Mapped[int]     = mapped_column(primary_key=True)
    empresa_id:     Mapped[int]     = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    nombre:         Mapped[str]     = mapped_column(String(100))
    precio:         Mapped[Decimal] = mapped_column(DINERO)
    ingrediente_id: Mapped[int]     = mapped_column(ForeignKey("items.id"))    # lo que descuenta al venderse
    cantidad:       Mapped[Decimal] = mapped_column(CANTIDAD)                  # en unidad base del ingrediente
    # True = se ofrece en todos los platos; False = solo en los de `extra_platos`.
    aplica_a_todos: Mapped[bool]    = mapped_column(Boolean, default=True, server_default=true())
    activo:         Mapped[bool]    = mapped_column(Boolean, default=True, server_default=true())

    ingrediente: Mapped["Item"] = relationship()


class ExtraPlato(Base):
    """Une un extra con los platos donde se ofrece (cuando no aplica a todos)."""
    __tablename__ = "extra_platos"

    extra_id: Mapped[int] = mapped_column(ForeignKey("extras.id", ondelete="CASCADE"), primary_key=True)
    item_id:  Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)


# ============================================================
# TABLA: stock_sucursal
# Cuánto hay de cada ítem en cada local.
#
#   cantidad_fisica    = lo que realmente está en bodega/cocina.
#   cantidad_reservada = lo comprometido por pedidos YA ENVIADOS a cocina
#                        que todavía no se marcan "listo".
#   disponible         = fisica - reservada.
#
# Flujo: enviar pedido → sube `reservada`. Cocina marca "listo" →
# bajan `fisica` y `reservada`. Se cancela antes de cocinar → baja
# solo `reservada` (el insumo "vuelve" a estar disponible).
#
# Para ver el total consolidado de la empresa basta sumar las sucursales.
# ============================================================
class StockSucursal(Base):
    __tablename__ = "stock_sucursal"
    __table_args__ = (UniqueConstraint("item_id", "sucursal_id", name="uq_stock_item_sucursal"),)

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    item_id:     Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)

    # Pueden quedar negativas a propósito: faltar un ingrediente solo alerta.
    cantidad_fisica:    Mapped[Decimal] = mapped_column(CANTIDAD, default=Decimal("0"), server_default="0")
    cantidad_reservada: Mapped[Decimal] = mapped_column(CANTIDAD, default=Decimal("0"), server_default="0")
    actualizado_en:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    item: Mapped["Item"] = relationship()

    @property
    def disponible(self) -> Decimal:
        """Lo que realmente se puede ofrecer ahora: físico menos lo ya reservado."""
        return (self.cantidad_fisica or Decimal("0")) - (self.cantidad_reservada or Decimal("0"))


# ============================================================
# TABLA: movimientos_stock
# El LIBRO CONTABLE del inventario: cada vez que el stock físico
# cambia, se agrega una fila. Nunca se edita ni se borra.
# Las mermas son movimientos con tipo "merma" y un motivo.
# ============================================================
class MovimientoStock(Base):
    __tablename__ = "movimientos_stock"
    __table_args__ = (
        Index("ix_movstock_empresa_item_fecha", "empresa_id", "item_id", "creado_en"),
        Index("ix_movstock_referencia", "referencia_tipo", "referencia_id"),
    )

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    item_id:     Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))

    tipo:        Mapped[TipoMovimientoStock] = mapped_column(columna_enum(TipoMovimientoStock))
    # Con signo y en unidad base: entrada positiva, salida negativa.
    cantidad:       Mapped[Decimal] = mapped_column(CANTIDAD)
    stock_anterior: Mapped[Decimal] = mapped_column(CANTIDAD)
    stock_nuevo:    Mapped[Decimal] = mapped_column(CANTIDAD)
    # Costo por unidad base al momento del movimiento (para valorizar mermas y consumos).
    costo_unitario: Mapped[Optional[Decimal]] = mapped_column(COSTO_UNITARIO)

    motivo_merma:   Mapped[Optional[MotivoMerma]] = mapped_column(columna_enum(MotivoMerma))
    usuario_id:     Mapped[Optional[int]]         = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))

    # Qué originó el movimiento: ("compra", id), ("lote_produccion", id),
    # ("orden", uuid), ("inventario_fisico", id)... Es texto para admitir
    # tanto ids numéricos como los UUID que generarán las tablets sin conexión.
    referencia_tipo: Mapped[Optional[str]] = mapped_column(String(30))
    referencia_id:   Mapped[Optional[str]] = mapped_column(String(64))
    nota:            Mapped[Optional[str]] = mapped_column(String(255))
    creado_en:       Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped["Item"] = relationship()


# ============================================================
# TABLA: lotes_produccion
# Cuando el cocinero produce un componente en lote ("hice 1 kg de
# salsa de ajo"): se descuentan los insumos y entra el componente.
# Esta fila es la cabecera; el detalle de lo consumido y lo que
# entró queda en `movimientos_stock` con referencia a este lote.
# ============================================================
class LoteProduccion(Base):
    __tablename__ = "lotes_produccion"
    __table_args__ = (CheckConstraint("cantidad_producida > 0", name="ck_lote_cantidad_positiva"),)

    id:          Mapped[int] = mapped_column(primary_key=True)
    empresa_id:  Mapped[int] = mapped_column(ForeignKey("empresas.id", ondelete="CASCADE"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"), index=True)
    item_id:     Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)       # el componente producido
    receta_id:   Mapped[int] = mapped_column(ForeignKey("recetas.id"))

    # Cuánto se produjo de verdad, en unidad base del componente (puede
    # diferir del rendimiento teórico de la receta).
    cantidad_producida: Mapped[Decimal] = mapped_column(CANTIDAD)
    costo_total:        Mapped[Decimal] = mapped_column(DINERO)            # lo que costaron los insumos
    costo_unitario:     Mapped[Decimal] = mapped_column(COSTO_UNITARIO)    # costo_total / cantidad_producida
    producido_por_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    nota:               Mapped[Optional[str]] = mapped_column(String(255))
    creado_en:          Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    item:   Mapped["Item"]   = relationship()
    receta: Mapped["Receta"] = relationship()
