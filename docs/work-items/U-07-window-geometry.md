# U-07 — Remember secondary-window geometry

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `feat/u-07-window-geometry` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** f1f459c

## Problema
Las ventanas secundarias vuelven a su tamaño y posición iniciales al reabrirlas, aunque el
usuario ya las acomodó para su flujo de análisis.

## Propiedad
- **Puede editar:** `views/base_window_manager.py`, `views/plot/plot_window_manager.py`, `views/main_window.py`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `models/`, `services/`, ViewModels, Mux Detection, HMI/OCR.

## Decisiones cerradas
- Persistir geometría con `saveGeometry`/`restoreGeometry` en las ventanas abiertas por `BaseWindowManager` y `PlotWindowManager`.
- Usar `SessionStateStore` bajo la preferencia `window_geometry`, con clave por tipo de ventana.
- Guardar al cerrar, restaurar antes de mostrar y dejar intacto el tamaño inicial si no hay geometría válida.
- FFT reutilizable y diálogos modales no forman parte de esta tarjeta.

## Trabajo
1. Agregar persistencia reutilizable de geometría al manager base.
2. Conectar todos los managers base activos y las ventanas Plot.
3. Verificar guardar, cerrar y reabrir ventanas en la app real.

## Pruebas
- Suite completa en verde.
- `/verify-ui`: cambiar tamaño/posición de varias ventanas, cerrarlas, reabrirlas y confirmar restauración.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] suite completa: 1024 tests
- [x] UI verificada: CAN Send y Plot restauran tamaño y posición
