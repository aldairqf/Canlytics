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

**Meta 2026-11:** llevar Canlytics al nivel de un banco de trabajo profesional de análisis CAN
(trace, estadística, cursores, formatos) y superarlo en lo que ninguno resuelve bien: descubrir
señales sin DBC. Orden de las fases para no rehacer trabajo: la base (Fases 2–5) primero; las
funciones nuevas (Fases 6–7) se apoyan en ella. El pulido UX (Fase U) corre en paralelo con la
Fase 2 porque toca vistas que la Fase 2 no reescribe.

**Criterio:** primero lo simple que el usuario siente (no perder datos, formatos estándar,
ergonomía); nada de complejidad sin un uso concreto. Lo grande y especulativo vive en el backlog.

## Fase D — No perder datos (prioridad; antes del resto de la Fase 2)

| ID | Trabajo | Esfuerzo |
|---|---|---|
| D-01 | Aviso de datos sin guardar: al cerrar la app, limpiar, cargar otro log o iniciar una conexión nueva con datos de captura sin guardar, preguntar Guardar / Descartar / Cancelar. "Clear" pide confirmación | 🟢 |
| D-02 | Guardar y exportar en formatos estándar: candump, ASC, BLF, TRC y CSV (vía `python-can` `can.io`) en un servicio Qt-free; el guardado corre en un worker con % y ETA (hoy recorre el df fila por fila en el hilo de la UI, `views/main_window.py:410`); guardar todo, lo filtrado o un rango de tiempo | 🟡 |
| D-03 | Grabación continua: mientras hay captura, cada chunk se escribe a un archivo (carpeta configurable, nombre con fecha y fuente, formato de D-02) en un hilo propio; indicador "● Grabando · archivo · MB" en la barra de estado; si la app se cerró de golpe, al abrirla ofrece recuperar la última grabación. Con grabación activa, el aviso de D-01 dice dónde quedó el archivo | 🟡 |

Leyenda de esfuerzo: 🟢 bajo · 🟡 medio · 🔴 alto.

## Fase 0 — Repo, docs y agentes

| ID | Trabajo | Esfuerzo |
|---|---|---|
| F0-03 | `tests/README.md` desactualizado: actualizar el conteo y el mapa de cobertura | 🟢 |

## Fase 2 — Streaming O(chunk) ([ADR 001](architecture/decisions/001-streaming-append-delta.md), [ADR 002](architecture/decisions/002-no-ram-cap.md))

| ID | Trabajo | Esfuerzo |
|---|---|---|
| F2-01 | Extender `scripts/bench_stream.py` (línea base actual: 4.3 → 30.2 ms/flush entre los 5 y los 20 min) a `TableModel`, Real-Time y Plot. Meta: costo plano por debajo de 5 ms | 🟢 |
| F2-02 | Señal `rows_appended(delta, new_ids)`; conjunto de IDs incremental (`_emit_ids`, `sorted_can_ids`) | 🟡 |
| F2-03 | `merge_frames` re-ordena solo la cola cuando un chunk llega desordenado | 🟡 |
| F2-04 | `IncrementalTableFilter` hace rechunk periódico; `TableModel.append_rows(delta)` sin `_same_row_identity` ni `dataChanged` global | 🟡 |
| F2-05 | Matrix Live de Analyze: evaluar sobre el delta, no re-filtrar el df completo por ID | 🟡 |
| F2-06 | Plot: derivados incrementales (`align_incremental`, detalle en el CLAUDE.md archivado § "Real-time plot — Incremental update") | 🔴 |
| F2-07 | Guardián de memoria y barra de estado de medición: conexión (con color), fps, frames, RAM, DBC activo, filtro de tiempo y zona horaria siempre visibles; aviso con umbral (la grabación a disco es D-03) | 🟡 |
| F2-08 | Abrir logs en ASC, BLF, TRC y CSV además de candump y Kvaser (lectura con el mismo servicio de D-02) | 🟢 |
| F2-09 | Estadística de bus: carga % (con el bitrate de la conexión), fps por ID, período mín/prom/máx y jitter, IDs nuevos o desaparecidos; ventana propia + resumen en la barra de estado. Sale del delta de F2-02 | 🟡 |

## Fase U — Pulido UX rápido (en paralelo con la Fase 2; cada ítem ≤ 1 día)

| ID | Trabajo | Esfuerzo |
|---|---|---|
| U-01 | Real-Time: mostrar la columna Delta T (hoy oculta en `_hide_realtime_columns`); separar ajustes (Refresh Interval, Highlight Hold → menú "Opciones") del estado (barra de estado propia de la ventana) | 🟢 |
| U-02 | Real-Time, panel Details: tabla 1×8 sin el encabezado repetido como fila; "Period [s]" vía `get_text()` | 🟢 |
| U-03 | Analyze Data: Precompute/Free memory a un menú "⋯"; quitar la barra de menú duplicada; estado vacío ("Selecciona un CAN ID") en lugar de "—"; autoajuste del eje Y cuando la serie es constante | 🟢 |
| U-04 | CAN Send: botones con texto e ícono; estado vacío "Agrega un frame con +" | 🟢 |
| U-05 | Ribbon: Time Filter pasa de Settings a Home (es un filtro de datos, no un ajuste); botón global Start/Stop de la última conexión (F5 / Shift+F5) | 🟢 |
| U-06 | Precisión fija de 6 decimales en TS en todas las tablas; la tabla principal reajusta el ancho de TS al cambiar la zona horaria (Real-Time ya lo hace) | 🟢 |
| U-07 | Cada ventana secundaria recuerda su geometría entre sesiones (`saveGeometry`/`restoreGeometry` en `BaseWindowManager`) | 🟢 |
| U-08 | Menú contextual mínimo sobre un frame crudo en la tabla principal y Real-Time (copiar ID, copiar frame, plotear byte N, abrir en Candidate); hoy no aparece si la línea no está decodificada (`views/table/table_view.py:106`). F3-01 lo reemplaza por "Enviar a…" | 🟢 |
| U-09 | Diff Live: no mostrar "Run a comparison…" mientras el modo Live está activo | 🟢 |

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

## Fase 6 — Ingeniería inversa avanzada (después de las Fases 3 y 4)

Reglas: todo lo de bits y cambios se construye **dentro** de la taxonomía de F3-05 (no una sexta
lógica); todo consumidor en vivo es O(chunk) sobre `rows_appended` (F2-02); toda salida viaja
con `AnalysisContext` (F3-01) y termina en "Guardar como señal" (F4-03).

| ID | Trabajo | Va después de | Esfuerzo |
|---|---|---|---|
| F6-01 | `services/bit_activity.py`: tasa de flip y magnitud por bit (algoritmo READ), límites de señal sugeridos, clases contador/CRC/constante/física, histograma por byte; acumulador incremental. Heatmap ID × bit | F3-05, F2-02 | 🟡 |
| F6-02 | Candidate usa los límites y clases de F6-01 para podar y rankear; heurística de signo y endianness (CAN-D); oculta contadores y CRC por defecto | F6-01, F3-02 | 🟢 |
| F6-03 | Marcadores de evento (tecla o botón, con nombre y ON/OFF) en vivo y offline, guardados en la sesión; "Diff entre eventos" arma los rangos A/B solo | F3-04 | 🟢 |
| F6-04 | `services/reference_correlation.py`: correlación con lag (Spearman/Pearson por ventanas) contra una referencia (CSV, señal del DBC, otra señal, secuencia de marcadores); propone escala y offset redondeados → "Guardar como señal" | F3-01, F4-03, F6-03 | 🟡 |
| F6-05 | Cursor de tiempo global sincronizado: tabla ↔ plot ↔ Real-Time ↔ timeline del Diff, con los marcadores visibles en todas | F3-04, F6-03 | 🟡 |
| F6-06 | Offline igual que online: Real-Time en posición fija sobre un log cargado, en el instante del cursor, paso a paso o animado (reemplaza el aviso de F1-08) | F2-02, F6-05 | 🟡 |
| F6-07 | Trace de nivel profesional: vista de diferencias (bytes que cambiaron respecto del frame anterior del mismo ID) y filtros por contenido (byte, máscara, valor, DLC, "solo con cambios") en la tabla principal | F2-04, F3-05 | 🟡 |
| F6-08 | Comparar dos logs (base contra acción) sobre `range_diff` | F3-05, D-02 | 🟡 |
| F6-09 | Columnas de trace configurables (hex/dec/bits, Δt, nombre DBC) guardadas en la sesión; columna "Name" y fila expandible con señales decodificadas | F3-06, F4-02 | 🟡 |
| F6-10 | State Tracker: carriles por bit o señal discreta como barras de estado, sincronizados con el cursor | F6-01, F2-06, F6-05 | 🟡 |
| F6-11 | Plot XY y estadísticas entre cursores (mín/máx/media/Δ) | F2-06 | 🟢 |
| F6-12 | Clustering de candidatos correlacionados (señales hermanas o redundantes) | F6-04 | 🟡 |

## Fase 7 — Integraciones y RE activo (después de la Fase 5)

| ID | Trabajo | Va después de | Esfuerzo |
|---|---|---|---|
| F7-01 | J1939 completo: columnas PGN/SA/DA/prioridad, nombre de PGN, transporte BAM + CMDT, DM1/DTC, lista de nodos; las señales J1939 estándar sirven de referencia para F6-04 | F5-01, F6-04 | 🟡 |
| F7-02 | Error frames y contadores de error (hoy se descartan en `viewmodels/connection_stream_viewmodel.py`); observador ISO-TP/UDS/OBD; consultas J1939/OBD para obtener referencias | F5-02 | 🟡 |
| F7-03 | RE activo: replay de un subconjunto filtrado, generador de rampas por señal, "inyectar y observar" con diff automático | F5-02, F6-03, D-02 | 🟡 |

## Backlog (sin fecha; no se toca sin pedido explícito)

| Trabajo | Condición para retomarlo |
|---|---|
| Mux Detection: reactivar o consolidar con Candidate | El usuario lo pide (lógica congelada) |
| HMI Video OCR + ID1 (correlación OCR ↔ señal detectada) | El usuario descongela OCR |
| Constraint Search: persistir precisión y tolerancia | Junto con F3-07 |
| Plot y diálogos: strings duplicados del menú oculto | Junto con F5-06 |
| CAN FD (64 bytes) y multi-bus | Cambia el contrato del DataFrame (`FRAME_SCHEMA`); hoy el campo es 1 bus clásico |
| Importar KCD/SYM/ARXML | Tras F5-01, si aparece un usuario que lo necesite |
| Match contra un corpus público de DBC | Bajo valor: los equipos de campo no son autos de serie |
| Ventanas acoplables (docks) con layouts guardables | Si U-07 (geometría por ventana) no alcanza en el uso real |
| Scripting en Python (plugins) | Un caso de uso concreto que no se resuelva con señales derivadas |
| Fuzzing de frames | Pedido explícito y protocolo de seguridad para equipo real |
