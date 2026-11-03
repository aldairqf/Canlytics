# F5-01 — Separar DbcManager de Qt

- **Estado:** Hecho
- **Fase:** 5 de `docs/plan.md`
- **Rama:** `refactor/f5-01-dbc-manager-layering` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F4-01, F4-02
- **Base commit:** `d946ddd`

## Problema

`services/dbc_manager.py` importa `QObject` y `Signal` aunque contiene la lógica de cargar,
ordenar, resolver y decodificar DBC. Esto impide usar el servicio desde procesos Qt-free y
mezcla estado de dominio con notificaciones de interfaz.

## Propiedad

- **Puede editar:** `services/dbc_manager.py`, `viewmodels/dbc_manager_viewmodel.py`,
  `viewmodels/main_window_viewmodel.py`, `viewmodels/interpretation_viewmodel.py`,
  `viewmodels/table_model.py`, `viewmodels/dbc_load_worker.py`, `services/session_state.py`,
  `services/dbc_loader_cli.py`, `views/main_window_view.py`, `views/dbc/dbc_manager_dialog.py`,
  `views/plot/plot_window_manager.py`, `views/signal/tabs/decode_tab.py`,
  `views/realtime_analysis_window.py`, `views/realtime_analysis_window_manager.py`,
  `tests/test_dbc_manager.py`, `tests/test_dbc_manager_viewmodel.py`, `tests/test_fixtures_real.py`,
  `tests/test_real_bam_decode.py`, `tests/test_range_diff.py`, `tests/test_signal_coverage.py`,
  `tests/README.md`, `docs/testing.md`, `docs/architecture/overview.md`, `docs/plan.md`,
  `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** cambios de comportamiento de decode, matching J1939/BAM, DBC de trabajo,
  CAN Send, Mux Detection, HMI/OCR, ni vistas fuera de cambios de anotación/import.

## Decisiones cerradas

- `services/dbc_manager.py::DbcManager` queda Qt-free y conserva íntegros sus resultados y cachés.
- `viewmodels/dbc_manager_viewmodel.py::DbcManagerViewModel` adapta notificaciones Qt para la app.
- Los workers CLI/carga y `SessionStateStore` usan el servicio; composition root, otros ViewModels
  y vistas que escuchan cambios usan el adaptador.
- No cambiar firma observable de métodos ni semántica de los DBC.

## Trabajo

1. Extraer Qt de `DbcManager` sin alterar la API de operaciones.
2. Añadir el adaptador QObject con `entries_changed` y usarlo desde el grafo de la app.
3. Mantener workers/servicios Qt-free y actualizar tipos/imports de consumidores.
4. Cubrir que la capa service importa sin Qt y que el adaptador notifica las mutaciones.

## Pruebas

- Caracterización de `tests/test_dbc_manager.py`, fixtures y decode J1939/BAM sin cambios.
- Test del adaptador y verificación de import Qt-free del servicio.
- Suite completa en verde: 1113 tests.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` cerrada
- [x] `docs/bugs.md` revisado; sin cambios aplicables
- [x] Suite completa en verde
