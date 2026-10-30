# ============================================================
# YEPAR RESTAURANT — backend/servicios/facturacion/base.py
# El "enchufe" común de todos los facturadores.
#
# Analogía: Yepar Restaurant habla con el notario a través de una
# ventanilla estándar (esta interfaz). Detrás puede haber un notario
# chileno (YeparDTE) o uno venezolano (YeparFactura): el restaurante
# no necesita saber cuál. Agregar un tercero = agregar un conector.
# ============================================================

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Protocol

import httpx


def transporte_http() -> Optional[httpx.BaseTransport]:
    """Las pruebas lo reemplazan por un transporte simulado; en producción es None (red real)."""
    return None


class ErrorFacturador(Exception):
    """
    El facturador no emitió el documento.
      - reintentable=True : no se pudo confirmar (sin red, tardó, 5xx). El documento PUDO emitirse:
                            se reintenta con la misma clave de idempotencia y no se duplica.
      - reintentable=False: el facturador lo rechazó (datos inválidos, API Key mala): hay que corregir.
    """
    def __init__(self, detalle: str, *, reintentable: bool):
        super().__init__(detalle)
        self.detalle = detalle
        self.reintentable = reintentable


@dataclass
class SolicitudEmision:
    tipo: str                                   # "boleta" | "factura"
    receptor: dict                              # {"nombre", "rut", "giro", "direccion", "email"}
    items: list                                 # [{"nombre", "cantidad", "precio_unitario", "descuento"}]
    idempotency_key: str
    referencia_externa: str                     # id del pedido en Yepar Restaurant
    iva_incluido: bool = True                   # los precios de la carta ya incluyen IVA
    moneda: Optional[str] = None                # moneda en que vende el restaurante (VES, USD, EUR, CLP...)
    forma_pago: Optional[str] = None            # "efectivo" | "transferencia"... solo si es un único medio


@dataclass
class ResultadoEmision:
    folio: str
    neto: Optional[Decimal] = None
    iva: Optional[Decimal] = None
    total: Optional[Decimal] = None
    pdf_url: Optional[str] = None
    track_id: Optional[str] = None
    moneda_montos: Optional[str] = None         # moneda de neto/iva/total (Venezuela: VES aunque se venda en USD)
    tasa_cambio: Optional[Decimal] = None       # Venezuela: la congela YeparFactura con la tasa BCV de YeparFX
    total_divisa: Optional[Decimal] = None      # Venezuela: total en la moneda original de la venta


class Facturador(Protocol):
    def ping(self) -> None:
        """Valida la API Key. Lanza ErrorFacturador si no sirve."""

    def emitir(self, solicitud: SolicitudEmision) -> ResultadoEmision:
        """Emite el documento. Lanza ErrorFacturador."""


def decimal_o_none(valor) -> Optional[Decimal]:
    return None if valor is None else Decimal(str(valor))


class ConectorHttp:
    """
    Base de los conectores HTTP (X-Api-Key, JSON). Traduce los fallos de red y las
    respuestas del facturador a ErrorFacturador con el criterio de reintento correcto.
    """
    nombre = "facturador"
    ruta_ping = "/api/v1/ping"
    ruta_emitir = "/api/v1/emitir"

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._cliente = httpx.Client(
            base_url=self.base_url, transport=transporte_http(),
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            # Emitir firma el documento y lo manda a la autoridad tributaria: la lectura tarda mucho más
            # que la conexión (mismo criterio que Carora: 10 s para conectar, hasta 120 s para leer).
            timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10))

    def _llamar(self, metodo: str, ruta: str, json=None) -> dict:
        try:
            r = self._cliente.request(metodo, ruta, json=json)
        except httpx.ReadTimeout:
            raise ErrorFacturador(
                f"{self.nombre} tardó más de lo esperado: el documento PUDO emitirse. Se reintentará sin duplicar.",
                reintentable=True)
        except httpx.HTTPError as e:
            raise ErrorFacturador(f"No se pudo conectar con {self.nombre}: {e}", reintentable=True)
        detalle = self._detalle(r)
        if r.status_code >= 500:
            raise ErrorFacturador(f"{self.nombre} respondió {r.status_code}.", reintentable=True)
        if r.status_code == 401:
            raise ErrorFacturador(f"La API Key de {self.nombre} no es válida o fue revocada.", reintentable=False)
        if r.status_code >= 400:
            raise ErrorFacturador(f"{self.nombre} rechazó la emisión ({r.status_code}): {detalle}",
                                  reintentable=self._es_transitorio(r.status_code, r))
        try:
            return r.json() or {}
        except Exception:
            raise ErrorFacturador(f"{self.nombre} respondió algo que no se entiende.", reintentable=True)

    @staticmethod
    def _json(r: httpx.Response):
        try:
            return r.json()
        except Exception:
            return None

    def _detalle(self, r: httpx.Response) -> str:
        """El mensaje legible del facturador, venga como texto, lista o diccionario."""
        datos = self._json(r)
        detalle = datos.get("detail", datos) if isinstance(datos, dict) else (datos or r.text)
        if isinstance(detalle, dict):
            detalle = detalle.get("error_real") or detalle
        return str(detalle)[:400]

    def _es_transitorio(self, status: int, r: httpx.Response) -> bool:
        """¿Este 4xx es en realidad un fallo pasajero del facturador? Cada conector lo afina."""
        return False

    def ping(self) -> None:
        self._llamar("GET", self.ruta_ping)
