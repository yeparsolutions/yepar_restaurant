# ============================================================
# YEPAR RESTAURANT — backend/models/enums.py
# Listas cerradas de valores que usa el modelo de datos.
#
# LECCIÓN APRENDIDA DE CARORA (YeparStock): allá los Enum se
# guardaban como tipos nativos de PostgreSQL, y agregar un valor
# nuevo obligaba a escribir scripts de migración (fix_enum.py,
# fix_enum2.py...). Acá los guardamos como TEXTO simple: agregar
# un valor nuevo es solo agregar una línea en la clase Python.
#
# Analogía: en vez de grabar los nombres de las salas en el
# cemento del edificio, los dejamos en un letrero que se cambia
# cuando haga falta.
# ============================================================

import enum

from sqlalchemy import Enum


def columna_enum(clase):
    """
    Devuelve el tipo de columna para guardar un Enum como texto (VARCHAR).
    Guarda el VALOR ("materia_prima"), no el nombre de Python, y rechaza
    textos que no pertenezcan a la lista.
    """
    return Enum(
        clase,
        native_enum=False,          # texto simple, sin tipo nativo de PostgreSQL
        length=30,
        validate_strings=True,      # un texto inválido falla antes de llegar a la base
        values_callable=lambda e: [m.value for m in e],
    )


# ── Unidades de medida ───────────────────────────────────────
class FamiliaUnidad(str, enum.Enum):
    """Solo se puede convertir DENTRO de una misma familia (nunca peso ↔ volumen)."""
    peso    = "peso"       # mg, g, kg
    volumen = "volumen"    # ml, cc, l
    unidad  = "unidad"     # und


# ── Ítems del inventario ─────────────────────────────────────
class TipoItem(str, enum.Enum):
    """
    Analogía de la casa:
      materia_prima      = los ladrillos (tomate, harina, licor)
      componente         = paredes prefabricadas (salsa de ajo, masa)
      vendible_preparado = la casa terminada (hamburguesa, trago)
      vendible_reventa   = se compra y se vende tal cual (agua, bebida en lata)
    """
    materia_prima      = "materia_prima"
    componente         = "componente"
    vendible_preparado = "vendible_preparado"
    vendible_reventa   = "vendible_reventa"


# Lo que ve el mesero en la carta.
TIPOS_VENDIBLES = frozenset({TipoItem.vendible_preparado, TipoItem.vendible_reventa})

# Lo que lleva receta (ingredientes + cantidades).
TIPOS_CON_RECETA = frozenset({TipoItem.componente, TipoItem.vendible_preparado})


# ── Stock ────────────────────────────────────────────────────
class TipoMovimientoStock(str, enum.Enum):
    compra             = "compra"              # entra por recepción física de una factura
    produccion_consumo = "produccion_consumo"  # sale: insumo gastado al producir un lote
    produccion_entrada = "produccion_entrada"  # entra: componente recién producido
    consumo_venta      = "consumo_venta"       # sale: lo descontado cuando cocina marca "listo"
    merma              = "merma"               # sale: pérdida (ver MotivoMerma)
    ajuste_inventario  = "ajuste_inventario"   # +/-: resultado aprobado de un conteo físico


class MotivoMerma(str, enum.Enum):
    vencido                     = "vencido"
    danado                      = "danado"
    error_preparacion           = "error_preparacion"
    sobrante                    = "sobrante"
    derrame                     = "derrame"
    cancelacion_en_preparacion  = "cancelacion_en_preparacion"   # plato cancelado cuando ya se estaba cocinando


# ── Reservas de stock ────────────────────────────────────────
class EstadoReserva(str, enum.Enum):
    activa     = "activa"        # pedido enviado a cocina, aún no listo
    consumida  = "consumida"     # cocina marcó "listo": salió del stock físico
    liberada   = "liberada"      # se canceló antes de empezar a cocinar
    merma      = "merma"         # se canceló ya en preparación: se pierde


# ── Salón: pedidos y platos ──────────────────────────────────
class EstadoPedido(str, enum.Enum):
    abierto        = "abierto"          # la mesa está siendo atendida
    cuenta_pedida  = "cuenta_pedida"    # el cliente pidió la cuenta: ya no se agregan platos
    cerrado        = "cerrado"          # cobrado
    anulado        = "anulado"          # se abrió por error / nadie consumió


class EstadoLinea(str, enum.Enum):
    tomada         = "tomada"           # anotada en la tablet, aún NO enviada (cola del mesero)
    enviada        = "enviada"          # llegó a cocina/barra, estado 'nuevo'
    en_preparacion = "en_preparacion"   # el cocinero la empezó
    lista          = "lista"            # lista para retirar: la mesa se enciende y vibra
    entregada      = "entregada"        # el mesero la llevó a la mesa
    cancelada      = "cancelada"


# ── Caja y cobro ─────────────────────────────────────────────
class MedioPago(str, enum.Enum):
    efectivo      = "efectivo"        # se paga en la caja (el mesero no maneja efectivo)
    tarjeta       = "tarjeta"         # terminal portátil en la mesa; exige terminal y número de operación
    transferencia = "transferencia"   # exige número de operación


class EstadoTurno(str, enum.Enum):
    abierto = "abierto"
    cerrado = "cerrado"


class ModoPropina(str, enum.Enum):
    por_mesa = "por_mesa"             # la propina de cada mesa es de su mesero
    grupal   = "grupal"               # va a un fondo común que se reparte entre el equipo


class EstadoPropina(str, enum.Enum):
    pendiente = "pendiente"           # el restaurante la tiene y aún no se la entrega a nadie
    entregada = "entregada"           # ya se entregó al mesero
    repartida = "repartida"           # (fondo grupal) ya se repartió entre el equipo


# ── Usuarios ─────────────────────────────────────────────────
class RolUsuario(str, enum.Enum):
    administrador = "administrador"
    cajero        = "cajero"
    mesero        = "mesero"
    cocinero      = "cocinero"


class EstacionCocina(str, enum.Enum):
    """El barman es simplemente un cocinero con estación 'barra'."""
    cocina = "cocina"
    barra  = "barra"


# ── Facturación (documentos tributarios) ─────────────────────
class ProveedorFacturacion(str, enum.Enum):
    yepardte     = "yepardte"       # Chile: boleta/factura al SII
    yeparfactura = "yeparfactura"   # Venezuela: factura al SENIAT (vía imprenta digital)


class TipoDocumento(str, enum.Enum):
    boleta  = "boleta"              # consumidor final (Chile)
    factura = "factura"             # con datos del receptor (Chile y Venezuela)
    nota_credito = "nota_credito"   # anula un documento ya emitido (siempre apunta a su original)


class EstadoDocumento(str, enum.Enum):
    pendiente = "pendiente"         # no se pudo confirmar con el facturador (sin red, tardó): se reintenta
    emitido   = "emitido"           # el facturador devolvió el folio
    rechazado = "rechazado"         # el facturador lo rechazó (datos inválidos): se corrige y se reintenta
    anulado   = "anulado"           # ya tiene su nota de crédito emitida


# ── Recepción de mercadería e inventario físico ──────────────
class EstadoCompra(str, enum.Enum):
    por_recibir = "por_recibir"   # factura registrada por el admin; la mercadería aún no se cuenta
    recibida    = "recibida"      # el cocinero contó lo que llegó y el stock ya subió
    anulada     = "anulada"       # factura cancelada antes de recibirse


class EstadoInventarioFisico(str, enum.Enum):
    contando    = "contando"      # el cocinero cuenta a ciegas
    en_revision = "en_revision"   # conteo completo; el admin revisa diferencias
    cerrado     = "cerrado"       # diferencias aplicadas al stock
    cancelado   = "cancelado"     # descartado sin tocar el stock


# ── Despacho (delivery con Yepar Go) ─────────────────────────
class EstadoDespacho(str, enum.Enum):
    pendiente = "pendiente"   # Yepar Go no respondió: se reintentará (la orden PUDO crearse)
    creado    = "creado"      # orden creada en Yepar Go (su estado vivo está en `estado_go`)
    rechazado = "rechazado"   # Yepar Go la rechazó (datos inválidos, límite del plan...): hay que corregir
