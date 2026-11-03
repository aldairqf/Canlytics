# F5-04 — Cerrar Candidate y normalizar fuera del hilo UI

- **Estado:** Hecho
- **Fase:** 5 de `docs/plan.md`
- **Rama:** `refactor/f5-04-shutdown-normalize` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-02
- **Base commit:** `74da65c`
- **Arquitectura:** [overview](../architecture/overview.md)

## Problema

`MainWindowViewModel.shutdown()` no encadena `candidate_interpretations_vm.shutdown()`, aunque
la ventana puede mantener una recalculación activa. Además, `_apply_normalize()` llama
sincrónicamente a `LogDataViewModel.set_normalize()`, que vuelve a parsear el log en el hilo UI.

## Propiedad

- **Puede editar:** `viewmodels/main_window_viewmodel.py`, `viewmodels/data_viewmodel.py`,
  `views/main_window.py`, `tests/test_unsaved_capture.py`, `tests/test_time_range_viewmodel.py`,
  `docs/architecture/overview.md`, `docs/plan.md`, `docs/testing.md`,
  `tests/README.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** otras vistas, otros servicios/ViewModels, lógica Mux Detection, HMI/OCR,
  otras tarjetas.

## Decisiones cerradas

- Shutdown espera el cierre del worker de Candidate antes de liberar el composition root.
- La lectura del log normalizado ocurre en un `QThread`; las mutaciones del modelo y señales de
  datos se aplican de regreso en el hilo UI.
- Un resultado de normalización obsoleto no debe reemplazar un log o datos que cambiaron mientras
  el worker estaba activo.
- El estado de progreso/error se publica por señales de ViewModel, sin llamadas de vista a servicios.

## Trabajo

1. Encadenar `candidate_interpretations_vm.shutdown()` en el cierre de `MainWindowViewModel`.
2. Ejecutar la carga normalizada fuera del hilo UI y aplicar el resultado de forma segura.
3. Caracterizar shutdown, error, reemplazo de log concurrente y normalización completada.

## Pruebas

- Verificar que `CANLog.load()` corre fuera del hilo UI y que las señales/modelo se actualizan en UI.
- Suite completa verde; el flujo de normalización conserva el estado del log.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa en verde
- [x] Estado de la ventana y normalización revisados en app
