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
    iva_incluido: bool = True
    moneda: Optional[str] = None
    tasa_cambio: Optional[Decimal] = None       # Venezuela: tasa del día para mostrar ambos montos


@dataclass
class ResultadoEmision:
    folio: str
    neto: Optional[Decimal] = None
    iva: Optional[Decimal] = None
    total: Optional[Decimal] = None
    pdf_url: Optional[str] = None
    track_id: Optional[str] = None


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
        if r.status_code >= 500:
            raise ErrorFacturador(f"{self.nombre} respondió {r.status_code}.", reintentable=True)
        if r.status_code in (401, 403):
            raise ErrorFacturador(f"La API Key de {self.nombre} no es válida o fue revocada.", reintentable=False)
        if r.status_code >= 400:
            try:
                detalle = r.json().get("detail", r.text)
            except Exception:
                detalle = r.text
            raise ErrorFacturador(f"{self.nombre} rechazó la emisión: {detalle}", reintentable=False)
        try:
            return r.json() or {}
        except Exception:
            raise ErrorFacturador(f"{self.nombre} respondió algo que no se entiende.", reintentable=True)

    def ping(self) -> None:
        self._llamar("GET", self.ruta_ping)
