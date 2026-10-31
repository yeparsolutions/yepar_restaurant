# ============================================================
# YEPAR RESTAURANT — backend/tests/test_despliegue.py
# Vigila que los archivos de despliegue sigan coherentes con el código.
# ============================================================

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_railway_json_migra_y_arranca_con_chequeo_de_salud():
    cfg = json.loads((RAIZ / "railway.json").read_text())["deploy"]
    assert cfg["startCommand"].startswith("alembic upgrade head && uvicorn main:app")
    assert "$PORT" in cfg["startCommand"] and cfg["healthcheckPath"] == "/salud"
    assert cfg["numReplicas"] == 1             # las migraciones corren al arrancar: una sola réplica


def test_toda_variable_de_entorno_del_codigo_esta_documentada():
    usadas = set()
    for archivo in RAIZ.rglob("*.py"):
        if "tests" in archivo.parts or ".venv" in archivo.parts:
            continue
        usadas |= set(re.findall(r'environ(?:\.get)?[\(\[]\s*"([A-Z][A-Z0-9_]+)"', archivo.read_text()))
    documentadas = (RAIZ / ".env.example").read_text()
    faltan = sorted(v for v in usadas if v not in documentadas)
    assert not faltan, f"Variables sin documentar en .env.example: {faltan}"
    assert {"DATABASE_URL", "SECRET_KEY", "CORS_ORIGINS"} <= set(re.findall(r"^#?\s*([A-Z_]+)=", documentadas, re.M))


def test_requirements_trae_el_driver_de_postgresql_y_alembic():
    texto = (RAIZ / "requirements.txt").read_text()
    for paquete in ("psycopg2-binary", "alembic", "uvicorn", "openpyxl", "python-multipart"):
        assert paquete in texto, paquete
