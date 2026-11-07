# Diccionario de datos y puerta CP1 — P0022

Estado: **Awaiting review**; evidencia y revisión en [REVISION_P0022.md](REVISION_P0022.md).
Implementación documentada: `65f270f07808ed4db732dc97133a46ec331fe2d5`;
Alembic head: `0007_recommendation_returns`. Este documento no cambia esquema,
OpenAPI ni políticas de producción.

## Procedencia y convenciones

La fuente ejecutable son las migraciones de `migrations/versions/` y los módulos
de `src/clavel/database/`; `metadata.create_all()` no instala los triggers.
El importador local es `src/clavel/data/offline_import.py` y su contrato v1 es
`src/clavel/data/import_validation.py`. No existe aquí un mapeo de proveedor
validado. Los identificadores externos deben ser tokens opacos sin datos personales;
ni su forma ni `subject_kind` autorizan inferir identidad o demografía.

En las tablas siguientes, `?` significa nullable; los demás campos son NOT NULL.
`id` es BIGINT identity y PK local, sin significado externo. FK conserva la
integridad referencial y no implica borrado en cascada. Los códigos/referencias
son sensibles a mayúsculas, no vacíos y sin espacios exteriores; los nombres
descriptivos deben contener caracteres distintos de espacios. TIMESTAMPTZ guarda
instantes finitos; los repositorios exigen zona explícita. Presentación en UTC.
Las restricciones SQL y las comprobaciones del importador se distinguen abajo.

## Catálogo e inventario

| Tabla | Campos y tipos | Significado, claves y restricciones |
| --- | --- | --- |
| `categories` | `id BIGINT`; `code TEXT`; `name TEXT` | PK `id`, código único; categoría explícita de catálogo. |
| `skus` | `id BIGINT`; `sku TEXT`; `name TEXT`; `category_id BIGINT?` | PK `id`, SKU único global; FK a categories. Categoría ausente permanece desconocida. |
| `hardware_attributes` | `sku_id BIGINT`; `name TEXT`; `value_kind TEXT`; `text_value TEXT?`; `number_value NUMERIC?`; `boolean_value BOOLEAN?`; `unit TEXT?` | PK `(sku_id,name)`, FK SKU. Tipo `unknown`, `text`, `number` o `boolean`; exactamente su columna tiene valor, o todas NULL para unknown. Texto no vacío, número finito. Unidad opcional, sin espacios exteriores y sólo con number/unknown; no convierte unidades ni acredita compatibilidad. |
| `inventory` | `sku_id BIGINT`; `sellable_stock BIGINT?`; `source_version BIGINT`; `observed_at TIMESTAMPTZ` | PK/FK SKU, una observación por SKU. Stock y versión no negativos. `observed_at` es tiempo de la fuente, no recepción. |

El trigger `inventory_observation_order` impide cambiar SKU, repetir/regresar
versión y regresar tiempo. Una versión mayor puede compartir timestamp. Es un
contrato local de un flujo autoritativo por SKU, no el protocolo de un proveedor.
El replay de inventario se rechaza incluso si los valores son idénticos.
Catálogo/atributos usan upsert sin versión de fuente: gana la última escritura;
los campos suministrados, incluidos los desconocidos, reemplazan los previos.

Una fila de inventario ausente y `sellable_stock=NULL` significan desconocido;
`0` significa cero observado. Stock positivo antiguo conserva su valor y su
antigüedad: nunca equivale a stock vigente verificado. Este almacenamiento no
determina elegibilidad. Atributo ausente o `value_kind=unknown` tampoco verifica
compatibilidad. Se necesita una política de frescura y compatibilidad explícita.

## Sujetos y sesiones

| Tabla | Campos y tipos | Significado, claves y restricciones |
| --- | --- | --- |
| `customers` | `id BIGINT`; `opaque_ref TEXT`; `subject_kind TEXT`; `created_at TIMESTAMPTZ`; `last_activity_at TIMESTAMPTZ` | PK id; referencia única entre ambos tipos. Kind explícito `anonymous`/`registered`. Actividad >= creación. No guarda nombre, email ni demografía. |
| `sessions` | `id BIGINT`; `opaque_ref TEXT`; `customer_id BIGINT?`; `started_at TIMESTAMPTZ`; `last_activity_at TIMESTAMPTZ` | PK id; referencia única; FK opcional a customers; UNIQUE `(id,customer_id)` soporta telemetría. Actividad >= inicio. NULL es sesión sin sujeto resuelto. |

Los repositorios resuelven referencias exactas; un lookup desconocido no crea
filas. La creación exige tipo explícito. El replay preserva creación y avanza
actividad con GREATEST. Los repositorios rechazan cambiar tipo o propietario de
sesión, incluido NULL; no son restricciones universales de UPDATE SQL. No hay
promoción anónimo→registrado, fusión ni atribución histórica automática.

## Ventas y devoluciones

| Tabla | Campos y tipos | Significado, claves y restricciones |
| --- | --- | --- |
| `sales_orders` | `id BIGINT`; `source_system TEXT`; `source_order_id TEXT`; `customer_id BIGINT?`; `sold_at TIMESTAMPTZ`; `currency TEXT` | PK id; UNIQUE `(source_system,source_order_id)` y `(id,source_system)`; FK opcional customers. Moneda SQL: tres letras ASCII mayúsculas, sin afirmar registro ISO ni conversión. |
| `sales_lines` | `id BIGINT`; `order_id BIGINT`; `source_system TEXT`; `source_line_id TEXT`; `sku_id BIGINT`; `quantity NUMERIC`; `unit_price NUMERIC`; `unit_cost NUMERIC?` | PK id; UNIQUE `(order_id,source_line_id)` y `(id,source_system)`; FK `(order_id,source_system)` a cabecera, FK SKU. Importes unitarios en moneda de cabecera. |
| `sales_returns` | `id BIGINT`; `source_system TEXT`; `source_return_id TEXT`; `source_line_id TEXT`; `sale_line_id BIGINT`; `quantity NUMERIC`; `returned_at TIMESTAMPTZ` | PK id; UNIQUE `(source_system,source_return_id,source_line_id)`; FK `(sale_line_id,source_system)` a venta. Hereda moneda de la venta. Índice por sale_line_id. |

Cantidad: `0 < quantity < 10^12`, hasta seis decimales significativos tras el
punto. Precio/costo: `0 <= amount < 10^15`, hasta cuatro decimales. NUMERIC sin
escala fija más CHECK rechaza exceso de precisión, NaN e infinitos en lugar de
redondear. Costo NULL es desconocido, distinto de costo cero. Cliente NULL en una
venta no crea ni atribuye un sujeto.

Los triggers `sales_return_quantity_guard` y `sales_line_quantity_guard`
serializan cambios sobre la línea vendida: suma de devoluciones <= vendido,
no reducir venta por debajo de lo devuelto y no reasignar devolución a otra
venta/fuente. No hay una restricción temporal que ordene returned_at y sold_at.
Los repositorios exigen replay completo e idéntico de pedidos/devoluciones;
conflictos no sobrescriben lo anterior. Una operación fallida revierte su grupo
y el importador revierte el archivo entero. Los repositorios no hacen commit
de la transacción del llamador.

## Telemetría de recomendaciones

| Tabla | Campos y tipos | Significado, claves y restricciones |
| --- | --- | --- |
| `recommendation_requests` | `request_id UUID`; `customer_id BIGINT`; `session_id BIGINT?`; `requested_at TIMESTAMPTZ` | PK request_id, UNIQUE `(request_id,customer_id)`; FK sujeto obligatorio; FK `(session_id,customer_id)` exige sesión del mismo sujeto si se indica. |
| `recommendation_results` | `request_id UUID`; `sku_id BIGINT`; `customer_id BIGINT`; `position INTEGER`; `generated_at TIMESTAMPTZ` | PK `(request_id,sku_id)`; FK SKU y `(request_id,customer_id)`; UNIQUE `(request_id,position)` y `(request_id,sku_id,customer_id)`; posición > 0. |
| `recommendation_events` | `event_id UUID`; `request_id UUID`; `sku_id BIGINT`; `customer_id BIGINT`; `event_type TEXT`; `occurred_at TIMESTAMPTZ`; `recorded_at TIMESTAMPTZ` | PK event_id; FK `(request_id,sku_id,customer_id)` al resultado exacto. Tipos exposure/click/add_to_cart/purchase/return. Índice `(request_id,sku_id,event_type)`. |

UUID estables permiten deduplicación de reintentos en repositorios; un payload
distinto con el mismo UUID se rechaza. Generación no prueba exposición. Una
solicitud puede tener cero resultados y un resultado cero eventos; NULL o ausencia
de observación no acredita un conteo medido. Los eventos exigen observación
explícitamente verificada en el repositorio; la base no prueba su autenticidad.
Los tiempos de fuente y recepción no se infieren uno de otro; orden de relojes y
ventanas de atribución requieren política. No se acredita stock ni compatibilidad.
El downgrade de 0007 a 0006 se bloquea si existen eventos return: no borrarlos
para forzar una migración en un entorno con evidencia que deba preservarse.

## Features conductuales — P0023 (`behavioral-v1`)

Definición ejecutable: `src/clavel/intelligence/clustering/features.py`;
ejemplo y límites verificados por `tests/test_behavioral_features.py`.
Es una baseline local para preparar clustering, **sin calibración ni aceptación
live**. No entrena BIRCH, no asigna segmentos ni autoriza recomendaciones,
stock o compatibilidad. No modifica esquema ni OpenAPI.

Entrada: eventos explícitamente verificados de `RecommendationRepository`,
un `customer_id` local, cutoff con zona y `FeaturePolicy`. Sólo se usa telemetría
de recomendaciones: no representa toda la conducta del cliente. No se mezclan
ventas contables con eventos purchase, evitando contarlos dos veces. Un evento
purchase no equivale a cantidad, ingreso o pedido distinto. No se atribuyen
ventas sin cliente ni se fusionan sujetos anónimos/registrados.

La ventana por defecto es **90 días transcurridos**, `[cutoff − 90 días, cutoff)`.
Además, `recorded_at < cutoff`: llegada tardía, llegada exactamente en cutoff,
evento en cutoff y evento futuro quedan fuera. La frontera inferior de ocurrencia
se incluye; no hay límite inferior de recepción. Todos los instantes se convierten
a UTC antes de restar/comparar; no se usan días de calendario local ni reloj actual.
Replay idéntico de UUID cuenta una vez; payload conflictivo de un UUID visible
falla. No se deduplican UUID distintos por SKU o fecha. El orden de entrada no
cambia el resultado. Los tiempos sin zona y tipos/identificadores inválidos fallan.

`HistoryCoverage(customer_id, start, end, event_types)` declara que la extracción
es completa y verificada para esos tipos y ese sujeto, **conocida al cutoff**.
Se exige `start <= cutoff − lookback` y `end == cutoff`; una extracción posterior
no demuestra completitud histórica. Cobertura ausente, parcial en tiempo o de
otro snapshot deja las features desconocidas; cobertura de otro sujeto falla.
No se infiere cobertura de tener filas, conexión disponible o cero resultados SQL.
El llamador debe conservar evidencia de completitud; no existe adaptador live ni
protocolo de proveedor aprobado en esta tarea. Un evento aislado no acredita
completitud, y `recorded_at` por sí solo no acredita su autenticidad.

| Feature por sujeto/ventana | Definición y desconocidos |
| --- | --- |
| `frequency[tipo]` | Número de UUID distintos por exposure/click/add_to_cart/purchase/return. `None` si ese tipo no tiene cobertura completa; `0` si está cubierto y no tiene eventos. Sin ponderación ni normalización. |
| `recency_days[tipo]` | `(cutoff − max(occurred_at)) / 86400 segundos`, fracción de día permitida. `None` sin cobertura o sin evento; consultar frequency para distinguir ambos casos. |
| `product_affinities[tipo][sku_id]` | Conteo del SKU / frequency de ese tipo. Distribución separada por tipo, suma 1 con tolerancia numérica; no se combinan pesos. `None` sin cobertura o con denominador cero, nunca una distribución uniforme inventada. Con denominador positivo, SKU omitido tiene participación observada cero dentro de ese tipo/ventana; no demuestra desinterés. No se infieren categorías desconocidas. |
| `interaction_count` | Suma de click + add_to_cart + purchase, sólo si los tres tipos tienen cobertura completa; de lo contrario `None`. Exposure y return no son evidencia positiva. |
| `active_days` | Fechas UTC distintas de esas interacciones, con el mismo requisito de cobertura; cero sólo para historial observado vacío. |
| `cold_start` | `unknown` sin cobertura positiva completa; `insufficient` si no alcanza ambos mínimos; `sufficient` con **>=3 interacciones y >=2 fechas UTC**. Los mínimos son configuración explícita de baseline, no umbrales aprobados para producción. No significa elegibilidad comercial. |

Return conserva señal propia: no resta purchase ni supone enlace a una venta;
la telemetría no incluye esa atribución. Exposure tampoco cuenta como click.
Cada salida conserva cutoff UTC, inicio de ventana, versión y política (lookback
y ambos mínimos) para reproducibilidad. Cambiar política exige comparaciones
explícitas; no se realiza tuning. No se imputan desconocidos a cero ni se produce
todavía un vector numérico para BIRCH. Evidencia insuficiente/desconocida se deja
para una política posterior de fallback; no se inventa asignación de segmento.

Ejemplo **sintético, mechanics only**, sujeto 1, cutoff `2026-04-01T00:00:00Z`:
con cobertura completa desde `2026-01-01T00:00:00Z`, click SKU 11 el 30 y 31 de
marzo, click SKU 22 el 31, purchase SKU 22 el 1 de enero, return SKU 22 y exposure
SKU 33 el 31 de marzo. Cada evento se recibió un segundo después de ocurrir.
Se agrega un replay idéntico, un click ocurrido exactamente al cutoff recibido
antes (desfase sintético), otro recibido exactamente al cutoff y uno ocurrido
un microsegundo antes del inicio: ninguno añade frecuencia.

| Resultado | Valor esperado |
| --- | --- |
| frequency | exposure=1, click=3, add_to_cart=0, purchase=1, return=1 |
| recency_days | exposure=1, click=1, add_to_cart=None, purchase=90, return=1 |
| product_affinities | click={11: 2/3, 22: 1/3}; purchase={22: 1}; return={22: 1}; exposure={33: 1}; add_to_cart=None |
| Evidencia positiva | interaction_count=4, active_days=3, cold_start=sufficient |
| Mismo sujeto sin eventos, cobertura completa | frequency=0 para todos; recency/afinidades=None; interaction_count=0, active_days=0, cold_start=insufficient |
| Mismo sujeto sin cobertura | frequency/recency/afinidades=None por tipo; interaction_count/active_days=None, cold_start=unknown |

Validación local: `.venv/bin/python -m pytest -q tests/test_behavioral_features.py`.
Evidencia P0023: **36 passed**, datos sintéticos, sin consultas live. Incluye el
ejemplo anterior, límites de ocurrencia/recepción, replay/conflicto, aislamiento
de sujeto, cobertura parcial/ausente, ceros, umbrales y fechas UTC/DST.
Estado P0023: **Awaiting review**; aceptación a cargo del revisor independiente.
Preparado para revisión independiente de Codex; no acredita representatividad,
retención, completitud de proveedor ni aceptación de producción.

## Archivo canónico v1 y procedencia sintética

JSONL UTF-8: una fila de venta o devolución por línea física, sin líneas vacías,
claves duplicadas, campos adicionales ni números no finitos.

| Tipo | Campos obligatorios | Opcionales y resolución |
| --- | --- | --- |
| Ambos | `contract_version="v1"`, `record_type`, `source_system`, `source_order_id`, `source_line_id`, `quantity` | Referencias opacas exactas; se rechazan controles Unicode y espacios exteriores. |
| sale | `record_type="sale"`, `sku`, `sold_at`, `currency`, `unit_price` | `unit_cost` y `customer_ref` omitidos/NULL quedan desconocidos. SKU y cliente explícito deben existir. |
| return | `record_type="return"`, `source_return_id`, `sale_source_line_id`, `returned_at` | Resuelve venta por fuente/pedido/línea original; no incluye moneda ni cliente propios. |

El validador acepta decimales exactos (texto, entero, Decimal; JSON decimal se
lee como Decimal), no float binario ni booleano; no redondea. Normaliza moneda
ASCII a mayúsculas e instantes ISO con segundos y offset a UTC; rechaza offset
desconocido `-00:00`. Las filas de un pedido deben tener cabeceras idénticas y
el pedido completo. Duplicados dentro del archivo se rechazan. Se procesan ventas
antes de devoluciones aunque el archivo las intercale. Replay exacto es idempotente.
Dry run ejecuta escrituras/restricciones y hace rollback: secuencias pueden avanzar.
Reporte seguro: posiciones/campos/códigos, sin valores ni errores SQL privados.
CLI: 0 imported/dry_run, 1 rejected, 2 unavailable. Un fallo deja processed_rows=0;
unknown_cost es warning y no fabrica costo cero.

`generate_fixtures.py --seed 21` genera exclusivamente datos inventados, con
`provenance.synthetic=true`, alcance a todos los registros, generador v1,
parámetros, semilla y advertencia «mechanics only; not live or representative».
El envelope no se agrega a filas v1 porque extra fields se rechazan: conservar
bundle y JSONL juntos en el entorno de pruebas. Fecha fija de referencia:
2026-01-31T00:00:00Z; no usar el reloj actual para afirmar frescura.
Defaults: 2 categorías, 12 SKU/atributos, 11 inventarios, 8 sujetos,
24 ventas de una línea y 6 devoluciones; reserva un SKU y dos sujetos sin compras.
No genera sesiones ni telemetría. Estas tablas no tienen una columna universal
de procedencia: una carga live requiere procedencia externa revisada.

## Retención y decisiones pendientes de producción

| Familia | Pregunta que debe resolverse antes de una carga live | Estado actual |
| --- | --- | --- |
| Catálogo/inventario | Fuente autoritativa, frecuencia, frescura, conservación histórica y calidad/cobertura de atributos | Sin proveedor verificado; inventario guarda sólo observación actual, sin TTL automático. |
| Sujetos/sesiones | Retención, base de uso, borrado/anonymización y propagación a respaldos; política de enlace anónimo/registrado | No se ha fijado duración ni existe trabajo automático de purga/fusión. |
| Ventas/devoluciones | Conservación contable, correcciones y obligaciones aplicables; desvinculación del cliente preservando integridad | No se inventa plazo ni política de borrado. FK y triggers siguen vigentes. |
| Telemetría | Ventanas de atribución, retención, acceso y borrado coordinado de UUID/enlaces | No hay TTL, ventanas aprobadas ni evidencia de verificación live. |
| Fixtures/evidencia | Cuánto conservar reportes de revisión y bundles sintéticos en CI | pytest elimina su base/cluster al cerrar; archivos temporales siguen su política de retención. Documentos/log/versionado preservan evidencia sin datos personales. |

Son preguntas abiertas para el uso live, no afirmaciones de autorización. CP1
evalúa mecánica local sintética; una carga de producción queda Blocked hasta
resolver sus entradas/políticas obligatorias, sin inventar decisiones Q01–Q12.

## Reconstrucción y siembra desechable

Desde la raíz del repo, con `.venv` instalada y PostgreSQL nativo accesible:

```bash
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -q tests/integration/test_data_gate.py
```

Es la receta verificada completa: cluster/socket privados sin TCP, base única
vacía, upgrade head, semilla, dry run/import/replay, downgrade base/upgrade head,
segunda siembra y limpieza. También puede usar `CLAVEL_MIGRATION_TEST_URL` sólo
contra un servicio de pruebas autorizado donde pueda crear/borrar bases únicas;
ese valor se mantiene fuera de código, salidas y log. No usar una base operativa.

Para inspección manual, configurar `DATABASE_URL` únicamente con la base
desechable propia y `APP_ENV=test`, sin imprimirlos. Alembic puede leer archivos
de configuración locales; el importador y la semilla de abajo usan sólo entorno.

```bash
.venv/bin/python -m alembic upgrade head
fixture_dir=$(mktemp -d "${TMPDIR:-/tmp}/clavel-p0022.XXXXXX")
.venv/bin/python scripts/generate_fixtures.py --seed 21 --output "$fixture_dir/bundle.json"
```

Guardar el siguiente bloque como `$fixture_dir/seed.py` y ejecutarlo con
`.venv/bin/python "$fixture_dir/seed.py" "$fixture_dir/bundle.json" "$fixture_dir/batch.jsonl"`.
Es una siembra **de una sola ejecución sobre base vacía**: repetir inventario
con la misma versión debe fallar. La prueba ejecuta este bloque documental.

```python
from datetime import datetime
import json
from pathlib import Path
import sys

from clavel.core.settings import load_settings
from clavel.database import Database
from clavel.database.repositories import (
    CatalogRepository, HardwareAttribute, StockObservation, StockRepository,
)

bundle_path, batch_path = map(Path, sys.argv[1:])
bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
if (bundle["provenance"]["synthetic"] is not True
        or bundle["provenance"]["generator"] != "clavel.data.synthetic_fixtures:v1"):
    raise ValueError("only the invented v1 bundle is supported")
database = Database(load_settings(env_file=None))
with database.session() as connection:
    catalog = CatalogRepository(connection)
    category_ids = {
        row["code"]: catalog.upsert_category(row["code"], row["name"]).id
        for row in bundle["categories"]
    }
    sku_ids = {}
    for row in bundle["catalog"]:
        sku = catalog.upsert_sku(row["sku"], row["name"], category_ids[row["category_code"]])
        sku_ids[row["sku"]] = sku.id
        for attribute in row["attributes"]:
            catalog.upsert_attribute(HardwareAttribute(sku_id=sku.id, **attribute))
    for row in bundle["subjects"]:
        connection.execute(
            "INSERT INTO customers (opaque_ref, subject_kind, created_at, last_activity_at) "
            "VALUES (%s, %s, %s, %s)",
            (row["opaque_ref"], row["subject_kind"],
             datetime.fromisoformat(row["created_at"]),
             datetime.fromisoformat(row["last_activity_at"])),
        )
    stock = StockRepository(connection)
    for row in bundle["inventory"]:
        stock.upsert(StockObservation(
            sku_id=sku_ids[row["sku"]], sellable_stock=row["sellable_stock"],
            source_version=row["source_version"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
        ))
with batch_path.open("x", encoding="utf-8") as stream:
    for row in bundle["sales"] + bundle["returns"]:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
```

Conservar el bundle de procedencia junto al batch; no imprimir filas.

```bash
.venv/bin/python scripts/import_canonical.py "$fixture_dir/batch.jsonl" --dry-run
.venv/bin/python scripts/import_canonical.py "$fixture_dir/batch.jsonl"
.venv/bin/python scripts/import_canonical.py "$fixture_dir/batch.jsonl"
```

Resultados: dry_run/imported/imported, 30 filas procesadas por ejecución y ocho
warnings unknown_cost. El último comando no duplica ventas/devoluciones. La
semilla no verifica stock ni compatibilidad y no procesa datos de proveedores.

Reset **sólo de esa base desechable** (destruye sus datos):

```bash
.venv/bin/python -m alembic downgrade base
.venv/bin/python -m alembic upgrade head
```

Tras downgrade sólo queda `alembic_version` vacía; tras upgrade las doce tablas
están vacías y head es 0007. Usar un nuevo fixture_dir para repetir la generación
y la siembra: los archivos se crean exclusivamente y no se sobrescriben. Cerrar
el cluster/base y eliminar únicamente el directorio temporal creado para esta
prueba. pytest elimina su base/cluster automáticamente; sus directorios temporales
pueden conservarse para diagnóstico según su configuración. No aplicar esta receta a datos live.
