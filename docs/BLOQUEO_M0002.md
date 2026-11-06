# M0002 — dependencia pendiente y propuesta de reasignación

Fecha: 2026-11-06 (UTC). Rama: `main`.
Revisión de referencia: `6272e867183b1d07b66a500c8f0055586e1471d2`.
Responsable actual en la planificación: Manu. Responsable propuesto: Emi.
Estado de esta comprobación: **Blocked**; no constituye aceptación de M0002.

La propuesta recibida mantiene el ID M0002 y la revisión independiente del
contrato como requisito de P0007. Alonso conserva el contrato y el backend;
Emi revisaría su consumo por frontend mediante OpenAPI y mocks sintéticos de
éxito, vacío y error, incluidos 401/403. Las credenciales y la autorización
real siguen siendo responsabilidad del backend.

La fila M0002 de la planificación externa declara `M0001, P0006` como
prerrequisitos. P0006 figura Accepted en `log/STATUS.md`, SHA `8a031e9`.
No hay una fila M0001 aceptada ni `log/EXTERNAL_ACCEPTED.txt` en este repo.
Tampoco hay una tarea M0002 importada en `INDEX.md` o `tasks/`.
Se detiene la revisión formal conforme a la regla de prerrequisitos de AGENTS.md.
No se abrieron los prompts individuales excluidos por el usuario.

Alonso y Emi deben acordar si M0001 sigue siendo necesario para esta revisión
del contrato. Si lo es, falta su aceptación atribuible. Si no lo es, deben
registrar expresamente el cambio de dependencia junto con la reasignación;
no basta cambiar el nombre del responsable. Después corresponde fijar el SHA
para CP0, importar el alcance autorizado y preparar la evidencia para Emi.

En el orquestador inspeccionado, `Ctx.ready()` consulta las dependencias que
no empiezan por P en `log/EXTERNAL_ACCEPTED.txt`. Una futura aceptación de
M0002 debe tener revisor, SHA exacto, fecha y evidencia; además debe publicarse
el ID externo para que P0007 pueda reconocerla. `repair_status()` conserva
solo tareas P del índice del kit, por lo que una fila M0002 añadida únicamente
a STATUS.md no es un registro duradero con ese script.

La inspección documental puede continuar; la revisión formal y la firma de
M0002 quedan pendientes. P0007 mantiene M0002 como requisito. E0001 ya figura
Accepted, con evidencia en `docs/REVISION_E0001.md`.
