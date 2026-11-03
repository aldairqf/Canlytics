# F4-04 — Ventana Working DBC

- **Estado:** Hecho
- **Fase:** 4 de `docs/plan.md`
- **Rama:** `feature/f4-04-working-dbc-window` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F4-01, F4-02, F4-03
- **Base commit:** `616ba20`
- **ADR:** [003](../architecture/decisions/003-working-dbc.md)

## Problema

Working DBC acepta señales desde las herramientas de análisis, pero no ofrece una forma de
revisar, corregir o exportar el resultado. `MainWindowViewModel.save_working_signal()` ya
persiste altas; falta una UI para administrar el contenido.

## Propiedad

- **Puede editar:** `views/dbc/working_dbc_dialog.py`, `views/main_window.py`,
  `views/widgets/ribbon_bar.py`, `views/menu/main_menu_factory.py`,
  `viewmodels/main_window_viewmodel.py`, `config/ui_text.py`,
  `tests/test_working_dbc_persistence.py`,
  `docs/plan.md`, `docs/architecture/overview.md`, `docs/ui-design.md`,
  `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `services/working_dbc.py`, `services/dbc_manager.py`, MCP,
  Mux Detection, HMI/OCR, ni otras tarjetas.

## Decisiones cerradas

- La vista solicita las operaciones al ViewModel y no importa servicios.
- La ventana permite inspeccionar, agregar, editar y eliminar mensajes/señales y exportar
  una copia `.dbc`; la persistencia canónica sigue en `.canlytics_state/working.dbc`.
- Los cambios se validan con `WorkingDbc` y se persisten antes de confirmar éxito.

## Trabajo

1. Exponer operaciones de administración en `MainWindowViewModel`.
2. Añadir una ventana accesible desde el ribbon y el menú oculto para administrar Working DBC.
3. Cubrir el contrato del ViewModel y verificar la UI con capturas.

## Pruebas

- Regresiones de agregar/editar/eliminar y exportar mediante ViewModel.
- Suite completa verde.
- `/verify-ui`: inspeccionar lista, editar y exportar en la ventana; revisar capturas.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa en verde (1126 tests)
- [x] Capturas de lista, edición y exportación revisadas
