# 004 — Contexto de análisis compartido

**Estado:** Aceptado (2026-11-01). Se implementa en la Fase 3 del plan.

## Contexto
Hoy cada ventana reimplementa sus conceptos por su cuenta. Hay:
- 4 lugares distintos que guardan el rango de tiempo;
- 3 copias de la configuración de mux, ninguna persistida;
- 5 lógicas distintas de "qué cambió";
- 4 selectores de CAN ID.

Además, al pasar de una herramienta a otra se pierde información:
- Diff → Candidate pasa solo el ID, sin el byte ni el rango A/B.
- Analyze, Constraint Search y Plot no tienen salida hacia ninguna otra herramienta.

## Decisión
- `models/analysis_context.py` define `AnalysisContext`: CAN ID, bytes o bits, rango de tiempo o rangos A/B, caso de mux y ventana de origen.
- `AnalysisContextViewModel` vive en el composition root.
- Un menú común "Enviar a…" reemplaza a `show_add_to_plot_menu`. Sus destinos son Plot, Candidate, Diff, Analyze, Real-Time y Working DBC.
- Una sola configuración de mux, persistida.
- Un solo componente de rango de tiempo.
- Una sola taxonomía de cambio, sobre `services/range_diff.py` (`observe_byte`, `classify_byte`, `LiveByteAccumulator`).

## Consecuencias
- Las ventanas se encadenan sin fusionarse: cada una sigue siendo independiente y la evidencia viaja con un clic.
- La migración toca muchas vistas. Se hace ventana por ventana, cada una en su tarjeta.
