# ============================================================
# YEPAR RESTAURANT — backend/servicios/facturacion/secretos.py
# Cifrado de las API Key de los facturadores en la base de datos.
#
# Analogía: la API Key es la llave del notario; no se deja pegada sobre
# el escritorio (texto plano) sino guardada en una caja fuerte cuya clave
# sale de SECRET_KEY. Quien robe solo la base de datos no puede usarlas.
# ============================================================

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from errores import ErrorNegocio
from seguridad import SECRET_KEY


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("facturacion|" + SECRET_KEY).encode()).digest()))


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode()


def descifrar(cifrado: str) -> str:
    try:
        return _fernet().decrypt(cifrado.encode()).decode()
    except InvalidToken:
        raise ErrorNegocio("No se pudo leer la API Key guardada (cambió la SECRET_KEY): vuelve a conectar el facturador.")
