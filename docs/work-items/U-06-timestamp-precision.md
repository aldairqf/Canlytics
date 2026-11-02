# U-06 — Timestamp precision and column width

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `feat/u-06-timestamp-precision` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** ed8fb7b

## Problema
La tabla principal muestra TS con precisión variable y no ajusta el ancho al cambiar la zona
horaria. Real-Time ya ajusta el ancho, y ambas tablas comparten el delegado de TS.

## Propiedad
- **Puede editar:** `views/table/ts_display_delegate.py`, `views/main_window.py`, `tests/test_ts_display_delegate.py`, `tests/README.md`, `docs/testing.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `views/realtime_analysis_window.py` salvo que la revisión demuestre un hueco, Mux Detection, HMI/OCR.

## Decisiones cerradas
- Todas las columnas TS usan exactamente seis decimales tanto en epoch como en fecha/hora de zona horaria.
- El ancho de TS en la tabla principal se calcula desde el texto que muestra el delegado, al iniciar y al cambiar zona horaria.
- Real-Time conserva su comportamiento de ajuste existente y adopta los seis decimales por el delegado compartido.

## Trabajo
1. Fijar el formato de seis decimales en el delegado compartido.
2. Ajustar el ancho TS de la tabla principal al cambiar el modo horario.
3. Agregar regresiones para formato epoch y con zona horaria.

## Pruebas
- Suite completa en verde.
- `/verify-ui`: comprobar valores TS de seis decimales en tabla principal y Real-Time; cambiar zona horaria y verificar el ancho de TS.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] suite completa: 1024 tests
- [x] UI verificada: seis decimales y ancho TS en principal y Real-Time
