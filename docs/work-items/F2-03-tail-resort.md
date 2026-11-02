# F2-03 — Reordenar solo la cola afectada

- **Estado:** Hecho
- **Fase:** 2
- **Rama:** `perf/f2-03-tail-resort` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-02
- **Base commit:** 1152224

## Problema
Cuando un chunk llega con timestamps anteriores al final del DataFrame acumulado,
`services/log_data.py::merge_frames` concatena y ordena todas las filas. En capturas largas,
la parte anterior al primer timestamp nuevo ya está ordenada y no requiere trabajo.

## Propiedad
- **Puede editar:** `services/log_data.py`, `tests/test_log_data.py`, `tests/README.md`,
  `docs/testing.md`, `docs/architecture/overview.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** ViewModels, `scripts/`, `TableModel`, lógica de Mux Detection, HMI/OCR.

## Decisiones cerradas
- La base de `merge_frames` se considera ordenada por `TS`.
- Para un chunk que obliga a reordenar, conservar el prefijo de la base anterior al mínimo TS
  entrante y ordenar solo la cola afectada junto con el chunk.
- Respetar `rechunk`: cuando es falso, no copiar/rechunkear todo el resultado; cuando es verdadero,
  consolidar el resultado como solicita el caller.
- Si el chunk llega antes del primer timestamp de la base, la cola afectada puede ser toda la base.

## Trabajo
1. Añadir regresiones para insertar chunks al inicio, en medio, al final con orden interno roto,
   y para timestamps duplicados y normalización.
2. Reemplazar el sort global de `merge_frames` por búsqueda del inicio de la cola afectada y sort local.
3. Documentar el comportamiento y cerrar la fila del plan.

## Pruebas
- La salida conserva todas las filas en orden temporal y coincide con el sort de referencia.
- La ruta ordenada mantiene su comportamiento de rechunk existente; la ruta desordenada respeta
  el parámetro `rechunk`.
- Suite completa verde.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/testing.md` y `tests/README.md`
