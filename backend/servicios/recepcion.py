# ============================================================
# YEPAR RESTAURANT — backend/servicios/recepcion.py
# Recepción física de mercadería en dos llaves.
#
# Analogía: el administrador deja el "pedido esperado" en un sobre cerrado
# (la factura). El cocinero abre las cajas, cuenta lo que llegó SIN ver el
# sobre, y recién ahí el sistema compara: llegó lo que decía el papel o no.
# El stock sube únicamente con lo contado.
# ============================================================

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import Compra, CompraLinea, EstadoCompra
from servicios.compras import (TIPOS_COMPRABLES, convertir_cantidad, ingresar_compra,
                               resolver_cantidad_y_costo)
from servicios.stock import cargar_item, validar_sucursal


def cargar_compra(db: Session, empresa_id: int, compra_id: int, sucursal_id: Optional[int] = None) -> Compra:
    """Busca una compra de ESTA empresa (y de la sucursal del usuario, si se indica); si no, 404."""
    compra = db.get(Compra, compra_id)
    if compra is None or compra.empresa_id != empresa_id or (sucursal_id is not None and compra.sucursal_id != sucursal_id):
        raise ErrorNoEncontrado(f"La compra {compra_id} no existe.")
    return compra


def registrar_compra(db: Session, *, empresa_id: int, sucursal_id: int, proveedor: str,
                     numero_documento: Optional[str], lineas: list[dict], nota: Optional[str] = None,
                     usuario_id: Optional[int] = None) -> Compra:
    """Primera llave: el admin anota lo que dice la factura. No toca el stock."""
    validar_sucursal(db, empresa_id, sucursal_id)
    if not lineas:
        raise ErrorNegocio("La factura necesita al menos una línea.")
    numero = (numero_documento or "").strip() or None
    if numero:
        repetida = (db.query(Compra).filter_by(empresa_id=empresa_id, proveedor=proveedor,
                                               numero_documento=numero).first())
        if repetida is not None:
            raise ErrorNegocio(f"La factura {numero} de {proveedor} ya está registrada (compra {repetida.id}).")

    compra = Compra(empresa_id=empresa_id, sucursal_id=sucursal_id, proveedor=proveedor,
                    numero_documento=numero, nota=nota, creada_por_id=usuario_id,
                    estado=EstadoCompra.por_recibir)
    vistos: set[int] = set()
    for l in lineas:
        item = cargar_item(db, empresa_id, l["item_id"])
        if item.tipo not in TIPOS_COMPRABLES:
            raise ErrorNegocio(f"'{item.nombre}' es de tipo '{item.tipo.value}': no se compra, se produce.")
        if item.id in vistos:
            raise ErrorNegocio(f"'{item.nombre}' está repetido en la factura: júntalo en una sola línea.")
        vistos.add(item.id)
        cantidad_base, costo = resolver_cantidad_y_costo(
            db, item, cantidad=l["cantidad"], unidad=l.get("unidad"), presentacion_id=l.get("presentacion_id"),
            monto_neto=l.get("monto_neto"), costo_unitario_base=l.get("costo_unitario_base"))
        compra.lineas.append(CompraLinea(item_id=item.id, cantidad_facturada=cantidad_base,
                                         costo_unitario_base=costo))
    db.add(compra)
    db.flush()
    return compra


def recibir_compra(db: Session, *, empresa_id: int, compra: Compra, recibidas: list[dict],
                   usuario_id: Optional[int] = None) -> Compra:
    """
    Segunda llave: el cocinero declara lo que llegó (todas las líneas, 0 permitido).
    Sube el stock con la cantidad CONTADA, al costo que dice la factura.
    """
    if compra.estado != EstadoCompra.por_recibir:
        raise ErrorNegocio(f"La compra está '{compra.estado.value}': solo se recibe una compra por recibir.")
    por_id = {l.id: l for l in compra.lineas}
    contado: dict[int, object] = {}
    for r in recibidas:
        linea = por_id.get(r["linea_id"])
        if linea is None:
            raise ErrorNoEncontrado(f"La línea {r['linea_id']} no pertenece a esta compra.")
        if linea.id in contado:
            raise ErrorNegocio("Una línea viene repetida en la recepción.")
        contado[linea.id] = convertir_cantidad(
            db, linea.item, cantidad=r["cantidad"], unidad=r.get("unidad"),
            presentacion_id=r.get("presentacion_id"), permitir_cero=True)
    faltan = [l.item.nombre for l in compra.lineas if l.id not in contado]
    if faltan:
        raise ErrorNegocio("Falta contar: " + ", ".join(faltan) + ".")

    for linea in compra.lineas:
        linea.cantidad_recibida = contado[linea.id]
        if contado[linea.id] > 0:
            ingresar_compra(db, empresa_id=empresa_id, sucursal_id=compra.sucursal_id, item_id=linea.item_id,
                            cantidad=contado[linea.id], costo_unitario_base=linea.costo_unitario_base,
                            usuario_id=usuario_id, referencia_tipo="compra", referencia_id=compra.id,
                            nota=f"Recepción de {compra.proveedor}"
                                 + (f" #{compra.numero_documento}" if compra.numero_documento else ""))
    compra.estado = EstadoCompra.recibida
    compra.recibida_por_id = usuario_id
    compra.recibida_en = datetime.now(timezone.utc)
    db.flush()
    return compra


def anular_compra(db: Session, compra: Compra) -> Compra:
    if compra.estado != EstadoCompra.por_recibir:
        raise ErrorNegocio("Solo se anula una compra que aún no se recibió.")
    compra.estado = EstadoCompra.anulada
    db.flush()
    return compra
