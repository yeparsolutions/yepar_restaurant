# Yepar Restaurant

Gestión integral para tu restaurant: pedidos con tablet, pantallas de cocina y barra, cobro y caja, e inventario con recetas y costeo. Producto SaaS para terceros, que parte por Chile.

Estado: **en definición y construcción del núcleo**. Aún no se despliega en Railway.

## Documento de definición

Las decisiones de producto (roles, flujos, stock, cobro, modo sin conexión) están en el documento de definición de Yepar Restaurant.

## Estructura

```
backend/
  database.py            conexión y base declarativa de SQLAlchemy
  models/
    enums.py             listas cerradas (tipos de ítem, roles, motivos de merma...)
    tenant.py            empresas (clientes), sucursales, usuarios y roles
    inventario.py        núcleo: unidades, ítems, recetas, extras, stock, movimientos, lotes
  unidades.py            conversión de unidades y costos por unidad base
  semilla.py             catálogo inicial de unidades de medida
  tests/                 pruebas del núcleo
```

## Cómo probar

```bash
cd backend
pip install -r requirements.txt
pytest                   # 26 pruebas sobre una base SQLite en memoria
python semilla.py        # crea la base local de desarrollo y siembra las unidades
```

## Decisiones de diseño del núcleo

- **Unidad base única.** Todo el stock y las recetas se guardan en gramos, mililitros o unidades. Las compras en kg, litros o cajas se convierten al entrar.
- **Decimales exactos.** Cantidades y costos son `Numeric`, nunca `float`.
- **Cuatro tipos de ítem.** Materia prima, componente, vendible preparado y vendible de reventa. El mesero solo ve los vendibles.
- **Faltar un ingrediente solo alerta.** El stock físico puede quedar negativo a propósito.
- **Stock reservado.** Se reserva al enviar el pedido y se descuenta definitivamente cuando cocina marca "listo".
- **Costo de referencia.** El mayor entre el promedio ponderado y el último precio de compra.
- **Movimientos como libro contable.** Solo se agregan filas; las mermas son movimientos con motivo.
- **Enums como texto.** Agregar un valor nuevo no requiere migración (lección de Carora).
