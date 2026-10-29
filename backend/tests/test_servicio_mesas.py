# ============================================================
# YEPAR RESTAURANT — backend/tests/test_servicio_mesas.py
# Pruebas del plano de mesas (servicios/mesas.py).
#
# Ejecutar desde la carpeta backend:   pytest
# ============================================================

import pytest

from errores import ErrorNegocio
from models import Sucursal
from servicios.mesas import (crear_mesa, estado_mesas, mesa_por_qr, posicionar_mesa)


def test_crear_mesa_con_su_lugar_en_el_plano_y_qr_propio(db, local):
    empresa, sucursal = local
    m1 = crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 1", capacidad=4,
                    pos_x=100, pos_y=200, forma="redonda")
    m2 = crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 2")
    assert (m1.pos_x, m1.pos_y, m1.forma) == (100, 200, "redonda")
    assert m1.qr_token and m1.qr_token != m2.qr_token


def test_reglas_al_crear_mesas(db, local, otro_local):
    empresa, sucursal = local
    _, sucursal_ajena = otro_local
    crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 1")
    with pytest.raises(ErrorNegocio, match="Ya existe"):
        crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre=" Mesa 1 ")
    with pytest.raises(ErrorNegocio, match="necesita un nombre"):
        crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="  ")
    with pytest.raises(ErrorNegocio, match="mayor que cero"):
        crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 9", capacidad=0)
    with pytest.raises(ErrorNegocio, match="Forma"):
        crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 9", forma="hexagonal")
    with pytest.raises(ErrorNegocio, match="no existe"):
        crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal_ajena.id, nombre="Mesa 1")


def test_mismo_nombre_en_otro_local_o_cliente_es_valido(db, local, otro_local):
    empresa, sucursal = local
    ajena, sucursal_ajena = otro_local
    segundo = Sucursal(empresa_id=empresa.id, nombre="Segundo local")
    db.add(segundo)
    db.commit()
    crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 1")
    crear_mesa(db, empresa_id=empresa.id, sucursal_id=segundo.id, nombre="Mesa 1")
    crear_mesa(db, empresa_id=ajena.id, sucursal_id=sucursal_ajena.id, nombre="Mesa 1")


def test_mover_mesa_en_el_plano(db, local):
    empresa, sucursal = local
    mesa = crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 1")
    posicionar_mesa(db, empresa_id=empresa.id, mesa_id=mesa.id, pos_x=300, pos_y=450, ancho=120)
    assert (mesa.pos_x, mesa.pos_y, mesa.ancho, mesa.alto) == (300, 450, 120, 80)


def test_escanear_qr_ancla_la_mesa_solo_dentro_del_cliente(db, local, otro_local):
    empresa, sucursal = local
    ajena, _ = otro_local
    mesa = crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 1")
    assert mesa_por_qr(db, empresa_id=empresa.id, qr_token=mesa.qr_token).id == mesa.id
    with pytest.raises(ErrorNegocio, match="no existe"):
        mesa_por_qr(db, empresa_id=ajena.id, qr_token=mesa.qr_token)     # QR de otro cliente
    with pytest.raises(ErrorNegocio, match="no existe"):
        mesa_por_qr(db, empresa_id=empresa.id, qr_token="inventado")


def test_el_plano_de_un_local_no_incluye_mesas_de_otro_ni_inactivas(db, local, otro_local):
    empresa, sucursal = local
    ajena, sucursal_ajena = otro_local
    crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 1")
    inactiva = crear_mesa(db, empresa_id=empresa.id, sucursal_id=sucursal.id, nombre="Mesa 2")
    crear_mesa(db, empresa_id=ajena.id, sucursal_id=sucursal_ajena.id, nombre="Mesa ajena")
    inactiva.activa = False
    db.commit()
    plano = estado_mesas(db, empresa_id=empresa.id, sucursal_id=sucursal.id)
    assert [(m.nombre, m.estado) for m in plano] == [("Mesa 1", "libre")]
