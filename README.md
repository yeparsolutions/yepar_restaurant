# Yepar Restaurant

Gestión integral para tu restaurant: pedidos con tablet, pantallas de cocina y barra, cobro y caja, e inventario con recetas y costeo. Producto SaaS para terceros, que parte por Chile.

Estado: **en definición y construcción del núcleo**. Aún no se despliega en Railway.

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
  models/
    enums.py             listas cerradas (tipos de ítem, roles, estados, medios de pago...)
    tenant.py            empresas (clientes), sucursales, usuarios y roles
    inventario.py        unidades, ítems, recetas, extras, stock, movimientos, lotes, reservas
    salon.py             mesas, pedidos, platos pedidos, traspasos de mesero
    caja.py              cajas, turnos, terminales, pagos, propinas, configuración de cobro
  servicios/             reglas de negocio (no confirman: lo hace quien las llama)
    stock, recetas, compras, produccion, reservas, disponibilidad,
    mesas, pedidos, cocina, caja, cobro, propinas, cierre
  routers/               endpoints HTTP: auth, salon (mesero), cocina
  unidades.py            conversión de unidades y costos por unidad base
  semilla.py             catálogo inicial de unidades de medida
  tests/                 pruebas de servicios y de la API
```

## Cómo probar y arrancar

```bash
cd backend
pip install -r requirements.txt
pytest                                  # servicios y API sobre una base SQLite en memoria
uvicorn main:app --reload               # API en desarrollo (crea una base SQLite local sola)
```

Documentación interactiva de la API en `http://localhost:8000/docs`.

Variables de entorno: `DATABASE_URL` (PostgreSQL en producción), `SECRET_KEY` (obligatoria con una base real),
`ACCESS_TOKEN_MINUTES`, `CORS_ORIGINS`.

## Cómo habla la API

- **Inicio de sesión:** `POST /auth/login` con código del restaurante, usuario y contraseña; devuelve un token para el encabezado `Authorization: Bearer ...`.
- **Roles:** administrador (todo), cajero, mesero y cocinero (con estación cocina o barra). Cada endpoint exige su rol.
- **Montos como texto** (`"6500.00"`) para no perder decimales; cantidades de stock con 3 decimales.
- **Errores:** `404` si no existe (también para datos de otro cliente), `422` si una regla de negocio no se cumple, `409` en conflictos de concurrencia, `403` sin permiso, `401` sin sesión.
- **Modo sin conexión:** pedidos, platos y pagos aceptan un UUID generado por la tablet; sincronizar dos veces se rechaza en vez de duplicar.

## Decisiones de diseño del núcleo

- **Unidad base única.** Todo el stock y las recetas se guardan en gramos, mililitros o unidades. Las compras en kg, litros o cajas se convierten al entrar.
- **Decimales exactos.** Cantidades y costos son `Numeric`, nunca `float`.
- **Cuatro tipos de ítem.** Materia prima, componente, vendible preparado y vendible de reventa. El mesero solo ve los vendibles.
- **Faltar un ingrediente solo alerta.** El stock físico puede quedar negativo a propósito.
- **Stock reservado.** Se reserva al enviar el pedido y se descuenta definitivamente cuando cocina marca "listo".
- **Costo de referencia.** El mayor entre el promedio ponderado y el último precio de compra.
- **Movimientos como libro contable.** Solo se agregan filas; las mermas son movimientos con motivo.
- **Enums como texto.** Agregar un valor nuevo no requiere migración (lección de Carora).
