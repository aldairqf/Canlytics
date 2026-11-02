# U-10 — Ventana XY

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `feat/u-10-xy-window` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-06 no comparte el renderer
- **Base commit:** a1dcc00

## Problema
El plot existente representa señales contra tiempo. Para descubrir relaciones entre señales hace falta comparar una contra otra.

## Propiedad
- **Puede editar:** `services/xy_plot.py`, `viewmodels/plot_viewmodel.py`, `views/plot/plot_window.py`, `views/plot/plot_ribbon.py`, `views/plot/xy_window.py`, `config/ui_text.py`, tests del servicio, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** renderer del plot, Mux Detection, HMI/OCR.

## Decisiones cerradas
- XY se abre desde un Plot existente y ofrece las señales crudas/DBC, BAM/J1939, candidatas y derivadas añadidas a ese plot.
- Cada muestra X se alinea con la muestra Y más reciente cuyo timestamp sea menor o igual (as-of hacia atrás).
- El rango selecciona timestamps de X; color por tiempo para mostrar la progresión.
- XY trabaja sobre una instantánea: el usuario pulsa Refresh para incorporar chunks o señales nuevos, sin recalcular todo el historial en cada flush.

## Trabajo
1. Exponer series completas decodificadas por el PlotViewModel.
2. Añadir ventana XY independiente con selección X/Y, rango temporal y exportación CSV.
3. Abrirla desde la pestaña Tools de Plot.

## Pruebas
- Casos de alineación as-of, rango, datos vacíos y exportación CSV.
- Suite completa en verde y `/verify-ui` con captura revisada.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] suite completa (1035 tests) y UI verificada
