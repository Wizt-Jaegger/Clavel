# PROGRESS — Clavel

## Completado
- [x] Inspección de los documentos de requisitos y decisiones.
- [x] Estructura inicial FastAPI + SQLite.
- [x] Esquema de clientes, productos, transacciones, líneas, segmentos e historial de ejecución.
- [x] Dataset ficticio inicial (20 clientes, 16 productos, compras con patrones diferenciados).
- [x] API de productos y clientes.
- [x] Registro de compras con control de inventario.
- [x] Pipeline TruncatedSVD + normalización L2 + BIRCH (SVD condicional para muestras pequeñas).
- [x] Recomendaciones por popularidad y filtro de stock/productos ya comprados.
- [x] Validación inicial de compatibilidad por socket y memoria.
- [x] Dashboard y reset de demo.
- [x] Pruebas iniciales escritas.
- [x] README y HANDOFF.

## Estado actual
Pruebas ejecutadas: `python -m pytest -q` → **4 passed**. No se pudo validar `pip install` dentro de este entorno porque no hay conexión de red; el entorno global sí tenía las dependencias necesarias.

## Próxima tarea
Crear formularios web para alta de clientes, alta/edición de productos y registro de compras. Ver `HANDOFF.md` para el plan completo y prompt de continuación.
