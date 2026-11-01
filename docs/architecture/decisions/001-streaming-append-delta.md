# 001 — Streaming con contrato append-delta

**Estado:** Aceptado (2026-11-01)

## Contexto
Durante una captura, `LogDataViewModel` emite el DataFrame **completo** acumulado en cada
flush (100 ms), y varios consumidores recalculan sobre todo el df:
- `unique()` de IDs (`data_viewmodel._emit_ids`, `analyze_data.sorted_can_ids`);
- `_same_row_identity` en `TableModel`;
- el filtro de tabla, que nunca hace rechunk;
- Matrix Live;
- un re-sort completo en `merge_frames` cuando un chunk llega desordenado.

El costo por flush crece lineal con la duración de la captura. Ese es el "se pone lento a
los ~10 min y solo Clear lo arregla" que reportó el usuario. Medido con
`scripts/bench_stream.py` sobre el perfil real (900 fps, 40 IDs), en 4 etapas:
4.3 ms/flush a los 5 min, 12.4 ms a los 10 min, 21 ms a los 15 min y 30.2 ms a los 20 min.
El filtro de tabla es el que más crece (16.7 ms a los 20 min), porque nunca hace rechunk.
Estos números no incluyen `TableModel`, el repintado, Real-Time ni Plot.

## Decisión
- `LogDataViewModel` emite además `rows_appended(delta_df, new_ids)` cuando el append respeta el orden de TS. Cuando hay que re-ordenar, emite `dataframe_replaced`.
- Todo consumidor mantiene su estado incremental a partir del delta o del chunk crudo de `chunk_ready`. **Nunca** usa un watermark por cantidad de filas sobre el df acumulado.
- `merge_frames` re-ordena solo la cola afectada (desde el TS mínimo del chunk), nunca el df completo.
- Los consumidores sin ventana abierta no se conectan.

## Consecuencias
- El costo por flush queda plano (meta: <5 ms con el perfil real), sin importar la duración.
- Cada consumidor incremental necesita un test de invariante: la acumulación del delta da lo mismo que recalcular completo.
- Aparecen más señales en el grafo. Se documentan en `docs/architecture/overview.md`.
