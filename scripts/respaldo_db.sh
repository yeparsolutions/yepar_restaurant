#!/usr/bin/env bash
# Respaldo de la base de datos de Yepar Restaurant (PostgreSQL).
#
# Analogía: es sacar una fotocopia del libro de cuentas del restaurante y
# guardarla en otro cajón. Si el libro original se daña, la fotocopia salva el día.
#
# Uso:
#   DATABASE_URL="postgresql://usuario:clave@host:puerto/base" scripts/respaldo_db.sh [carpeta] [dias]
#
#   carpeta  dónde guardar los respaldos (por defecto ./respaldos)
#   dias     cuántos días conservar (por defecto 14); los más viejos se borran
#
# Restaurar en una base VACÍA:
#   gunzip -c respaldos/yepar_AAAAMMDD_HHMMSS.sql.gz | psql "$DATABASE_URL_DESTINO"
set -euo pipefail

# La URL de la base es obligatoria; nunca se escribe en el script.
: "${DATABASE_URL:?Falta DATABASE_URL}"

CARPETA="${1:-./respaldos}"
DIAS="${2:-14}"
SELLO="$(date +%Y%m%d_%H%M%S)"
ARCHIVO="$CARPETA/yepar_${SELLO}.sql.gz"

mkdir -p "$CARPETA"

# Si algo falla, no se deja basura a medias.
trap 'rm -f "$ARCHIVO.tmp"' EXIT

# --no-owner/--no-privileges: el respaldo se puede restaurar con otro usuario.
# Se escribe primero a un archivo temporal para no dejar un respaldo a medias.
pg_dump --no-owner --no-privileges "$DATABASE_URL" | gzip > "$ARCHIVO.tmp"

# Un respaldo vacío es peor que ninguno: se avisa y se descarta.
if [ ! -s "$ARCHIVO.tmp" ] || ! gzip -t "$ARCHIVO.tmp"; then
  rm -f "$ARCHIVO.tmp"
  echo "ERROR: el respaldo salió vacío o dañado" >&2
  exit 1
fi
mv "$ARCHIVO.tmp" "$ARCHIVO"
chmod 600 "$ARCHIVO"   # contiene datos de clientes: solo para ti
echo "Respaldo listo: $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"

# Limpieza de respaldos más viejos que $DIAS días.
find "$CARPETA" -name 'yepar_*.sql.gz' -mtime +"$DIAS" -delete
