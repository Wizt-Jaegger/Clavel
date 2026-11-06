# P0010: recursos temporales para revisión independiente

Alonso trabaja en NixOS. PostgreSQL 17.11, initdb y pg_ctl ya están disponibles
en PATH; este ajuste no instala paquetes ni cambia la configuración del sistema.

Los dos intentos anteriores fueron rechazados porque la instrucción del revisor
prohibía crear cualquier archivo. El revisor registró explícitamente que esa
regla impedía arrancar la fixture de PostgreSQL, aunque las pruebas del autor
habían pasado. Pedir un servicio preexistente no era necesario: la fixture
`tests/integration/conftest.py` crea un clúster efímero en /tmp, con rol y datos
sintéticos, socket Unix privado y sin escucha TCP; lo elimina al terminar.

El [parche incremental del kit](P0010_REVIEW_TEMP_RESOURCES.patch) permite crear
esos recursos aislados durante la revisión y exige CLAVEL_REQUIRE_POSTGRES=1.
El revisor mantiene intactos el código, contrato, estado de tareas e historial
Git. La regla de aceptación exacta y la revisión independiente se conservan.
No se usan las credenciales ni la base configurada en el .env de la aplicación.

Validación previa al reintento:

- Suite existente del kit: 29 passed, con fixtures y dobles sintéticos.
- CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest tests/integration/test_migrations.py -q --tb=short:
  2 passed, 0 skipped en 7.55s, sobre PostgreSQL nativo desechable. La ejecución
  dentro del sandbox falló al iniciar el socket; fuera del sandbox pasó.
- git apply --check del parche incremental: correcto.

Estas pruebas verifican la infraestructura y la mecánica del ajuste. P0010
sigue necesitando su implementación, pruebas específicas y un nuevo veredicto
independiente. El orquestador debe reintentar únicamente P0010 después de pasar
su estado de Blocked a Pending; no se marca Accepted manualmente.

## Resultado del reintento

P0010 **Accepted** por revisión automática independiente el 2026-11-06 a las
19:52:08 UTC. SHA exacto revisado:
`9714d8a03ab5894dfcae48dc695361b2bf7827e4`.

El reintento implementó la revisión `0004_customer_session_schema`, después de
inventario, con sujetos registrados/anónimos, referencias opacas únicas,
sesiones opcionalmente enlazadas y actividad finita y ordenada. La política de
vinculación anónima a registrada continúa separada y Pending. No hubo cambios
OpenAPI ni activación de flujos de identificación o autorización.

- Autor: 83 pruebas PostgreSQL de esquemas/migraciones correctas.
- Orquestador: 494 pruebas y 6 subpruebas correctas; una advertencia de deprecación.
- Revisor independiente: 84 pruebas correctas, 0 omitidas, incluyendo su propia
  comprobación de concurrencia, enlaces inválidos y persistencia anónima.
- Revisor terminó con código 0 y última línea stdout exactamente
  `VERDICT: ACCEPTED`. Solo entonces el orquestador actualizó el estado.

La evidencia verifica mecánica real de PostgreSQL sobre datos sintéticos; no es
aceptación de identidades, datos o servicios de producción. Los registros previos
al ajuste se conservaron en `log/runs/P0010-before-temp-resource-fix/` (ignorados
por Git). No se ejecutaron otras tareas ni se publicaron commits al remoto.
