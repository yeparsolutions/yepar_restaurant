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
4. En el servicio → *Settings* → **Root Directory** = `backend`. (Ahí están `requirements.txt` y `alembic.ini`.)
5. En el mismo servicio → *Settings* → *Deploy* (**este paso es obligatorio**: con la carpeta raíz en `backend`, Railway NO lee solo el `railway.json`; en la prueba real arrancó sin migrar):
   - **Custom Start Command** = `alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Healthcheck Path** = `/salud` (timeout 120 s)
   - *(Alternativa: en *Config-as-code* apunta el archivo a `/backend/railway.json`, que ya trae estos valores.)*
6. En el servicio → *Variables* (usa `.env.example` como lista):
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (referencia a la base del paso 2).
   - `SECRET_KEY` = una clave larga y aleatoria. Genérala con `python -c "import secrets; print(secrets.token_urlsafe(64))"`. **Guárdala en tu gestor de contraseñas:** si se pierde o cambia, todos deben iniciar sesión de nuevo y se deben reconectar los facturadores.
   - `CORS_ORIGINS` = el dominio de tu web/tablet (`https://...`).
7. **Despliega.** Al arrancar, el servicio ejecuta `alembic upgrade head` (crea las tablas y las unidades de medida) y levanta la API. Railway espera que `/salud` responda antes de dar el despliegue por bueno. Si el despliegue sale "SUCCESS" pero los logs no muestran las migraciones, revisa que el paso 5 esté hecho.
8. *Settings* → *Networking* → **Generate Domain**. Abre `https://TU-DOMINIO/salud`: debe responder `{"estado": "ok"}`. La documentación interactiva queda en `/docs`.

## Desplegar la web

La web (`frontend/`) es un segundo servicio en el mismo proyecto de Railway:

1. **New → GitHub Repo** → el mismo repositorio. En Settings → **Root Directory** = `/frontend`.
2. Variables del servicio web: `VITE_API_URL` = la dirección pública de la API (con `https://`, sin `/` al final). Debe estar **antes** del primer despliegue, porque se incorpora al compilar.
3. Settings → Networking → **Generate Domain**.
4. En el servicio **api**, variable `CORS_ORIGINS` = la dirección de la web (con `https://`, sin `/` al final). Sin esto el navegador bloquea las llamadas.
5. Abre la web y pulsa **Crear mi restaurante**: ya no hace falta el script de abajo. Para cerrar el registro público (si solo Yepar da de alta clientes): `REGISTRO_ABIERTO=0` en el servicio api.

## Crear el primer restaurante (alternativa por terminal)

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
- **Primera vez en PostgreSQL:** las pruebas corren sobre SQLite. El despliegue de prueba (proyecto `YeparRestaurant-Test`) levantó la API sobre PostgreSQL real con el comando de arranque del paso 5; confirma las tablas con `railway connect postgres` y `SELECT version_num FROM alembic_version;` (debe dar `0006`). Haz siempre el primer despliegue de un cambio grande en un proyecto de prueba.
