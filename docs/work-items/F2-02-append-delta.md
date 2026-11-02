# F2-02 — Contrato incremental de append y CAN IDs

- **Estado:** Hecho
- **Fase:** 2
- **Rama:** `feature/f2-02-append-delta` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-01
- **Base commit:** a6c36ca

## Problema
`LogDataViewModel._flush_pending()` emite el DataFrame completo y `_emit_ids()` vuelve a
calcular `unique()` sobre toda la historia en cada flush. ADR 001 pide un delta crudo cuando
el append respeta el orden y reemplazo completo cuando hay que reordenar.

## Propiedad
- **Puede editar:** `viewmodels/data_viewmodel.py`, `services/log_data.py`,
  `tests/test_data_viewmodel.py`, `tests/test_log_data.py`, `tests/README.md`,
  `docs/testing.md`, `docs/architecture/overview.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `scripts/` (F2-01), `services/` salvo `log_data.py`, otros ViewModels,
  lógica de Mux Detection, HMI/OCR.

## Decisiones cerradas
- Añadir `rows_appended(delta_df, new_ids)` para appends en orden; `delta_df` usa el mismo
  contrato de TS normalizado que el DataFrame acumulado.
- Si el chunk llega fuera de orden, emitir `dataframe_replaced` con el resultado reordenado y
  no emitir `rows_appended`.
- Mantener un set incremental de CAN IDs y reconstruir la lista ordenada solo cuando aparecen
  IDs nuevos o el DataFrame completo se reemplaza.
- Conservar `dataframe_changed(df_completo)` por compatibilidad hasta que las tarjetas siguientes
  migren consumidores.

## Trabajo
1. Exponer la comprobación de append en orden usada por `merge_frames`.
2. Emitir deltas normalizados y reemplazos en los caminos de captura y append de logs.
3. Mantener el índice de IDs sin consultar el DataFrame acumulado durante flushes normales.
4. Añadir pruebas de delta, IDs nuevos, orden, normalize y reemplazo.

## Pruebas
- Regresión primero: acumulación de deltas == DataFrame final, IDs nuevos incrementales,
  append fuera de orden reemplaza y normalize mantiene TS coherente.
- Suite completa verde.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/testing.md` y `tests/README.md`
