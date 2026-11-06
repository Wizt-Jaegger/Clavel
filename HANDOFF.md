# HANDOFF — Clavel

## 1. Estado actual
MVP inicial implementado en una estructura nueva. Los archivos que se recibieron (`Proyecto`, `Prpuesta.txt`, `Resumen del proyecto.md`) son documentos de decisiones y alcance, no un repositorio de código preexistente.

## 2. Funcionalidades implementadas
- FastAPI con SQLite local y carga automática de datos ficticios.
- Catálogo de 16 componentes/periféricos; endpoints de alta, edición, listado y eliminación.
- Registro y listado de clientes.
- Compras con varias líneas, validación de stock y decremento transaccional.
- Dashboard web con métricas, productos populares, clientes, segmentos y recomendaciones de ejemplo.
- Pipeline de segmentación: StandardScaler + TruncatedSVD cuando la dimensionalidad lo permite + Normalizer L2 + BIRCH.
- Recomendaciones por popularidad del segmento o global; excluye stock cero y artículos ya comprados.
- Comprobación básica de socket y tipo de RAM cuando las compras previas permiten inferirlos.
- Endpoint y botón para reiniciar datos demo.
- Pruebas de dashboard, flujo de compra, segmentación/recomendaciones y stock.

## 3. Pendientes priorizados
1. Añadir formularios web para crear/editar productos y clientes, y registrar compras sin usar `/docs`.
2. Añadir endpoint de detalle de cliente e historial de compras.
3. Implementar evaluador determinista con backtesting temporal (margen, cobertura y precisión/relevancia); no permitir fuga de datos.
4. Versionar configuraciones y métricas de segmentación; comparar score antes/después y rollback.
5. Solo después, integrar agente proponente opcional (salida Pydantic validada) y orquestación LangGraph.
6. Ampliar compatibilidad técnica de hardware con reglas explícitas y pruebas.

Verificación ejecutada: `python -m pytest -q` → **4 passed**. Instalación por pip no se pudo probar porque el entorno de ejecución no tiene acceso a internet; las dependencias ya estaban disponibles globalmente.
2. Añadir formularios web para crear/editar productos y clientes, y registrar compras sin usar `/docs`.
3. Añadir endpoint de detalle de cliente e historial de compras.
4. Implementar evaluador determinista con backtesting temporal (margen, cobertura y precisión/relevancia); no permitir fuga de datos.
5. Versionar configuraciones y métricas de segmentación; comparar score antes/después y rollback.
6. Solo después, integrar agente proponente opcional (salida Pydantic validada) y orquestación LangGraph.
7. Ampliar compatibilidad técnica de hardware con reglas explícitas y pruebas.

## 4. Estructura
- `app/main.py`: FastAPI y endpoints.
- `app/db.py`: conexión, esquema SQLite y helpers.
- `app/seed.py`: catálogo y dataset sintético.
- `app/analytics.py`: pipeline BIRCH.
- `app/recommendations.py`: ranking y compatibilidad básica.
- `app/templates/index.html`: dashboard web.
- `tests/test_workflows.py`: pruebas de flujos principales.
- `README.md`: instalación, ejecución y limitaciones.

## 5. Dependencias e instalación
Python 3.10+. `pip install -r requirements.txt`. Dependencias: FastAPI, Uvicorn, scikit-learn, pandas, Jinja2, httpx y pytest.

## 6. Base de datos
SQLite `clavel.db` en la raíz (o ruta de `CLAVEL_DB`). Tablas: `customers`, `products`, `transactions`, `transaction_items`, `segments`, `model_runs`. `uvicorn app.main:app --reload` inicializa esquema y datos demo. `POST /api/demo/reset` reinicia.

## 7. Comandos
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest -q
```

## 8. Bugs y limitaciones conocidas
- Interfaz permite consultar y ejecutar, pero las altas/ediciones/ventas se hacen por API `/docs` hasta agregar formularios.
- Compatibilidad solo cubre reglas simples de socket/RAM y se infiere de compras previas; no equivale a un configurador de PC.
- BIRCH con SVD es exploratorio; parámetros fijos y sin evaluación de calidad/backtesting.
- No se implementó agente LLM ni automejora: se reserva para una fase controlada por evaluador determinista.

## 9. Siguiente sesión: pasos exactos
1. Inspeccionar el repositorio y leer `HANDOFF.md` y `PROGRESS.md` completos.
2. Verificar los archivos y ejecutar instalación/pruebas; no reconstruir ni reemplazar lo ya implementado.
3. Corregir fallos existentes antes de agregar funciones.
4. Implementar formularios HTML/JS sencillos para alta de clientes, productos y registro de compras, consumiendo los endpoints actuales.
5. Añadir pruebas de integración para los formularios/endpoints nuevos y actualizar README, HANDOFF y PROGRESS.

## Prompt de continuación
"Inspecciona el repositorio completo, lee HANDOFF.md y PROGRESS.md, verifica la implementación actual y ejecuta las pruebas. Continúa desde la última tarea completada: añade formularios web simples para crear clientes, crear/editar productos y registrar compras usando los endpoints existentes. No reconstruyas el proyecto ni repitas funcionalidades ya implementadas. Corrige primero cualquier fallo encontrado, agrega pruebas y actualiza ambos documentos de continuidad."
