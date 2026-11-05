# F6-06 — Real-Time offline sincronizado con el cursor

- **Estado:** Hecho
- **Verificación:** suite completa: 1264 tests; revisiones code-reviewer y qt-mvvm-reviewer aprobadas; smoke visual con candump (1150 frames), cinta offline, snapshot, cursor, Next, scrub y reproducción. Capturas revisadas en `%TEMP%\canlytics-f606-verify`.
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-06-offline-realtime` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-02, F6-05
- **Base commit:** `a915e65`
- **Referencias:** [ADR 001](../architecture/decisions/001-streaming-append-delta.md), [ADR 004](../architecture/decisions/004-analysis-context.md)

## Problema

Con un log ya cargado y sin captura en vivo, Real-Time queda vacío (F1-08 deshabilitó
"Confirm in Real-Time" para evitar esa vista vacía). El usuario debe poder inspeccionar
la instantánea de cada ID en el instante del cursor compartido y recorrer el log.

## Propiedad

- **Puede editar:** nuevo `services/offline_realtime.py`, `viewmodels/real_time_analysis_viewmodel.py`, `views/realtime_analysis_window_manager.py`, `views/realtime_analysis_window.py`, `views/main_window.py`, `views/widgets/ribbon_bar.py`, `views/plot/plot_window_manager.py`, `views/candidate_interpretations_window.py`, `views/analyze_data_window.py`, `views/candidate_constraint_search.py`, construcción de `BitActivityWindowManager` y `SignalCoverageWindowManager`, `config/ui_text.py`, pruebas relacionadas, `docs/plan.md`, `CHANGELOG.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** Mux Detection, HMI/OCR, F2-02, cursores globales y lógica de análisis no relacionada.

## Decisiones cerradas

- En modo offline, cada CAN ID muestra el último frame con timestamp menor o igual al cursor global; el `Delta T` corresponde al intervalo con su frame anterior.
- El índice del log se construye una vez y las búsquedas usan búsqueda binaria; mover el cursor no recorre el DataFrame completo.
- La ventana ofrece anterior, reproducir/pausar, siguiente y scrub por timestamps distintos. Frames con el mismo timestamp pertenecen a la misma posición temporal del cursor global y se muestran como una sola instantánea.
- El comportamiento live sigue alimentándose de chunks y no muestra los controles de transporte offline.
- La carga/reemplazo del log reconstruye el índice y Clear lo vacía. La indexación de logs largos se construye en un worker Qt propiedad del ViewModel.

## Trabajo

1. Crear y probar un índice Qt-free que devuelva el último frame por ID en un timestamp.
2. Integrarlo con Real-Time offline, el cursor global y cambios de fuente.
3. Añadir controles de paso, reproducción y posición, con textos localizados.
4. Documentar y verificar el flujo offline y live.

## Pruebas

- Regresión primero: límites antes/después del log, timestamps duplicados, IDs, Delta T y progreso/reemplazo del índice.
- Suite completa verde.
- `/verify-ui`: log candump offline, cursor externo, botones de paso, reproducción/scrub y modo live.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite, revisiones y capturas revisadas
