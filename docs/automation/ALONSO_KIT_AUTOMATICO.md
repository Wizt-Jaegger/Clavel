# Kit de Alonso: revisión automática

Preparación del orquestador y del encargo P0007; esta entrega no ejecuta P0007
ni acepta CP0. Base compartida: `381a79f3bf0cdd546fc90ea62cc6748346646d9a`.

El [parche del kit](ALONSO_KIT_AUTOMATICO.patch) conserva la implementación y
las pruebas necesarias para reproducir la instalación en
`/home/alonso/Documents/clavel-codex-kit`. Se aplica sobre la versión del kit
inspeccionada en esta sesión; `git apply --check` debe pasar antes de aplicarlo.

Cambios:

- `gates.txt` existe y está vacío. No hay pausas manuales. Su ausencia activa
  los valores antiguos; no eliminarlo.
- P0007 requiere P0006 y E0001. Verifica OpenAPI y fixtures sintéticos de éxito,
  vacío y error, incluidos 401/403; registra el SHA completo. No requiere M0002
  ni firma de Manu. El encargo reserva `docs/REVISION_P0007.md` para su evidencia.
- La revisión independiente acepta únicamente código 0 y última línea de stdout
  exactamente `VERDICT: ACCEPTED`. Stderr, veredictos parciales y texto posterior
  no aceptan. El registro identifica revisión automática, SHA, fecha y revisor.
- `--no-review` queda deshabilitado; con gates vacías también `--accept`.
- STATUS conserva las filas P/E/M, y E0001 Accepted puede satisfacer directamente
  la dependencia. Un ID externo no sobreescribe una fila explícitamente no aceptada.
- Fallos, insumos faltantes y decisiones live obligatorias siguen bloqueando.
  Las pruebas Python del proyecto requieren su `.venv` local.

Validación:

- `.venv/bin/python -m pytest /tmp/clavel-kit-auto-review-381a79f/tests/test_orchestrator.py -q --tb=short`:
  **29 passed**. Incluye dos tareas consecutivas P0007/P0008 con implementación,
  checks y revisión simulados, rechazo por código no cero, stderr, formato,
  cambios del revisor, insumos faltantes y dependencias no aceptadas.
- `.venv/bin/python -m pytest tests/test_openapi_contract.py tests/test_api_shell.py -q --tb=short`:
  **293 passed, 1 warning** de deprecación Starlette, ejecutado fuera del sandbox.
  El intento dentro del sandbox se bloqueó y su diagnóstico agotó 25 segundos.
- Reconstrucción del kit con `git apply --check`, aplicación en copia aislada y
  comparación SHA256 de los ocho archivos: correcta; incluye el archivo vacío.
- `--dry-run` sobre una copia del STATUS real: únicamente P0007 lista, sin perder
  filas de Emi. No se modificó el STATUS real ni se lanzó Codex.

Toda esta evidencia es de fixtures, dobles o checks locales. No constituye
aceptación live de autenticación, autorización, proveedores o despliegue.

Tras instalar el kit y dejar el repo limpio, comprobar disponibilidad:

```bash
python3 /home/alonso/Documents/clavel-codex-kit/orchestrator.py --repo /home/alonso/Documents/GitRepos/Clavel --kit /home/alonso/Documents/clavel-codex-kit --dry-run
```

Para continuar automáticamente tras P0007, ejecutar sin `--only P0007` ni
`--max-tasks 1`. Alonso y Emi coordinan un solo orquestador a la vez sobre main.
No existe bloqueo distribuido entre clones. Cada cambio de turno requiere
publicar los commits y actualizar el otro clon. Los reintentos usan reset/clean;
no mantener trabajo manual sin commit durante la ejecución.
