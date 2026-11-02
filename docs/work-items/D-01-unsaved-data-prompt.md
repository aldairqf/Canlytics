# D-01 — Aviso de datos de captura sin guardar

- **Estado:** Hecho
- **Fase:** D
- **Rama:** `feature/d-01-unsaved-data-prompt` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 807f3a3

## Problema
Palabras del usuario: "me han reportado que al cerrar el app se pierde el log, no les da ni un
aviso para guardar el log".

Verificado:
- `views/main_window.py:511` `closeEvent` solo pregunta si hay ventanas secundarias abiertas;
  nunca por datos sin guardar.
- `views/main_window.py:389` `_clear_log` → `vm.clear_log()` (`viewmodels/main_window_viewmodel.py:103`)
  borra todo sin confirmar.
- Cargar otro log (`_pick_load_log`, `views/main_window.py:301` → `vm.start_load`) reemplaza
  los datos capturados sin avisar.
- Iniciar una conexión nueva (`connection_vm.start_ssh/start_kvaser/start_replay`): comprueba si
  hoy limpia o agrega a los datos existentes y documenta lo que encuentres; el aviso aplica si
  los datos actuales se van a reemplazar o mezclar.
- Guardado actual: `views/main_window.py:392` `_save_current_log_menu` / `_save_current_log`
  (candump). D-02 lo moverá a un servicio con formatos y worker; aquí se **reutiliza** tal cual.

## Propiedad
- **Puede editar:** `viewmodels/data_viewmodel.py`, `viewmodels/main_window_viewmodel.py`,
  `views/main_window.py`, `config/ui_text.py` (strings nuevos), `config/defaults.py` si hace
  falta, tests en `tests/`, `tests/README.md`, `docs/testing.md`, `docs/plan.md`,
  `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `scripts/` (F2-01 en paralelo), `viewmodels/connection_stream_viewmodel.py`
  salvo una línea imprescindible (justifícala), Mux Detection, HMI/OCR.

## Decisiones cerradas
- **Qué cuenta como "sin guardar":** datos que llegaron por captura o replay (`append_df`) desde
  la última carga, guardado o limpieza. Un log abierto desde archivo y sin datos nuevos **no**
  está sin guardar. El estado vive en el ViewModel (`has_unsaved_capture: bool` + señal de
  cambio), sin Qt de widgets, para poder probarlo.
- Guardar con éxito, cargar un log o limpiar ponen el estado en `False`.
- **Dónde se pregunta** (la vista muestra el diálogo, el VM decide si hace falta):
  - cerrar la app: si hay datos sin guardar → "Guardar / Descartar / Cancelar". Guardar abre el
    diálogo actual de guardado; si el usuario cancela ese diálogo o el guardado falla, **no** se
    cierra. Después sigue la pregunta de ventanas abiertas que ya existe (o combínalas en un
    solo diálogo si queda más claro, pero sin perder ninguno de los dos avisos);
  - Clear: si hay datos sin guardar → "Guardar / Descartar / Cancelar"; si hay datos ya
    guardados → confirmación simple "¿Limpiar los datos?"; si no hay datos, nada;
  - cargar otro log con datos sin guardar → "Guardar / Descartar / Cancelar";
  - iniciar una conexión que vaya a reemplazar o mezclar datos sin guardar → igual.
- Durante una captura en curso, cerrar la app también pregunta (los datos siguen llegando).
- Textos en `get_text()`, en inglés como el resto de la UI, claros y cortos (p. ej. título
  "Unsaved capture", cuerpo "You have N frames captured that are not saved. Save them before
  closing?").
- Nada de esto cambia el formato del guardado (lo hace D-02).

## Trabajo
1. Estado `has_unsaved_capture` en el VM y sus transiciones.
2. Un helper de vista único que muestre el diálogo y devuelva `proceed: bool` (y guarde si se
   pidió), usado por cerrar, Clear, cargar y conectar.
3. Cablear los cuatro puntos.

## Pruebas
- Regresión primero (rojo → verde), sin widgets reales:
  - `append_df` marca sin guardar; cargar log, guardar y limpiar lo desmarcan;
  - un log cargado sin datos nuevos no está sin guardar;
  - la lógica de decisión (p. ej. una función pura `unsaved_prompt_kind(has_data, has_unsaved)`
    → `none | confirm | save_discard_cancel`) cubre los casos.
- Suite completa en verde.
- `/verify-ui` (el orquestador): replay de un log de Fase 02 → cerrar la app pide guardar;
  Cancelar no cierra; Guardar escribe el archivo; log abierto sin captura → cierra sin preguntar.

## Ajustes de la revisión
- El guardado pide primero la ruta; después detiene la captura al cerrar, hace flush,
  toma el snapshot, escribe y marca como guardado sin abrir otro event loop.
- La decisión de nueva sesión se muestra solo al iniciar manualmente SSH, Kvaser o replay;
  permite Guardar, Descartar, Conservar y agregar o Cancelar. Stop y auto-retry no preguntan.
- Normalize confirma antes de recargar un log con captura pendiente; al recargar, limpia el
  estado y el conteo. La carga append no pregunta y no marca frames del archivo como captura.
- Se agregó cobertura de secuencia de guardado con chunks inyectados al elegir la ruta.
- Excepción a la propiedad de archivos: `connection_stream_viewmodel.py` agrega
  `stop_and_drain()` porque `stop()` solo solicita detener el worker y no espera la entrega
  de sus señales `chunk_ready`, causa confirmada del snapshot incompleto.

Verificación revisión: suite completa, 937 tests en 56 archivos. Reproducción de cierre con
replay (`verify_d01b.py`): 1,248 filas en memoria y 1,248 frames guardados; la captura se
detuvo y `has_unsaved_capture` quedó en `False`. `stop_and_drain()` espera el fin del worker y
procesa sus señales pendientes antes de vaciar el timer y tomar el snapshot.

## Cierre
- [x] CHANGELOG `## Unreleased` (sección `### Correcciones`)
- [x] Fila de `docs/plan.md` retirada
- [x] `tests/README.md` y `docs/testing.md` actualizados
