# ============================================================
# YEPAR RESTAURANT — backend/servicios/facturacion/yepardte.py
# Conector con YeparDTE (Chile · SII). Contrato REAL de YeparDTE (verificado en su código):
#   POST /api/v1/emitir   (X-Api-Key)
#        {tipo, receptor{nombre,rut,email,direccion,giro}, items[{nombre, precio:int, qty:int,
#         descuento:int (PORCENTAJE 0-100)}], iva_incluido, condicion_pago, referencia_externa,
#         idempotency_key}
#     →  {"ok", "documento": {id, folio, numero, neto, iva, total, pdf_url, ...}}
#   GET  /api/v1/ping
# Ojo: YeparDTE devuelve SIEMPRE 400 ante cualquier error (nunca 5xx, por Cloudflare); un fallo
# interno viene como {"error_real", "http_original": 5xx}: eso es transitorio y se reintenta.
# ============================================================

import os
from decimal import ROUND_HALF_UP, Decimal

from servicios.facturacion.base import (ConectorHttp, ErrorFacturador, ResultadoEmision, SolicitudEmision,
                                        decimal_o_none)

URL_POR_DEFECTO = "https://api.yepardte.cl"


def _entero(valor: Decimal) -> int:
    return int(valor.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def items_yepardte(items: list) -> list:
    """
    Traduce las líneas de la cuenta al formato de YeparDTE (pesos enteros, descuento en %).
    - Sin descuento y precio entero: tal cual.
    - Con descuento que equivale a un % entero (el que da el cajero): se manda como % por línea.
    - Si no calza exacto: la línea va como UN renglón ("Plato x2") por su monto final, para que
      el total del documento sea el cobrado al peso.
    """
    salida = []
    for i in items:
        cantidad, precio, desc = int(i["cantidad"]), Decimal(i["precio_unitario"]), Decimal(i.get("descuento", 0))
        bruto = precio * cantidad
        item = None
        if precio == precio.to_integral_value():
            if desc == 0:
                item = {"nombre": i["nombre"], "precio": int(precio), "qty": cantidad}
            elif bruto > 0:
                pct = _entero(desc / bruto * 100)
                if 0 < pct < 100 and abs(_entero(bruto * (100 - pct) / 100) - _entero(bruto - desc)) <= 1:
                    item = {"nombre": i["nombre"], "precio": int(precio), "qty": cantidad, "descuento": pct}
        if item is None:
            nombre = i["nombre"] if cantidad == 1 else f"{i['nombre']} x{cantidad}"
            item = {"nombre": nombre, "precio": _entero(bruto - desc), "qty": 1}
        salida.append(item)
    return salida


class ConectorYeparDTE(ConectorHttp):
    nombre = "YeparDTE"

    def __init__(self, api_key: str, base_url: str = None):
        super().__init__(base_url or os.environ.get("YEPARDTE_API_URL", URL_POR_DEFECTO), api_key)

    def _es_transitorio(self, status, r) -> bool:
        datos = self._json(r)
        detalle = datos.get("detail") if isinstance(datos, dict) else None
        return isinstance(detalle, dict) and (
            (detalle.get("http_original") or 0) >= 500 or detalle.get("tipo") == "excepcion_no_controlada")

    def emitir(self, s: SolicitudEmision) -> ResultadoEmision:
        receptor = {k: v for k, v in s.receptor.items() if k in ("nombre", "rut", "email", "direccion", "giro") and v}
        cuerpo = {
            "tipo": s.tipo,                     # "boleta" (39) | "factura" (33)
            "receptor": receptor,
            "items": items_yepardte(s.items),
            "iva_incluido": s.iva_incluido,
            "condicion_pago": "Contado",
            "referencia_externa": s.referencia_externa,
            "idempotency_key": s.idempotency_key,
        }
        if s.referencia:        # nota de crédito: "anula documento" (cod_ref 1) apuntando al original (39 boleta, 33 factura)
            cuerpo["referencia"] = {"tipo_doc_ref": "39" if s.referencia["tipo"] == "boleta" else "33",
                                    "folio_ref": s.referencia["folio"], "fecha_ref": s.referencia["fecha"],
                                    "razon": s.referencia["motivo"], "cod_ref": 1}
        datos = self._llamar("POST", self.ruta_emitir, cuerpo)
        doc = datos.get("documento") or {}
        if not doc.get("folio"):
            raise ErrorFacturador("YeparDTE no devolvió el folio.", reintentable=True)
        return ResultadoEmision(folio=str(doc["folio"]), neto=decimal_o_none(doc.get("neto")),
                                iva=decimal_o_none(doc.get("iva")), total=decimal_o_none(doc.get("total")),
                                pdf_url=doc.get("pdf_url"), moneda_montos="CLP")
