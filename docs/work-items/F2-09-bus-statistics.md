# F2-09 — Estadística de bus

- **Estado:** Hecho
- **Fase:** 2
- **Rama:** `feat/f2-09-bus-statistics` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-02
- **Base commit:** d2b1f6c

## Problema
La captura no muestra la carga estimada del bus ni permite comparar actividad, periodicidad y presencia de CAN IDs mientras se analiza el tráfico.

## Propiedad
- **Puede editar:** `services/bus_statistics.py`, `viewmodels/bus_statistics_viewmodel.py`, `viewmodels/main_window_viewmodel.py`, `views/bus_statistics_window.py`, `views/bus_statistics_window_manager.py`, `views/main_window.py`, `views/widgets/ribbon_bar.py`, `config/defaults.py`, `config/ui_text.py`, `tests/test_bus_statistics.py`, `tests/README.md`, `docs/testing.md`, `docs/architecture/overview.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `services/log_data.py`, `viewmodels/data_viewmodel.py`, `scripts/`, lógica de Mux Detection, HMI/OCR, otras tarjetas.

## Decisiones cerradas
- Los consumidores live usan `chunk_ready` crudo; nunca un watermark de filas del DataFrame acumulado (ADR 001).
- El porcentaje de carga es estimado y solo se muestra con bitrate conocido y un único bus.
- Las tasas cuentan intervalos entre timestamps; si llegan fuera de orden, períodos y jitter se marcan como no confiables sin retener el historial completo.
- Ventana secundaria de instancia única con `Qt.WA_DeleteOnClose`.

## Trabajo
1. Acumular estadísticas O(chunk): fps global y por ID, período mínimo/promedio/máximo, jitter y nuevos/desaparecidos.
2. Mostrar resumen en barra y abrir ventana propia con detalle por ID.
3. Añadir tests del servicio y documentar límites de la estimación.

## Pruebas
- Probar acumulación, períodos, jitter, bitrate, IDs nuevos/desaparecidos y chunks vacíos.
- Suite completa verde.
- `/verify-ui`: abrir la ventana, verificar resumen y tabla con una captura/replay.

## Cierre
- [x] CHANGELOG `## Unreleased`  - [x] fila de `docs/plan.md`  - [x] `docs/bugs.md` si aplica
