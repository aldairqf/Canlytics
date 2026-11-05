# F6-05 — Cursor global de tiempo y marcadores

- **Estado:** Hecho
- **Verificación:** suite completa: 1252 tests; revisiones code-reviewer y qt-mvvm-reviewer aprobadas; smoke visual con log candump, cursor por tabla/teclado/Diff, Plot normalizado y marcadores. Capturas revisadas en `%TEMP%\canlytics-f605-verify`
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-05-global-time-cursor` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-04, F6-03
- **Base commit:** `fa3f11e`
- **Referencias:** [ADR 004](../architecture/decisions/004-analysis-context.md)

## Problema

Cada herramienta mantiene su propio cursor o ninguno. El tiempo del frame seleccionado en Main o Real-Time no llega al Plot ni al timeline de Diff, y los marcadores ON/OFF de F6-03 no se ven como referencias comunes. El contrato de datos usa timestamps epoch en `TS`; Plot puede normalizar su eje, por lo que el enlace debe convertir el tiempo sin perder la referencia original.

## Propiedad

- **Puede editar:** `viewmodels/main_window_viewmodel.py`, nuevo `viewmodels/time_cursor_viewmodel.py`, `views/main_window.py`, `views/plot/plot_window.py`, `views/plot/plot_window_manager.py`, `views/realtime_analysis_window.py`, `views/realtime_analysis_window_manager.py`, `views/range_diff_window.py`, `views/range_diff_window_manager.py`, `views/widgets/range_timeline.py`, `viewmodels/table_model.py`, `viewmodels/plot_viewmodel.py`, `config/ui_text.py`, pruebas relacionadas, `docs/plan.md`, `CHANGELOG.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** lógica de Mux Detection, HMI/OCR, algoritmos de análisis o rangos A/B de Diff, otras tarjetas.

## Decisiones cerradas

- El estado compartido es un timestamp epoch finito, emitido con origen para evitar ciclos de realimentación.
- La interacción de cursor A en Plot, selección de fila en Main/Real-Time y clic en el timeline de Diff actualizan el mismo tiempo. El cursor B y los rangos A/B de Diff siguen independientes.
- Plot normalizado convierte a tiempo relativo al origen de las series graficadas y vuelve a epoch al recibir.
- Los marcadores persistidos por `EventMarkersViewModel` se muestran como referencias verticales en Plot y Diff y como indicación en tablas. Las ventanas suscriptoras desconectan al cerrarse.
- Ninguna actualización de cursor recorre el DataFrame completo.

## Trabajo

1. Crear el estado compartido e integrarlo al composition root.
2. Sincronizar la selección de Main/Real-Time, cursor A de cada Plot y posición del cursor en el timeline Diff.
3. Dibujar marcadores de eventos en Plot, Diff y filas coincidentes.
4. Cubrir conversión de tiempo, propagación, feedback, marcadores y ciclo de vida; documentar.

## Pruebas

- Regresión primero: propagación entre superficies, ejes normalizados, clic en timeline fuera de las bandas, ciclo de conexión y visibilidad de eventos.
- Suite completa verde.
- `/verify-ui`: mover el cursor desde Main, Real-Time, Plot y Diff; comprobar sincronía en las demás ventanas y marcadores ON/OFF en temas claro y oscuro.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite, revisiones y capturas revisadas
