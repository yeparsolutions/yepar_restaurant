# Despliegue en Railway

Guía para poner el backend en línea. Tiempo estimado: 20 minutos. Nada de esto toca tu cuenta hasta que tú lo hagas.

**Analogía:** Railway es el local que arriendas. Tú llevas el negocio (el código), Railway pone el edificio (servidor) y la bodega (PostgreSQL). Las *migraciones* son el plano de la bodega: se aplican solas cada vez que el servicio arranca.

## Antes de empezar

- El código está en `main` del repositorio `yeparsolutions/yepar_restaurant`.
- Tienes cuenta en Railway con el repositorio conectado.
- Ten a mano el dominio de la web/tablet (para `CORS_ORIGINS`). Si aún no existe, déjala con el valor de ejemplo y corrígela cuando lo tengas: la API funciona igual, solo el navegador no podrá llamarla desde otro dominio.

## Pasos

1. **Crea el proyecto** en Railway → *New Project* → *Empty Project*.
2. **Agrega PostgreSQL:** *+ New* → *Database* → *Add PostgreSQL*.
3. **Agrega el servicio de la API:** *+ New* → *GitHub Repo* → `yepar_restaurant`.
4. En el servicio → *Settings* → **Root Directory** = `backend`. (Ahí están `railway.json`, `requirements.txt` y `alembic.ini`.)
5. En el servicio → *Variables* (usa `.env.example` como lista):
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (referencia a la base del paso 2).
   - `SECRET_KEY` = una clave larga y aleatoria. Genérala con `python -c "import secrets; print(secrets.token_urlsafe(64))"`. **Guárdala en tu gestor de contraseñas:** si se pierde o cambia, todos deben iniciar sesión de nuevo y se deben reconectar los facturadores.
   - `CORS_ORIGINS` = el dominio de tu web/tablet (`https://...`).
6. **Despliega.** Al arrancar, el servicio ejecuta `alembic upgrade head` (crea las tablas y las unidades de medida) y levanta la API. Railway espera que `/salud` responda antes de dar el despliegue por bueno.
7. *Settings* → *Networking* → **Generate Domain**. Abre `https://TU-DOMINIO/salud`: debe responder `{"estado": "ok"}`. La documentación interactiva queda en `/docs`.

## Crear el primer restaurante

La base nace vacía: hay que dar de alta al primer cliente con su administrador. Desde tu computador, en la carpeta `backend`:

```bash
# 1. En Railway → Postgres → Connect, copia "Public Network" (DATABASE_PUBLIC_URL). Tiene la clave: no la compartas.
export DATABASE_URL="postgresql://...copiado..."
export SECRET_KEY="cualquier-valor"      # solo para que el script arranque; no firma nada aquí
python crear_restaurante.py --nombre "Mi Restaurante" --sucursal "Casa matriz" \
    --admin-nombre "Tu Nombre" --admin-usuario tunombre
# Te pide la contraseña (mínimo 8 caracteres) y muestra el CÓDIGO DE ACCESO de 8 letras.
```

Con ese código, el usuario y la contraseña se inicia sesión (`POST /auth/login`). El equipo usa el **mismo código** con su propio usuario.

## Después del primer ingreso

1. Crear al personal: `POST /personal` (meseros, cocina, caja), y más sucursales con `POST /sucursales`.
2. Cargar insumos, carta y recetas: `GET /carga-masiva/plantilla` → llenar → `POST /carga-masiva/importar`.
3. Seguir `GET /carga-masiva/asistente`: lista lo que falta (mesas, caja, propina, facturador).
4. Definir tu PIN de supervisor: `PUT /supervisor/pin`.
5. Conectar el facturador: `PUT /facturacion/conexion`.

## Cuidados

- **Respaldos:** activa los respaldos de la base en Railway (*Postgres → Backups*) antes de tener clientes reales.
- **Una sola réplica:** las migraciones corren al arrancar; con varias réplicas arrancando a la vez podrían pisarse. El `railway.json` fija `numReplicas: 1`.
- **Cambios de esquema:** cada cambio de modelos trae su migración (`alembic revision --autogenerate`); un test avisa si falta.
- **Primera vez en PostgreSQL:** las pruebas corren sobre SQLite; las migraciones se revisaron generando el SQL de PostgreSQL, pero no se han ejecutado contra un PostgreSQL real. Haz el primer despliegue en un proyecto de prueba y revisa los *Deploy Logs* antes de usar el definitivo.
