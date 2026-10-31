# ============================================================
# YEPAR RESTAURANT — backend/crear_restaurante.py
# Alta de un restaurante nuevo: crea el restaurante, su primera sucursal y su administrador,
# y muestra el CÓDIGO DE ACCESO con el que el equipo inicia sesión.
#
# Uso (desde la carpeta backend, con DATABASE_URL apuntando a la base real):
#   python crear_restaurante.py --nombre "Hamburguesería Demo" --sucursal "Casa matriz" \
#       --admin-nombre "Alberto" --admin-usuario alberto [--pais CL --moneda CLP]
# La contraseña se pide por teclado (no queda en el historial); o, en un script, en YEPAR_ADMIN_PASSWORD.
#
# Analogía: es el alta del cliente nuevo en la oficina de Yepar. Se hace una vez por restaurante.
# ============================================================

import argparse
import getpass
import os
import sys

from database import SessionLocal
from errores import ErrorNegocio
from semilla import sembrar_unidades
from servicios.equipo import crear_restaurante


def ejecutar(db, args, password: str) -> str:
    """Crea todo y confirma. Devuelve el código de acceso. (Separado de main() para poder probarlo.)"""
    sembrar_unidades(db)                     # sin las unidades (g, kg, ml...) nada funciona
    empresa, sucursal, admin = crear_restaurante(
        db, nombre=args.nombre, sucursal=args.sucursal, admin_nombre=args.admin_nombre,
        admin_usuario=args.admin_usuario, admin_password=password, pais=args.pais, moneda=args.moneda)
    db.commit()
    return empresa.codigo_acceso


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Crea un restaurante nuevo con su sucursal y su administrador.")
    p.add_argument("--nombre", required=True, help="Nombre del restaurante")
    p.add_argument("--sucursal", default="Casa matriz", help="Nombre de la primera sucursal")
    p.add_argument("--admin-nombre", required=True, help="Nombre de la persona administradora")
    p.add_argument("--admin-usuario", required=True, help="Usuario con el que inicia sesión")
    p.add_argument("--pais", default="CL", help="País (2 letras): CL, VE...")
    p.add_argument("--moneda", default="CLP", help="Moneda: CLP, VES, USD...")
    args = p.parse_args(argv)

    password = os.environ.get("YEPAR_ADMIN_PASSWORD") or getpass.getpass("Contraseña del administrador: ")
    with SessionLocal() as db:
        try:
            codigo = ejecutar(db, args, password)
        except ErrorNegocio as e:
            db.rollback()
            print(f"No se pudo crear: {e}", file=sys.stderr)
            return 1
    print(f"Listo. Código de acceso del restaurante: {codigo}")
    print(f"Inicia sesión con código {codigo}, usuario '{args.admin_usuario}' y la contraseña que acabas de definir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
