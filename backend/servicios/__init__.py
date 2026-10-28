# ============================================================
# YEPAR RESTAURANT — backend/servicios/__init__.py
# Reglas de negocio del sistema.
#
# Analogía: los modelos son los planos de la bodega; los servicios
# son las personas que trabajan en ella siguiendo el reglamento
# (recibir mercadería, producir un lote, reservar ingredientes).
#
# Convención: un servicio NUNCA hace commit. Valida, modifica y hace
# flush; quien lo llama (la API) decide cuándo confirmar o deshacer
# toda la operación en conjunto.
# ============================================================
