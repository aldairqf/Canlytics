# F5-03 — Las vistas delegan el acceso a servicios

- **Estado:** Hecho
- **Fase:** 5 de `docs/plan.md`
- **Rama:** `refactor/f5-03-view-services` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-02
- **Base commit:** `2fe1bec`
- **Arquitectura:** [overview](../architecture/overview.md)

## Problema

`views/settings/connection_dialog.py` define `_SshTimePollThread`, que abre SSH y parsea
candump desde una vista. `views/plot/plot_window.py` llama directamente a `compute_fft`,
`export_plot_csv` y `export_plot_image`. Esto incumple la regla de que las vistas no llaman
servicios y que el trabajo de I/O y análisis lo poseen ViewModels/servicios.

## Propiedad

- **Puede editar:** `services/ssh_time_poll.py`, `viewmodels/ssh_time_poll_viewmodel.py`,
  `viewmodels/plot_viewmodel.py`, `views/settings/connection_dialog.py`,
  `views/plot/plot_window.py`, tests de esos ViewModels/servicios, `docs/architecture/overview.md`,
  `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** otros servicios de conexión, `services/fft_analysis.py`,
  `services/plot_exporter.py`, lógica Mux Detection, HMI/OCR, otras tarjetas.

## Decisiones cerradas

- Las vistas conservan diálogos, widgets y eventos de usuario; las llamadas a servicios pasan por ViewModels.
- El polling SSH debe mantener cancelación pronta al cerrar el diálogo y no bloquear el hilo UI.
- El resultado y los errores de exportación/FFT deben conservar el comportamiento visible actual.
- Los servicios se mantienen Qt-free y las ventanas conservan su ciclo de vida existente.

## Trabajo

1. Mover el polling SSH a un servicio Qt-free y gestionar su worker desde un ViewModel dedicado.
2. Delegar FFT y exportación del plot en `PlotViewModel`.
3. Añadir pruebas de cancelación, delegación y propagación de errores/resultados.

## Pruebas

- Imports de servicios nuevos sin Qt ni hardware.
- Suite completa verde y smoke de sincronización SSH, FFT y export del plot.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa en verde
- [x] Capturas de los flujos visibles revisadas
