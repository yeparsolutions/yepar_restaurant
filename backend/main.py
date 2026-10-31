# ============================================================
# YEPAR RESTAURANT — backend/main.py
# Punto de entrada de la API.
#
# Arrancar en desarrollo (desde la carpeta backend):
#     uvicorn main:app --reload
#
# Analogía: es la puerta principal del edificio. Aquí se reciben las
# peticiones, se traducen los errores del negocio a respuestas HTTP
# claras y se reparte cada pedido al área que corresponde.
# ============================================================

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

import models  # noqa: F401  (registra todos los modelos)
from database import Base, SessionLocal, engine
from errores import ErrorNegocio, ErrorNoEncontrado
from routers import auth, caja, catalogo, cocina, conteo, facturacion, inventario, recepcion, salon
from semilla import sembrar_unidades


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """
    Al arrancar: con SQLite (desarrollo) crea las tablas y siembra las unidades solas.
    Con PostgreSQL NO toca el esquema: ahí el esquema se maneja con migraciones.
    """
    if str(engine.url).startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            sembrar_unidades(db)
            db.commit()
    yield


app = FastAPI(title="Yepar Restaurant API", version="0.1.0", lifespan=ciclo_de_vida)

_origenes = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origenes, allow_methods=["*"], allow_headers=["*"],
                   allow_credentials=True)


# ── Errores de negocio → respuestas HTTP legibles ─────────────
@app.exception_handler(ErrorNoEncontrado)
async def _no_encontrado(_: Request, error: ErrorNoEncontrado):
    return JSONResponse(status_code=404, content={"detalle": str(error)})


@app.exception_handler(ErrorNegocio)
async def _regla_de_negocio(_: Request, error: ErrorNegocio):
    return JSONResponse(status_code=422, content={"detalle": str(error)})


@app.exception_handler(IntegrityError)
async def _conflicto(_: Request, error: IntegrityError):
    # Típico: dos tablets abriendo la misma mesa a la vez (la base lo impide con un índice único).
    return JSONResponse(status_code=409, content={"detalle": "Conflicto: otra persona acaba de modificar lo mismo."})


app.include_router(auth.router)
app.include_router(salon.router)
app.include_router(cocina.router)
app.include_router(catalogo.router)
app.include_router(inventario.router)
app.include_router(caja.router)
app.include_router(facturacion.router)
app.include_router(recepcion.router)
app.include_router(conteo.router)


@app.get("/salud", tags=["sistema"])
def salud():
    """Para que Railway (o quien monitoree) sepa que la API está viva."""
    return {"estado": "ok"}
