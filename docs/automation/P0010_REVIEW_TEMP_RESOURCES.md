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
