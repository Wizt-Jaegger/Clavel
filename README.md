# Clavel — MVP de inteligencia comercial para hardware

MVP local para administrar clientes, catálogo y ventas; segmentar clientes con **StandardScaler → TruncatedSVD (cuando aplica) → Normalizer L2 → BIRCH** y recomendar productos por popularidad del segmento o popularidad global.

## Requisitos
- Python 3.10 o superior.
- Linux, macOS o Windows.

## Instalación y ejecución
```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Abre http://127.0.0.1:8000. La base SQLite `clavel.db` se crea automáticamente y se carga con datos ficticios al primer inicio. La documentación interactiva está en http://127.0.0.1:8000/docs.

## Funcionalidades
- Dashboard con métricas, ventas y productos populares.
- API CRUD de productos (`GET/POST /api/products`, `PUT/DELETE /api/products/{id}`).
- Registro y consulta de clientes (`POST/GET /api/customers`).
- Registro de compras (`POST /api/purchases`), validación de stock y descuento automático.
- Segmentación (`POST /api/segments/run`) y asignación visible por cliente.
- Recomendaciones (`GET /api/recommendations/{customer_id}`), excluyendo productos sin stock y ya comprados por el cliente.
- Restauración de datos de demo (`POST /api/demo/reset`) o botón del dashboard.

## Datos y segmentación
El dataset tiene 20 clientes ficticios, 16 productos de hardware y compras simuladas con perfiles de gaming, productividad y periféricos. BIRCH se ejecuta con umbral 0.65 y un número de clusters derivado del tamaño de la muestra. Se requieren al menos 6 clientes y compras registradas. En muestras pequeñas o matrices con pocas dimensiones, SVD se omite cuando no es matemáticamente aplicable.

Las variables de entrada combinan edad, presupuesto, gasto, volumen de compra y cantidades compradas por categoría. Los valores categóricos del catálogo aparecen indirectamente como categorías de compra. La segmentación es exploratoria y no debe interpretarse como una clasificación demográfica validada.

## Compatibilidad
La recomendación descarta conflictos evidentes de socket y tipo de memoria cuando hay especificaciones y compras previas suficientes. No existe un modelo completo de compatibilidad de placas, BIOS, dimensiones, conectores, consumo eléctrico o generación PCIe. El mensaje de compatibilidad es orientativo, no una garantía.

## Pruebas
```bash
pytest -q
```

## Limitaciones conocidas
- Sin autenticación, roles, impuestos, devoluciones ni pagos.
- No hay edición de clientes ni interfaz visual dedicada para altas/edición de productos; esas operaciones están disponibles por API en `/docs`.
- Las recomendaciones son estadísticas, no generadas por un LLM.
- No hay agente autónomo, LangGraph, optimización de prompts, backtesting de margen ni experimentos A/B en esta primera entrega. Son fases posteriores; el evaluador debe usar separación temporal train/validation antes de aceptar cambios de modelo.
- Los datos demo se cargan automáticamente solo cuando el catálogo está vacío. El reset restaura el dataset completo.

## Configurar otra base
Define `CLAVEL_DB=/ruta/a/clavel.db` antes de iniciar la aplicación.
