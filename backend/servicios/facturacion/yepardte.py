# ============================================================
# YEPAR RESTAURANT — backend/servicios/facturacion/yepardte.py
# Conector con YeparDTE (Chile · SII). Mismo contrato que usa YeparStock:
#   POST /api/v1/emitir   (X-Api-Key)  →  {"documento": {folio, neto, iva, total, pdf_url, ...}, "track_id"}
#   GET  /api/v1/ping
# ============================================================

import os

from servicios.facturacion.base import (ConectorHttp, ResultadoEmision, SolicitudEmision, decimal_o_none)

URL_POR_DEFECTO = "https://api.yepardte.cl"


class ConectorYeparDTE(ConectorHttp):
    nombre = "YeparDTE"

    def __init__(self, api_key: str, base_url: str = None):
        super().__init__(base_url or os.environ.get("YEPARDTE_API_URL", URL_POR_DEFECTO), api_key)

    def emitir(self, s: SolicitudEmision) -> ResultadoEmision:
        cuerpo = {
            "tipo": s.tipo,                     # "boleta" (39) | "factura" (33)
            "receptor": s.receptor,
            "items": [{"nombre": i["nombre"], "precio": str(i["precio_unitario"]), "qty": i["cantidad"],
                       "descuento": str(i.get("descuento", 0))} for i in s.items],
            "iva_incluido": s.iva_incluido,
            "condicion_pago": "Contado",
            "referencia_externa": s.referencia_externa,
            "idempotency_key": s.idempotency_key,
        }
        datos = self._llamar("POST", self.ruta_emitir, cuerpo)
        doc = datos.get("documento") or {}
        if not doc.get("folio"):
            from servicios.facturacion.base import ErrorFacturador
            raise ErrorFacturador("YeparDTE no devolvió el folio.", reintentable=True)
        return ResultadoEmision(folio=str(doc["folio"]), neto=decimal_o_none(doc.get("neto")),
                                iva=decimal_o_none(doc.get("iva")), total=decimal_o_none(doc.get("total")),
                                pdf_url=doc.get("pdf_url"), track_id=datos.get("track_id"))
