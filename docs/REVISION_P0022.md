# CP1 — expediente P0022

Estado: **Awaiting review**. Preparado por Codex; revisión independiente automática
pendiente. No hay firmas humanas solicitadas ni aceptación atribuida a Emi.
Sólo el orquestador puede registrar Accepted tras checks satisfactorios y una
revisión independiente cuya última línea stdout sea exactamente `VERDICT: ACCEPTED`.

## Revisiones y entorno

- Fuente backend sin cambios: `65f270f07808ed4db732dc97133a46ec331fe2d5`.
- Prerrequisitos Accepted, verificados previamente por el orquestador:
  P0018 `a2773313fc20dc0fc38bcf98d1fbfeeccf7ae1a8`,
  P0020 `31941fdb27e60f3cdfa26b960ecc3d184b59aeb6`,
  P0021 `17bde414a7f30be096a031465186b1e68cc47ce7`.
- Candidato de implementación y prueba: `806593d5b2493a4054ed1bc2a4408360ae425ec8`.
  El cierre posterior sólo fija este identificador en el expediente y completa
  la bitácora; la revisión independiente debe registrar `git rev-parse HEAD`
  completo del checkout final revisado.
- Python 3.13.15, PostgreSQL 17.11 nativo, `.venv` del proyecto. El harness crea
  cluster/socket sin TCP y bases únicas desechables; no usa datos de proveedores.
- Migraciones reales hasta `0007_recommendation_returns`; datos **sintéticos**,
  generador `clavel.data.synthetic_fixtures:v1`, semilla 21, referencia fija UTC
  2026-01-31. Las pruebas unitarias complementarias no son evidencia live.

## Criterios exigidos por P0022 y CHECKPOINT.md

Los resultados corresponden a los comandos R1/R2 de abajo. En cada fila el SHA
identifica el candidato que contiene las fuentes y la prueba ejercitadas. La
implementación backend conserva el SHA fuente indicado arriba; el candidato
añade documentación, la prueba integrada y el registro append-only.

| Criterio / tareas | SHA candidato completo | Reproducción y evidencia | Resultado observado | Revisor |
| --- | --- | --- | --- | --- |
| Migración PostgreSQL limpia / P0022 | `806593d5b2493a4054ed1bc2a4408360ae425ec8` | R1 y R2 `test_migrations.py`; base sin tablas → head, downgrade base → head; error DDL inyectado revierte tabla y revisión. | R1 pasó dos ciclos; R2 pasó, sin fallos ni omisiones. | Codex ejecutor; independiente Pending. |
| Restricciones / P0022 | `806593d5b2493a4054ed1bc2a4408360ae425ec8` | R2 suites de catálogo, inventario, sujetos, ventas y telemetría: FK/UNIQUE/CHECK, tipos/precisión, triggers y concurrencia. R1 preserva NULL/cero/antigüedad y compatibilidad desconocida. | R1 y R2 pasaron, sin fallos ni omisiones. | Codex ejecutor; independiente Pending. |
| Replay y rollback / P0018, P0020, P0022 | `806593d5b2493a4054ed1bc2a4408360ae425ec8` | R2 repositorios y offline_import: reintentos exactos, conflictos, rollback de grupos/archivo, transacciones y carreras. R1 prueba dry run y replay sin duplicación. | R1 y R2 pasaron, sin fallos ni omisiones. | Codex ejecutor; independiente Pending. |
| Importación canónica / P0020, P0022 | `806593d5b2493a4054ed1bc2a4408360ae425ec8` | R2 import_validation/offline_import, resolución de referencias, diagnósticos seguros, rechazo tardío y rollback. R1 ejecuta CLI real con lote generado de 30 filas. | R1: dry_run/imported/imported; 30 procesadas, ocho warnings unknown_cost; R2 pasó, sin fallos ni omisiones. | Codex ejecutor; independiente Pending. |
| Fixtures sintéticos y procedencia / P0021, P0022 | `806593d5b2493a4054ed1bc2a4408360ae425ec8` | R2 test_synthetic_fixtures: reproducibilidad, cold start, stock desconocido/antiguo, envelope. R1 consume ese envelope y el bloque Python del diccionario. | R1: 2 categorías, 12 SKU/atributos, 11 inventarios, 8 sujetos, 24 ventas/líneas y 6 devoluciones; R2 pasó, sin fallos ni omisiones. | Codex ejecutor; independiente Pending. |
| Diccionario, retención y seed/reset / P0022 | `806593d5b2493a4054ed1bc2a4408360ae425ec8` | [DICCIONARIO_DATOS.md](DICCIONARIO_DATOS.md), R1 ejecuta su bloque Python contra PostgreSQL vacío y vuelve a sembrar tras reset completo. | R1: 1 passed, 0 failed, 0 skipped (5.67 s); preguntas live explícitas, sin políticas inventadas. | Codex ejecutor; independiente Pending. |

## Reproducción

Ejecutar desde raíz del repo con dependencias ya instaladas en `.venv` y los
binarios `initdb`/`pg_ctl` disponibles para el usuario sin privilegios. No se
necesitan credenciales ni un proveedor. `CLAVEL_REQUIRE_POSTGRES=1` convierte
ausencia de PostgreSQL en fallo, no en evidencia omitida. Si el entorno define
`CLAVEL_MIGRATION_TEST_URL`, debe apuntar exclusivamente al servicio desechable
de pruebas autorizado; no imprimir su valor. Esta ejecución usó PostgreSQL local.

R1 — requisito Done when y receta del diccionario:

```bash
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -q tests/integration/test_data_gate.py
```

R2 — suites de repositorios/importación y restricciones CP1:

```bash
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -q \
  tests/integration/test_migrations.py \
  tests/integration/test_catalog_schema.py \
  tests/integration/test_inventory_schema.py \
  tests/integration/test_customer_session_schema.py \
  tests/integration/test_sales_return_schema.py \
  tests/integration/test_recommendation_telemetry.py \
  tests/integration/test_repositories.py \
  tests/integration/test_customer_session_repositories.py \
  tests/integration/test_sales_repository.py \
  tests/integration/test_recommendation_repository.py \
  tests/integration/test_offline_import.py \
  tests/test_import_validation.py tests/test_synthetic_fixtures.py \
  tests/test_database.py tests/test_repository_rules.py
```

Resultado R2: **596 passed, 7 subtests passed, 0 failed, 0 skipped**, en 264.61 s.
Una advertencia de dependencia FastAPI/Starlette sobre httpx; no hubo errores.
Con R1: **597 pruebas y 7 subtests aprobados**, sin omisiones. El resumen y los
comandos exactos están en `log/CODEX_LOG.md`, junto con START/END y el intento
inicial del chequeo de whitespace; la revisión independiente sigue pendiente.

Comprobación adicional del diccionario con `.venv/bin/python`: las doce tablas
y sus 65 columnas coinciden exactamente con metadata PostgreSQL en campos,
tipos y nulabilidad. Los triggers se contrastaron con las migraciones y se
ejercitan en R2.

El chequeo estándar de whitespace pasa para documentos/prueba. Una ejecución
inicial sobre el diff completo detectó separadores con espacios finales en
entradas nuevas del log; se corrigió el registrador para entradas futuras y se
preservaron los bytes ya escritos por la regla append-only. El chequeo del log
pasa con `git -c core.whitespace=-blank-at-eol diff --check -- log/CODEX_LOG.md`;
la excepción sólo aplica al espacio final de la bitácora.

## Límites y siguiente paso

La evidencia prueba PostgreSQL y mecánica local con datos inventados; no prueba
calidad/cobertura de un catálogo real, legitimidad de identificadores, protocolo
de inventario de proveedor, retención autorizada ni compatibilidad live. Estas
entradas para uso live permanecen **Blocked** hasta resolver sus decisiones
obligatorias; P0022 no exige un proveedor live y no inventa decisiones Q01–Q12.

Revisión independiente pendiente sobre el SHA completo del candidato: comprobar
documento contra fuentes, repetir R1/R2 y registrar el veredicto real. Fallos,
entradas faltantes o decisiones live requeridas mantienen bloqueado el alcance
correspondiente. El ejecutor no modifica `log/STATUS.md` ni marca Accepted.
