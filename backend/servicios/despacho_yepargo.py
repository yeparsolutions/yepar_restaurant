# ============================================================
# YEPAR RESTAURANT — backend/servicios/despacho_yepargo.py
# Conector HTTP con la API de integración de Yepar Go (delivery).
#
# Contrato real (leído del código de YeparGo, módulo `integration`):
#   POST /api/v1/integration/orders        crea la orden → {id, orderNumber, status, trackingToken, trackingUrl...}
#   GET  /api/v1/integration/orders/{id}   estado vivo de la orden
#   GET  /api/v1/integration/pickup-centers  centros de retiro (sirve también para validar la API Key)
# Autenticación: cabecera X-API-Key. Los errores de validación llegan como 400 {message: [...]}.
# ============================================================

import os

import httpx

from servicios.facturacion import base            # reutiliza el hook transporte_http (las pruebas lo simulan)

URL_POR_DEFECTO = "https://yepargo-production.up.railway.app"   # la que usa Yepar Go hoy; cámbiala con YEPARGO_API_URL
PREFIJO = "/api/v1/integration"


class ErrorDespacho(Exception):
    """
    Yepar Go no creó/consultó la orden.
      - reintentable=True : no se pudo confirmar (sin red, tardó, 5xx, 429). La orden PUDO crearse.
      - reintentable=False: la rechazó (datos inválidos, API Key mala, límite del plan): hay que corregir.
    """
    def __init__(self, detalle: str, *, reintentable: bool):
        super().__init__(detalle)
        self.detalle = detalle
        self.reintentable = reintentable


class ConectorYeparGo:
    def __init__(self, api_key: str, base_url: str | None = None):
        self.base_url = (base_url or os.environ.get("YEPARGO_API_URL", URL_POR_DEFECTO)).rstrip("/")
        self._cliente = httpx.Client(
            base_url=self.base_url, transport=base.transporte_http(),
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            timeout=httpx.Timeout(connect=10, read=60, write=30, pool=10))

    @staticmethod
    def _detalle(r: httpx.Response) -> str:
        try:
            datos = r.json()
        except Exception:
            return r.text[:300]
        mensaje = datos.get("message", datos) if isinstance(datos, dict) else datos
        if isinstance(mensaje, list):                      # class-validator entrega una lista de mensajes
            mensaje = "; ".join(map(str, mensaje))
        return str(mensaje)[:400]

    def _llamar(self, metodo: str, ruta: str, json=None):
        try:
            r = self._cliente.request(metodo, PREFIJO + ruta, json=json)
        except httpx.ReadTimeout:
            raise ErrorDespacho("Yepar Go tardó más de lo esperado: la orden PUDO crearse. Se reintentará.",
                                reintentable=True)
        except httpx.HTTPError as e:
            raise ErrorDespacho(f"No se pudo conectar con Yepar Go: {e}", reintentable=True)
        if r.status_code >= 500 or r.status_code == 429:
            raise ErrorDespacho(f"Yepar Go respondió {r.status_code}.", reintentable=True)
        if r.status_code == 401:
            raise ErrorDespacho("La API Key de Yepar Go no es válida o fue revocada.", reintentable=False)
        if r.status_code >= 400:
            raise ErrorDespacho(f"Yepar Go rechazó la solicitud ({r.status_code}): {self._detalle(r)}",
                                reintentable=False)
        try:
            return r.json()
        except Exception:
            raise ErrorDespacho("Yepar Go respondió algo que no se entiende.", reintentable=True)

    def centros_de_retiro(self) -> list[dict]:
        datos = self._llamar("GET", "/pickup-centers")
        return datos if isinstance(datos, list) else []

    def ping(self) -> None:
        self.centros_de_retiro()

    def crear_orden(self, payload: dict) -> dict:
        return self._llamar("POST", "/orders", json=payload)

    def obtener_orden(self, orden_id: str) -> dict:
        return self._llamar("GET", f"/orders/{orden_id}")
