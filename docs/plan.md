# Plan — Canlytics

Este es el **único plan activo** y contiene **solo lo pendiente**. Al cerrar un ítem, se borra su
fila y se agrega su línea al `CHANGELOG.md` (en `## Unreleased`) **en el mismo commit**.
Cada ítem en curso tiene su tarjeta en `docs/work-items/<ID>-<slug>.md`. El cómo se trabaja
está en [operations/orquestacion.md](operations/orquestacion.md). La historia anterior está
en [archive/roadmap-2026-07.md](archive/roadmap-2026-07.md).

**Norte del producto:** ingeniería inversa de señales CAN, offline y en vivo. Una señal
encontrada tiene que poder recorrer todo el camino: detectar → confirmar → nombrar →
guardar en el DBC de trabajo → plotear, sin perder contexto entre ventanas. Evidencia y
diagnóstico: [review/2026-11-functional-review.md](review/2026-11-functional-review.md).

Leyenda de esfuerzo: 🟢 bajo · 🟡 medio · 🔴 alto.

## Fase 0 — Repo, docs y agentes

| ID | Trabajo | Esfuerzo |
|---|---|---|
| F0-03 | `tests/README.md` desactualizado: actualizar el conteo y el mapa de cobertura | 🟢 |

## Fase 1 — Fixes de alto impacto (rama `fix/…` por ítem)

| ID | Trabajo | Esfuerzo |
|---|---|---|
| F1-08 | "Confirm in Real-Time" offline abre una ventana vacía: deshabilitar la acción o explicarlo con un mensaje | 🟢 |

## Fase 2 — Streaming O(chunk) ([ADR 001](architecture/decisions/001-streaming-append-delta.md), [ADR 002](architecture/decisions/002-no-ram-cap.md))

| ID | Trabajo | Esfuerzo |
|---|---|---|
| F2-01 | Extender `scripts/bench_stream.py` (línea base actual: 4.3 → 30.2 ms/flush entre los 5 y los 20 min) a `TableModel`, Real-Time y Plot. Meta: costo plano por debajo de 5 ms | 🟢 |
| F2-02 | Señal `rows_appended(delta, new_ids)`; conjunto de IDs incremental (`_emit_ids`, `sorted_can_ids`) | 🟡 |
| F2-03 | `merge_frames` re-ordena solo la cola cuando un chunk llega desordenado | 🟡 |
| F2-04 | `IncrementalTableFilter` hace rechunk periódico; `TableModel.append_rows(delta)` sin `_same_row_identity` ni `dataChanged` global | 🟡 |
| F2-05 | Matrix Live de Analyze: evaluar sobre el delta, no re-filtrar el df completo por ID | 🟡 |
| F2-06 | Plot: derivados incrementales (`align_incremental`, detalle en el CLAUDE.md archivado § "Real-time plot — Incremental update") | 🔴 |
| F2-07 | Guardián de memoria: RAM, frames y fps en la barra de estado; aviso con umbral; grabación continua a disco | 🟡 |

## Fase 3 — Contexto de análisis y conceptos unificados ([ADR 004](architecture/decisions/004-analysis-context.md))

| ID | Trabajo | Esfuerzo |
|---|---|---|
| F3-01 | `AnalysisContext` + `AnalysisContextViewModel` + menú común "Enviar a…" | 🟡 |
| F3-02 | Diff → Candidate con ID + bytes + rango; Candidate busca en ese rango | 🟡 |
| F3-03 | Configuración de mux única y persistida (Real-Time, Analyze, Candidate, Diff) | 🟡 |
| F3-04 | Un solo componente y estado de rango de tiempo (hoy hay 4) | 🟡 |
| F3-05 | Una sola taxonomía de "qué cambió" sobre `services/range_diff.py` (hoy hay 5) | 🔴 |
| F3-06 | `CanIdPanelWidget` como selector único de CAN ID; buscador global (Ctrl+F) para saltar a un ID | 🟡 |
| F3-07 | Salidas para Analyze Data, Constraint Search y Plot (hoy son callejones sin salida) | 🟡 |

## Fase 4 — DBC de trabajo ([ADR 003](architecture/decisions/003-working-dbc.md))

| ID | Trabajo | Esfuerzo |
|---|---|---|
| F4-01 | `services/working_dbc.py` (Qt-free): CRUD de mensajes y señales, validación de solapes, export `.dbc` + test de ida y vuelta | 🟡 |
| F4-02 | Registro en `DbcManager` y persistencia en `.canlytics_state/working.dbc` | 🟢 |
| F4-03 | Diálogo "Guardar como señal" prellenado desde el contexto, en Candidate, Diff, Analyze, Plot y la tabla | 🟡 |
| F4-04 | Ventana "Working DBC": listar, editar, exportar | 🟡 |

## Fase 5 — Deuda de arquitectura (sin cambio de comportamiento)

| ID | Trabajo | Esfuerzo |
|---|---|---|
| F5-01 | `DbcManager` Qt-free + adaptador `QObject` en `viewmodels/` | 🟡 |
| F5-02 | `CanSource` `Protocol` (SSH, Kvaser, replay); la lógica de probe y los loops pasan a `services/` | 🔴 |
| F5-03 | Las vistas dejan de llamar servicios directamente (`_SshTimePollThread`, FFT, export del plot) | 🟡 |
| F5-04 | Encadenar `candidate_interpretations_vm.shutdown()`; mover `set_normalize` a un worker | 🟢 |
| F5-05 | Borrar código muerto (con confirmación): `PipelineBuilder`, `can_frame_formatter.py`, `candump_parser.py` | 🟢 |
| F5-06 | i18n de strings hardcodeados; `from __future__ import annotations` donde falta | 🟢 |
| F5-07 | Migración de tokens de tema (colores hardcodeados en vistas); pase de accesibilidad | 🟡 |

## Backlog (sin fecha; no se toca sin pedido explícito)

| Trabajo | Condición para retomarlo |
|---|---|
| Mux Detection: reactivar o consolidar con Candidate | El usuario lo pide (lógica congelada) |
| HMI Video OCR + ID1 (correlación OCR ↔ señal detectada) | El usuario descongela OCR |
| Constraint Search: persistir precisión y tolerancia | Junto con F3-07 |
| Plot y diálogos: strings duplicados del menú oculto | Junto con F5-06 |
