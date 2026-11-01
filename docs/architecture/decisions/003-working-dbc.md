# 003 — DBC de trabajo editable

**Estado:** Aceptado (2026-11-01). Se implementa en la Fase 4 del plan.

## Contexto
La detección termina en un callejón sin salida: ninguna ventana puede guardar una señal
encontrada como señal DBC. `DbcManager` es de solo lectura. La única salida es un ida y
vuelta por CSV desde Signal Coverage, y ese CSV solo exporta lo que **ya** está en un DBC.

El usuario hace ingeniería inversa, y el DBC que carga le sirve solo de ayuda.

## Decisión
- `services/working_dbc.py` (Qt-free) mantiene un `cantools.Database` editable: crear, editar y eliminar mensajes y señales, validar solapes y exportar a `.dbc`.
- Se persiste en `.canlytics_state/working.dbc` y se registra en `DbcManager` como una entrada más. Así decodifica al instante en la tabla, en Real-Time y en Plot.
- La acción "Guardar como señal" se abre prellenada desde el contexto de análisis (ADR 004). Está disponible en Candidate, Diff, Analyze, Plot y en la línea decodificada de la tabla.
- Los DBC cargados siguen siendo de solo lectura.

## Consecuencias
- Reusa la construcción de `Message`/`Signal`/mux de `services/pgn_csv_to_dbc.py`, que ya está probada.
- Necesita un test de ida y vuelta: crear una señal, exportar, recargar y comprobar que decodifica igual.
