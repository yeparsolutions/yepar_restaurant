# ============================================================
# YEPAR RESTAURANT — backend/servicios/facturacion/yeparfactura.py
# Conector con YeparFactura (Venezuela · SENIAT, vía imprenta digital YeparID).
#
# CONTRATO PROPUESTO (YeparFactura aún no publica su API; este conector
# espeja el de YeparDTE para que ambos productos hablen igual):
#   POST /api/v1/emitir  (X-Api-Key) →
#        {"documento": {numero_control, numero, neto, iva, total, pdf_url}, "track_id"}
#   GET  /api/v1/ping
# Diferencias con Chile: solo "factura" (no hay boleta), y todo documento
# lleva la moneda y la tasa de cambio del día (la factura muestra ambos montos).
# Cuando la API real exista, solo se ajusta este archivo.
# ============================================================

import os

from servicios.facturacion.base import (ConectorHttp, ErrorFacturador, ResultadoEmision, SolicitudEmision,
                                        decimal_o_none)

URL_POR_DEFECTO = "https://api.yeparfactura.com.ve"


class ConectorYeparFactura(ConectorHttp):
    nombre = "YeparFactura"

    def __init__(self, api_key: str, base_url: str = None):
        super().__init__(base_url or os.environ.get("YEPARFACTURA_API_URL", URL_POR_DEFECTO), api_key)

    def emitir(self, s: SolicitudEmision) -> ResultadoEmision:
        if s.tipo != "factura":
            raise ErrorFacturador("En Venezuela solo se emite factura (no existe boleta).", reintentable=False)
        if not s.moneda or not s.tasa_cambio or s.tasa_cambio <= 0:
            raise ErrorFacturador("La factura venezolana necesita la moneda y la tasa de cambio del día.",
                                  reintentable=False)
        cuerpo = {
            "tipo": "factura",
            "receptor": s.receptor,
            "items": [{"nombre": i["nombre"], "precio": str(i["precio_unitario"]), "cantidad": i["cantidad"],
                       "descuento": str(i.get("descuento", 0))} for i in s.items],
            "iva_incluido": s.iva_incluido,
            "moneda": s.moneda,
            "tasa_cambio": str(s.tasa_cambio),
            "referencia_externa": s.referencia_externa,
            "idempotency_key": s.idempotency_key,
        }
        datos = self._llamar("POST", self.ruta_emitir, cuerpo)
        doc = datos.get("documento") or {}
        folio = doc.get("numero") or doc.get("numero_control")
        if not folio:
            raise ErrorFacturador("YeparFactura no devolvió el número del documento.", reintentable=True)
        return ResultadoEmision(folio=str(folio), neto=decimal_o_none(doc.get("neto")),
                                iva=decimal_o_none(doc.get("iva")), total=decimal_o_none(doc.get("total")),
                                pdf_url=doc.get("pdf_url"), track_id=datos.get("track_id"))
