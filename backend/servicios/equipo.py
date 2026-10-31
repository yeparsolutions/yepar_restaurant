# ============================================================
# YEPAR RESTAURANT — backend/servicios/equipo.py
# Sucursales y personal del restaurante, y el alta de un restaurante nuevo.
#
# Analogía: es la oficina de personal. El administrador contrata (crea la
# cuenta), asigna el puesto (rol) y el local, y puede dar de baja a alguien
# sin borrar su historial. Regla de oro: el restaurante nunca se queda sin
# un administrador activo (se quedaría sin llave de su propia casa).
# ============================================================

import secrets
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from errores import ErrorNegocio, ErrorNoEncontrado
from models import Empresa, EstacionCocina, RolUsuario, Sucursal, Usuario, UsuarioRol
from seguridad import encriptar_password, verificar_password

MIN_PASSWORD = 8
# Sin 0/O/1/I para que el dueño pueda dictar el código por teléfono sin confusiones.
_ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _limpio(texto: Optional[str]) -> str:
    return (texto or "").strip()


def _validar_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ErrorNegocio(f"La contraseña necesita al menos {MIN_PASSWORD} caracteres.")


# ── Sucursales ───────────────────────────────────────────────
def crear_sucursal(db: Session, *, empresa_id: int, nombre: str) -> Sucursal:
    nombre = _limpio(nombre)
    if not nombre:
        raise ErrorNegocio("La sucursal necesita un nombre.")
    if db.query(Sucursal).filter(Sucursal.empresa_id == empresa_id, func.lower(Sucursal.nombre) == nombre.lower()).first():
        raise ErrorNegocio(f"Ya existe una sucursal llamada '{nombre}'.")
    s = Sucursal(empresa_id=empresa_id, nombre=nombre)
    db.add(s)
    db.flush()
    return s


def renombrar_sucursal(db: Session, *, empresa_id: int, sucursal_id: int, nombre: str) -> Sucursal:
    s = db.get(Sucursal, sucursal_id)
    if s is None or s.empresa_id != empresa_id:
        raise ErrorNoEncontrado(f"La sucursal {sucursal_id} no existe.")
    nombre = _limpio(nombre)
    if not nombre:
        raise ErrorNegocio("La sucursal necesita un nombre.")
    otra = db.query(Sucursal).filter(Sucursal.empresa_id == empresa_id, func.lower(Sucursal.nombre) == nombre.lower(),
                                     Sucursal.id != s.id).first()
    if otra:
        raise ErrorNegocio(f"Ya existe una sucursal llamada '{nombre}'.")
    s.nombre = nombre
    db.flush()
    return s


def listar_sucursales(db: Session, empresa_id: int) -> list[Sucursal]:
    return db.query(Sucursal).filter_by(empresa_id=empresa_id).order_by(Sucursal.nombre).all()


# ── Personal ─────────────────────────────────────────────────
def _cargar_persona(db: Session, empresa_id: int, usuario_id: int) -> Usuario:
    u = db.get(Usuario, usuario_id)
    if u is None or u.empresa_id != empresa_id:
        raise ErrorNoEncontrado(f"La persona {usuario_id} no existe.")
    return u


def _validar_puesto(db: Session, empresa_id: int, roles: set, sucursal_id: Optional[int], estacion, pct) -> None:
    """Reglas del puesto: al menos un rol; quien no es administrador trabaja en un local; el cocinero, en una estación."""
    if not roles:
        raise ErrorNegocio("La persona necesita al menos un rol.")
    if sucursal_id is not None:
        s = db.get(Sucursal, sucursal_id)
        if s is None or s.empresa_id != empresa_id:
            raise ErrorNoEncontrado(f"La sucursal {sucursal_id} no existe.")
    elif roles != {RolUsuario.administrador}:
        raise ErrorNegocio("El personal que no es administrador trabaja en una sucursal: indícala.")
    if RolUsuario.cocinero in roles and estacion is None:
        raise ErrorNegocio("El cocinero necesita una estación (cocina o barra).")
    if estacion is not None and RolUsuario.cocinero not in roles:
        raise ErrorNegocio("Solo el cocinero lleva estación.")
    if not (Decimal("0") <= pct <= Decimal("100")):
        raise ErrorNegocio("El tope de descuento debe estar entre 0 y 100%.")


def crear_persona(db: Session, *, empresa_id: int, nombre: str, username: str, password: str, roles: Iterable,
                  sucursal_id: Optional[int] = None, estacion: Optional[str] = None,
                  descuento_max_pct=0) -> Usuario:
    nombre, username = _limpio(nombre), _limpio(username)
    if not nombre or not username:
        raise ErrorNegocio("Indica el nombre y el usuario.")
    _validar_password(password)
    roles = {RolUsuario(r) for r in roles}
    estacion = EstacionCocina(estacion) if estacion else None
    pct = Decimal(str(descuento_max_pct))
    _validar_puesto(db, empresa_id, roles, sucursal_id, estacion, pct)
    if db.query(Usuario).filter(Usuario.empresa_id == empresa_id, func.lower(Usuario.username) == username.lower()).first():
        raise ErrorNegocio(f"El usuario '{username}' ya existe.")
    u = Usuario(empresa_id=empresa_id, nombre=nombre, username=username, password_hash=encriptar_password(password),
                sucursal_id=sucursal_id, estacion=estacion, descuento_max_pct=pct)
    u.roles = [UsuarioRol(rol=r) for r in sorted(roles, key=lambda r: r.value)]
    db.add(u)
    db.flush()
    return u


def _administradores_activos(db: Session, empresa_id: int) -> int:
    return (db.query(func.count(func.distinct(Usuario.id))).join(UsuarioRol, UsuarioRol.usuario_id == Usuario.id)
              .filter(Usuario.empresa_id == empresa_id, Usuario.activo.is_(True),
                      UsuarioRol.rol == RolUsuario.administrador).scalar() or 0)


def actualizar_persona(db: Session, *, empresa_id: int, usuario_id: int, cambios: dict) -> Usuario:
    """`cambios` trae solo lo que se quiere cambiar: nombre, roles, sucursal_id, estacion, descuento_max_pct, activo."""
    u = _cargar_persona(db, empresa_id, usuario_id)
    era_admin_activo = u.activo and any(r.rol == RolUsuario.administrador for r in u.roles)
    roles = {RolUsuario(r) for r in cambios["roles"]} if "roles" in cambios else {r.rol for r in u.roles}
    sucursal_id = cambios["sucursal_id"] if "sucursal_id" in cambios else u.sucursal_id
    estacion = (EstacionCocina(cambios["estacion"]) if cambios["estacion"] else None) if "estacion" in cambios else u.estacion
    if "roles" in cambios and RolUsuario.cocinero not in roles and "estacion" not in cambios:
        estacion = None                      # dejó de ser cocinero: la estación ya no aplica
    pct = Decimal(str(cambios["descuento_max_pct"])) if "descuento_max_pct" in cambios else u.descuento_max_pct
    activo = cambios["activo"] if "activo" in cambios else u.activo
    _validar_puesto(db, empresa_id, roles, sucursal_id, estacion, pct)
    seguira_siendo_admin = activo and RolUsuario.administrador in roles
    if era_admin_activo and not seguira_siendo_admin and _administradores_activos(db, empresa_id) <= 1:
        raise ErrorNegocio("El restaurante no puede quedarse sin un administrador activo.")
    if "nombre" in cambios:
        nombre = _limpio(cambios["nombre"])
        if not nombre:
            raise ErrorNegocio("Indica el nombre.")
        u.nombre = nombre
    if "roles" in cambios:
        # Se quitan y agregan solo las diferencias (reemplazar la lista entera choca con la clave única usuario+rol).
        for fila in [f for f in u.roles if f.rol not in roles]:
            u.roles.remove(fila)
        u.roles.extend(UsuarioRol(rol=r) for r in sorted(roles - {f.rol for f in u.roles}, key=lambda r: r.value))
    u.sucursal_id, u.estacion, u.descuento_max_pct, u.activo = sucursal_id, estacion, pct, activo
    if not any(r == RolUsuario.administrador for r in roles):
        u.pin_hash, u.pin_fallos, u.pin_bloqueado_hasta = None, 0, None     # sin rol admin no hay PIN de supervisor
    db.flush()
    return u


def listar_personal(db: Session, empresa_id: int) -> list[Usuario]:
    return db.query(Usuario).filter_by(empresa_id=empresa_id).order_by(Usuario.nombre).all()


def restablecer_password(db: Session, *, empresa_id: int, usuario_id: int, password: str) -> None:
    """El administrador pone una contraseña nueva a alguien del equipo (olvidó la suya)."""
    _validar_password(password)
    u = _cargar_persona(db, empresa_id, usuario_id)
    u.password_hash = encriptar_password(password)
    db.flush()


def cambiar_password(db: Session, usuario: Usuario, *, actual: str, nueva: str) -> None:
    if not verificar_password(actual, usuario.password_hash):
        raise ErrorNegocio("La contraseña actual no es correcta.")
    _validar_password(nueva)
    if actual == nueva:
        raise ErrorNegocio("La contraseña nueva debe ser distinta de la actual.")
    usuario.password_hash = encriptar_password(nueva)
    db.flush()


# ── Alta de un restaurante nuevo ─────────────────────────────
def _codigo_libre(db: Session) -> str:
    for _ in range(20):
        codigo = "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(8))
        if db.query(Empresa).filter_by(codigo_acceso=codigo).first() is None:
            return codigo
    raise ErrorNegocio("No se pudo generar un código de acceso libre: reintenta.")


def crear_restaurante(db: Session, *, nombre: str, sucursal: str, admin_nombre: str, admin_usuario: str,
                      admin_password: str, pais: str = "CL", moneda: str = "CLP") -> tuple[Empresa, Sucursal, Usuario]:
    """El alta de un cliente nuevo: restaurante + primera sucursal + su administrador. Devuelve los tres."""
    nombre = _limpio(nombre)
    if not nombre:
        raise ErrorNegocio("El restaurante necesita un nombre.")
    empresa = Empresa(nombre=nombre, codigo_acceso=_codigo_libre(db), pais=pais.upper(), moneda=moneda.upper())
    db.add(empresa)
    db.flush()
    suc = crear_sucursal(db, empresa_id=empresa.id, nombre=sucursal)
    admin = crear_persona(db, empresa_id=empresa.id, nombre=admin_nombre, username=admin_usuario,
                          password=admin_password, roles=[RolUsuario.administrador], sucursal_id=suc.id)
    return empresa, suc, admin
