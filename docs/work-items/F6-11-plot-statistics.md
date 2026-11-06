# F6-11 — Estadísticas entre cursores y modo XY integrado

- **Estado:** Hecho
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-11-plot-statistics` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-06, U-10
- **Base commit:** `3db9eff`
- **Arquitectura:** [overview](../architecture/overview.md), [ADR 001](../architecture/decisions/001-streaming-append-delta.md)

## Problema

Plot ya tiene cursores A/B y estadísticas configurables, y U-10 ofrece un XY Plot en una ventana aparte. F6-11 pide hacer más eficiente el cálculo de estadísticas del intervalo y ofrecer el modo XY dentro de la ventana principal de Plot.

## Propiedad

- **Puede editar:** `utils/plot_statistics.py`, `views/plot/cursor_controller.py`, `views/plot/xy_window.py`, `views/plot/plot_window.py`, `views/plot/plot_ribbon.py`, `config/ui_text.py`, pruebas relacionadas, `docs/plan.md`, `CHANGELOG.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** servicios de streaming, lógicas congeladas de Mux Detection y HMI/OCR.

## Decisiones cerradas

- Conservar el XY Plot independiente de U-10 y reutilizar sus controles, alineación y exportación.
- El modo XY de Plot muestra series ya añadidas al plot; no reconstruye datos en cada flush y se refresca a petición.
- Las estadísticas usan muestras dentro del intervalo inclusivo entre A y B; Δ es el valor en B menos el de A.

## Trabajo

1. Añadir el modo XY integrado a la ventana principal, conservando la ventana U-10.
2. Usar búsqueda binaria para delimitar las muestras del intervalo de cursor antes de calcular media, mínimo, máximo y conteo.
3. Cubrir el modo XY y estadísticas de intervalo con pruebas y documentar el flujo.

## Pruebas

- Regresión primero para extremos inclusivos, rango vacío y arrays con timestamps ordenados.
- Suite completa verde.
- Verificar en la app real el cambio entre plot temporal y XY, refresco/exportación y las estadísticas con cursores A/B.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` sin cambios (no aplica)
- [x] Suite completa: 1307 tests en verde
- [x] Revisiones code-reviewer y qt-mvvm-reviewer
- [x] Verificación UI con capturas revisadas
