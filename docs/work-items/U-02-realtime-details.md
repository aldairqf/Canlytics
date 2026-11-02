# U-02 — Panel Details de Real-Time

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `feat/u-02-realtime-details` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 95e87e2

## Problema
La tabla de valores únicos tiene dos filas y repite B0–B7 debajo de sus propios encabezados; la etiqueta `Period [s]` está hardcodeada.

## Propiedad
- **Puede editar:** `views/realtime_analysis_window.py`, `config/ui_text.py`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `viewmodels/real_time_analysis_viewmodel.py`, Mux Detection, HMI/OCR.

## Decisiones cerradas
- Mantener B0–B7 como encabezados de columna y dejar una sola fila de valores.
- Obtener la etiqueta del período con `get_text()`.

## Trabajo
1. Cambiar la tabla de valores únicos a una fila por ocho columnas.
2. Localizar el texto del resumen de período.

## Pruebas
- Suite completa en verde.
- `/verify-ui`: abrir Real-Time y comprobar que Details muestra una fila de valores bajo B0–B7.

## Cierre
- [x] CHANGELOG `## Unreleased`  - [x] fila de `docs/plan.md`
