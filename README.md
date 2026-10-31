# Yepar Restaurant

Gestión integral para tu restaurant: pedidos con tablet, pantallas de cocina y barra, cobro y caja, inventario con recetas y costeo, y facturación electrónica. Producto SaaS para terceros (multi-restaurante), que parte por Chile y se conecta a Venezuela.

Estado: **API del backend completa de punta a punta** (mesa → cocina → cobro → boleta/factura → cierre). Falta el frontend, el modo sin conexión de la tablet y el despliegue. Aún no se despliega en Railway.

## Documento de definición

Las decisiones de producto (roles, flujos, stock, cobro, modo sin conexión) están en el documento de definición de Yepar Restaurant.

## Estructura

```
backend/
  main.py                punto de entrada de la API (FastAPI)
  seguridad.py           contraseñas, tokens de sesión (JWT) y permisos por rol
  esquemas.py            formas de los datos de entrada y salida de la API
  errores.py             errores de negocio (422) y "no existe" (404)
  database.py            conexión y base declarativa de SQLAlchemy
  alembic.ini            configuración de las migraciones
  migraciones/           migraciones de la base de datos (Alembic): esquema inicial + unidades de medida
  models/
    enums.py             listas cerradas (tipos de ítem, roles, estados, medios de pago, documentos...)
    tenant.py            empresas (clientes), sucursales, usuarios y roles
    inventario.py        unidades, ítems, recetas, extras, stock, movimientos, lotes, reservas
    salon.py             mesas, pedidos, platos pedidos, traspasos de mesero
    caja.py              cajas, turnos, terminales, pagos, propinas, configuración de cobro
    facturacion.py       facturador del restaurante (API Key cifrada) y documentos tributarios
  servicios/             reglas de negocio (no confirman: lo hace quien las llama)
    stock, recetas, compras, produccion, reservas, disponibilidad, mermas, items,
    mesas, pedidos, cocina, caja, cobro, propinas, cierre
    facturacion/         conectores YeparDTE (Chile) y YeparFactura (Venezuela) + emisión con reintentos
  routers/               endpoints HTTP: auth, salon, cocina, catalogo, inventario, caja, facturacion
  unidades.py            conversión de unidades y costos por unidad base
  semilla.py             catálogo inicial de unidades de medida (desarrollo)
  tests/                 pruebas de servicios, de la API y de las migraciones
```

## Cómo probar y arrancar

```bash
cd backend
pip install -r requirements.txt
pytest                                  # servicios, API y migraciones (SQLite en memoria)
uvicorn main:app --reload               # API en desarrollo (crea una base SQLite local sola)
```

Documentación interactiva de la API en `http://localhost:8000/docs`.

## Base de datos y migraciones

- **Desarrollo (SQLite):** la app crea las tablas y siembra las unidades de medida sola al arrancar.
- **Producción (PostgreSQL):** la app **no toca el esquema**; se maneja con migraciones. Antes de arrancar una versión nueva:

```bash
cd backend
alembic upgrade head                    # aplica las migraciones pendientes (es seguro repetirlo)
uvicorn main:app --host 0.0.0.0 --port $PORT
```

- **Cambiar un modelo:** después de editarlo, `alembic revision --autogenerate -m "qué cambió"`, **revisar** el archivo generado
  (autogenerate lo escribe mirando SQLite: valores como `server_default` de booleanos o fechas deben quedar portables, por ejemplo
  `sa.true()` y `sa.func.now()`) y subirlo junto con el cambio.
- **Una prueba vigila que modelos y migraciones no se separen** (`tests/test_migraciones.py`): si cambias un modelo y olvidas la migración, falla.
  Además revisa que el SQL para PostgreSQL sea portable. `alembic upgrade head --sql` imprime el SQL sin conectarse.
- Las unidades de medida (g, kg, ml, l, cc, und, mg) las siembra la migración `0002`; sin ellas nada convierte.

## Variables de entorno

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | PostgreSQL en producción (Railway entrega `postgres://`, se corrige solo) |
| `SECRET_KEY` | Firma de sesiones **y** cifrado de las API Key de los facturadores. Obligatoria con una base real. **Si se cambia, hay que volver a conectar el facturador de cada restaurante.** |
| `ACCESS_TOKEN_MINUTES` | Duración de la sesión (por defecto un turno de trabajo, 12 h) |
| `CORS_ORIGINS` | Orígenes permitidos del frontend |
| `YEPARDTE_API_URL` | URL de YeparDTE (por defecto `https://api.yepardte.cl`) |
| `YEPARFACTURA_API_URL` | URL de YeparFactura (por defecto `https://yeparfactura.yeparsolution.com`) |
| `YEPARFACTURA_ALICUOTA` | IVA general de Venezuela que se usa al facturar (por defecto `16`) |

## Cómo habla la API

- **Inicio de sesión:** `POST /auth/login` con código del restaurante, usuario y contraseña; devuelve un token para el encabezado `Authorization: Bearer ...`.
- **Roles:** administrador (todo), cajero, mesero y cocinero (con estación cocina o barra). Cada endpoint exige su rol; el administrador entra siempre.
- **Montos como texto** (`"6500.00"`) para no perder decimales; cantidades de stock con 3 decimales.
- **Errores:** `404` si no existe (también para datos de otro cliente), `422` si una regla de negocio no se cumple, `409` en conflictos de concurrencia, `403` sin permiso, `401` sin sesión.
- **Modo sin conexión:** pedidos, platos y pagos aceptan un UUID generado por la tablet; sincronizar dos veces se rechaza en vez de duplicar.
- **Sucursal:** el personal trabaja en su local; el administrador sin local fijo indica `sucursal_id`.

## Mapa de la API (89 endpoints)

**Sesión** — `POST /auth/login` · `GET /auth/yo`

**Salón (mesero; el cajero ve plano y pedidos; el administrador crea mesas)**
`GET /mesas` · `POST /mesas` · `PATCH /mesas/{id}/posicion` · `GET /mesas/qr/{token}` · `GET /carta` ·
`POST /pedidos` · `GET /pedidos/{id}` · `POST /pedidos/{id}/lineas` · `DELETE /lineas/{id}` · `POST /pedidos/{id}/enviar` ·
`POST /lineas/{id}/cancelar` · `POST /pedidos/{id}/cuenta` · `POST /pedidos/{id}/traspaso` · `POST /pedidos/{id}/anular` ·
`GET /retiros` · `POST /lineas/{id}/entregar`

**Cocina y barra (cocinero)**
`GET /cocina/comandas` · `POST /cocina/lineas/{id}/iniciar` · `POST /cocina/lineas/{id}/lista` ·
`POST|DELETE /cocina/items/{id}/agotado`

**Catálogo (administrador; el cocinero lee recetas sin costos)**
`GET /unidades` · `GET|POST /categorias` · `GET|POST /items` · `GET|PATCH /items/{id}` · `POST /items/{id}/presentaciones` ·
`GET|POST /extras` · `PUT|GET /items/{id}/receta` · `GET /items/{id}/costo`

**Inventario (compras y listas: administrador; producción, mermas, stock y alertas: cocinero o administrador)**
`POST /inventario/compras` · `POST /inventario/produccion` · `POST /inventario/mermas` · `GET /inventario/stock` ·
`GET /inventario/movimientos` · `GET /inventario/alertas` · `GET /inventario/lista-compras`

**Recepción de mercadería a ciegas (el administrador registra y revisa; el cocinero cuenta lo que llega sin ver cantidades ni costos)**
`POST|GET /compras` · `GET /compras/por-recibir` · `GET /compras/{id}/recepcion` · `POST /compras/{id}/recibir` ·
`GET /compras/{id}` · `POST /compras/{id}/anular`

**Inventario físico ciego (el administrador abre, revisa, recuenta y cierra; el cocinero cuenta sin ver el stock del sistema)**
`POST|GET /inventario-fisico` · `GET /inventario-fisico/activo` · `POST /inventario-fisico/{id}/contar` ·
`POST /inventario-fisico/{id}/finalizar-conteo` · `GET /inventario-fisico/{id}/revision` · `POST /inventario-fisico/{id}/recontar` ·
`POST /inventario-fisico/{id}/cerrar` · `POST /inventario-fisico/{id}/cancelar`

**Caja y cobro (cajero; el mesero anota propina y cobra tarjeta o transferencia en sus mesas)**
`POST|GET /cajas` · `POST|GET /terminales` · `POST /turnos` · `GET /turnos/actual` · `GET /turnos/{id}/arqueo` ·
`POST /turnos/{id}/cerrar` · `POST /turnos/{id}/revisar` · `GET|PUT /configuracion/cobro` ·
`POST /pedidos/{id}/propina` · `POST /pedidos/{id}/descuento` · `POST /pedidos/{id}/pagos` ·
`GET /propinas` · `GET /propinas/saldos` · `POST /propinas/entregar` · `POST /propinas/repartir` ·
`GET /cierre/terminal/{id}` · `GET /cierre/resumen`

**Facturación electrónica (el administrador conecta, configura y anula; el cajero emite y consulta)**
`PUT|GET|DELETE /facturacion/conexion` · `PUT /facturacion/configuracion` · `POST|GET /pedidos/{id}/documento` ·
`POST /documentos/{id}/anular` · `GET /documentos` · `POST /documentos/reintentar`

**Sistema** — `GET /salud`

## Facturación electrónica

Cada restaurante conecta **su** facturador con su API Key (se valida al instante y se guarda cifrada):

- **YeparDTE** (Chile · SII): boleta y factura. El descuento por línea se manda como porcentaje; si no cuadra al peso, la línea va como un solo renglón.
- **YeparFactura** (Venezuela · SENIAT): factura. Los precios de la carta se asumen con IVA incluido y se envían sin IVA; la tasa BCV la congela YeparFactura (vía YeparFX).

Reglas comunes:

- La **propina no se factura**; el descuento se reparte entre las líneas.
- **Reintentos seguros:** cada documento lleva una clave de idempotencia estable; si el facturador no respondió queda `pendiente` y `POST /documentos/reintentar` lo reenvía sin duplicar el folio. La venta nunca se bloquea por la facturación.
- **Emisión automática** de la boleta al cerrar la mesa (solo Chile, opcional por restaurante).
- **Anulación** con nota de crédito (solo administrador, con motivo). Es solo el papel tributario: devolver el dinero y corregir la caja es aparte.

## Recepción e inventario a ciegas

- **Dos llaves en la compra:** el administrador registra la factura (`por_recibir`, el stock no se mueve); el cocinero cuenta lo que llegó sin ver lo facturado ni los costos. El stock sube con lo **contado**, al costo de la factura; el administrador ve después facturado vs. recibido.
- **Inventario físico:** se toma una foto del stock al abrir; quien cuenta no la ve. Al cerrar se aplica la **diferencia** (contado − foto) como ajuste, así las ventas hechas durante el conteo no se pisan. El administrador puede pedir recuento de ítems puntuales antes de cerrar. Un solo inventario en curso por sucursal.

## Decisiones de diseño del núcleo

- **Unidad base única.** Todo el stock y las recetas se guardan en gramos, mililitros o unidades. Las compras en kg, litros o cajas se convierten al entrar.
- **Decimales exactos.** Cantidades y costos son `Numeric`, nunca `float`.
- **Cuatro tipos de ítem.** Materia prima, componente, vendible preparado y vendible de reventa. El mesero solo ve los vendibles.
- **Faltar un ingrediente solo alerta.** El stock físico puede quedar negativo a propósito.
- **Stock reservado.** Se reserva al enviar el pedido y se descuenta definitivamente cuando cocina marca "listo".
- **Costo de referencia.** El mayor entre el promedio ponderado y el último precio de compra.
- **Movimientos como libro contable.** Solo se agregan filas; las mermas son movimientos con motivo.
- **Enums como texto.** Agregar un valor nuevo no requiere migración (lección de Carora).

## Pendiente

Frontend de la tablet, modo sin conexión (sincronización), integración con Yepar Go (delivery),
carga masiva por Excel con asistente de arranque, PIN de supervisor para descuentos sobre el tope, y despliegue en Railway.
