# ============================================================
# YEPAR RESTAURANT — backend/servicios/limite_login.py
# Freno a los intentos de contraseña (fuerza bruta).
#
# Analogía: el candado de la caja fuerte. Si alguien prueba claves y se equivoca varias veces, la
# caja se bloquea un rato; la persona que sí sabe la clave la abre sin problema, y quien adivina
# tiene que esperar entre rondas.
#
# Tres cuentas de fallos en una ventana de 15 minutos (por defecto):
#   - por (persona, conexión): 5   → quien se equivoca mucho tarda en volver a probar
#   - por conexión (IP):       30  → una tablet o un script que prueba muchas personas distintas
#                                    (el límite es alto porque el wifi de un local comparte IP)
#   - por persona (cualquier IP): 30 → ataque repartido entre muchas conexiones
# Un ingreso correcto borra el contador de esa (persona, conexión).
#
# Vive en la memoria del proceso (el servicio corre con una sola réplica, igual que el registro).
# Si se reinicia, los contadores empiezan de cero.
# ============================================================

import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException

VENTANA_SEGUNDOS = 15 * 60

_reloj = time.monotonic                       # en las pruebas se reemplaza para "avanzar" el tiempo
_fallos: dict[tuple, deque] = defaultdict(deque)


def _tope_persona_conexion() -> int:
    return int(os.environ.get("LOGIN_MAX_FALLOS", "5"))


def _tope_conexion() -> int:
    return int(os.environ.get("LOGIN_MAX_FALLOS_POR_CONEXION", "30"))


def _tope_persona() -> int:
    return int(os.environ.get("LOGIN_MAX_FALLOS_POR_PERSONA", "30"))


def _limpiar(cola: deque, ahora: float) -> None:
    while cola and ahora - cola[0] > VENTANA_SEGUNDOS:
        cola.popleft()


def _llaves(persona: str, conexion: str) -> list[tuple[tuple, int]]:
    return [(("pc", persona, conexion), _tope_persona_conexion()),
            (("c", conexion), _tope_conexion()),
            (("p", persona), _tope_persona())]


def exigir_libre(persona: str, conexion: str) -> None:
    """Antes de mirar la contraseña: si ya hay demasiados fallos, se corta con 429 (y no se prueba nada más)."""
    ahora = _reloj()
    espera = 0.0
    for llave, tope in _llaves(persona, conexion):
        cola = _fallos[llave]
        _limpiar(cola, ahora)
        if len(cola) >= tope:
            # Se libera cuando el fallo más antiguo que cuenta salga de la ventana.
            espera = max(espera, VENTANA_SEGUNDOS - (ahora - cola[len(cola) - tope]))
    if espera > 0:
        minutos = max(1, int(espera // 60) + 1)
        raise HTTPException(status_code=429, headers={"Retry-After": str(int(espera) + 1)},
                            detail=f"Demasiados intentos fallidos. Espera {minutos} minuto{'s' if minutos != 1 else ''} e inténtalo de nuevo.")


def anotar_fallo(persona: str, conexion: str) -> None:
    ahora = _reloj()
    for llave, _tope in _llaves(persona, conexion):
        _fallos[llave].append(ahora)


def anotar_exito(persona: str, conexion: str) -> None:
    _fallos.pop(("pc", persona, conexion), None)


def reiniciar() -> None:
    """Para las pruebas: borra todos los contadores."""
    _fallos.clear()
