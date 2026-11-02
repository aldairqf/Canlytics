# U-03 — Ergonomía de Analyze Data

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `feat/u-03-analyze-data-ergonomics` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** f7007da

## Problema
Analyze Data deja Precompute/Free memory expuestos en la barra, duplica opciones de tiempo en una barra de menú, muestra un guion cuando no hay CAN ID seleccionado y no da escala útil a una serie constante.

## Propiedad
- **Puede editar:** `views/analyze_data_window.py`, `config/ui_text.py`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `viewmodels/analyze_data_viewmodel.py`, `services/analyze_data.py`, Mux Detection, HMI/OCR.

## Decisiones cerradas
- Mover Precompute y Free memory a un menú «⋯» sin cambiar sus acciones.
- Ocultar la barra de menú duplicada; Time Config y Time Filter siguen accesibles desde la toolbar.
- Usar un estado vacío legible sin selección y ampliar el eje Y solo cuando todos los puntos visibles son constantes.

## Trabajo
1. Agrupar acciones de memoria en el menú de opciones.
2. Quitar la barra de menú y el estado vacío de guion.
3. Dar un rango Y útil a las series constantes.

## Pruebas
- Suite completa en verde.
- `/verify-ui`: comprobar menú, estado sin selección y el eje Y para una serie constante.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] suite completa: 1021 tests
- [x] UI verificada: menú, estado vacío, rango constante y restauración de ejes
