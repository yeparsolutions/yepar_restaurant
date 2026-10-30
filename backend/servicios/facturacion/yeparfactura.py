# ============================================================
# YEPAR RESTAURANT — backend/servicios/facturacion/yeparfactura.py
# Conector con YeparFactura (Venezuela · SENIAT, vía la imprenta digital YeparID).
# Contrato REAL de YeparFactura (verificado en su código):
#   POST /v1/documentos   (X-API-Key)
#        {request_id, tipo:"factura", moneda:"VES|USD|EUR", receptor_razon_social, receptor_rif,
#         receptor_cedula_pasaporte, receptor_domicilio, receptor_correo, receptor_telefono,
#         forma_pago, condicion_pago, items[{descripcion, cantidad, precio_unitario NETO,
#         alicuota:"16|8|31|exento", descuento MONTO neto}]}
#     →  {documento_id, estado, numeracion_consecutiva, numero_control, monto_neto, monto_iva,
#         monto_total (en Bs), tasa_cambio, monto_total_divisa, idempotente}
#   GET  /v1/cuentas/verificar
# Claves del diseño de YeparFactura:
#   - La TASA de cambio la toma ella (BCV vía YeparFX) y la congela: acá no se manda.
#   - Los precios van SIN IVA (ella le suma el IVA por alícuota): los precios de la carta se
#     asumen CON IVA incluido y se convierten a neto.
#   - Un reintento con el mismo request_id devuelve el mismo documento (no gasta número de control).
#   - 502 = la imprenta no respondió (transitorio); 422 = rechazo permanente (o sin tasa BCV hoy).
# ============================================================

import os
from decimal import Decimal

from servicios.facturacion.base import (ConectorHttp, ErrorFacturador, ResultadoEmision, SolicitudEmision,
                                        decimal_o_none)

URL_POR_DEFECTO = "https://yeparfactura.yeparsolution.com"
MONEDAS = ("VES", "USD", "EUR")
CAMPOS_RECEPTOR = {"nombre": "receptor_razon_social", "rut": "receptor_rif", "cedula": "receptor_cedula_pasaporte",
                   "direccion": "receptor_domicilio", "email": "receptor_correo", "telefono": "receptor_telefono"}


class ConectorYeparFactura(ConectorHttp):
    nombre = "YeparFactura"
    ruta_ping = "/v1/cuentas/verificar"
    ruta_emitir = "/v1/documentos"

    def __init__(self, api_key: str, base_url: str = None):
        super().__init__(base_url or os.environ.get("YEPARFACTURA_API_URL", URL_POR_DEFECTO), api_key)
        self._cliente.headers.pop("X-Api-Key", None)
        self._cliente.headers["X-API-Key"] = api_key
        # IVA general de Venezuela (16%); configurable por si cambia la alícuota.
        self.alicuota = os.environ.get("YEPARFACTURA_ALICUOTA", "16")

    def _items(self, s: SolicitudEmision) -> list:
        divisor = Decimal(1) + Decimal(self.alicuota) / 100 if s.iva_incluido else Decimal(1)
        return [{
            "descripcion": i["nombre"],
            "cantidad": str(i["cantidad"]),
            "precio_unitario": str((Decimal(i["precio_unitario"]) / divisor).quantize(Decimal("0.000001"))),
            "alicuota": self.alicuota,
            "descuento": str((Decimal(i.get("descuento", 0)) / divisor).quantize(Decimal("0.01"))),
        } for i in s.items]

    def emitir(self, s: SolicitudEmision) -> ResultadoEmision:
        if s.tipo != "factura":
            raise ErrorFacturador("En Venezuela solo se emite factura (no existe boleta).", reintentable=False)
        if s.moneda not in MONEDAS:
            raise ErrorFacturador(f"YeparFactura vende en {', '.join(MONEDAS)}; el restaurante está en '{s.moneda}'.",
                                  reintentable=False)
        cuerpo = {
            "request_id": s.idempotency_key,
            "tipo": "factura",
            "moneda": s.moneda,
            "condicion_pago": "contado",
            "items": self._items(s),
            **{destino: s.receptor[origen] for origen, destino in CAMPOS_RECEPTOR.items() if s.receptor.get(origen)},
        }
        if s.forma_pago:
            cuerpo["forma_pago"] = s.forma_pago
        datos = self._llamar("POST", self.ruta_emitir, cuerpo)
        folio = datos.get("numero_control") or datos.get("numeracion_consecutiva")
        if not folio:
            raise ErrorFacturador("YeparFactura no devolvió el número del documento.", reintentable=True)
        return ResultadoEmision(
            folio=str(folio), neto=decimal_o_none(datos.get("monto_neto")), iva=decimal_o_none(datos.get("monto_iva")),
            total=decimal_o_none(datos.get("monto_total")), moneda_montos="VES",
            tasa_cambio=decimal_o_none(datos.get("tasa_cambio")), total_divisa=decimal_o_none(datos.get("monto_total_divisa")))
