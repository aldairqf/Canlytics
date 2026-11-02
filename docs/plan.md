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

Leyenda de esfuerzo: 🟢 bajo · 🟡 medio · 🔴 alto.

## Fase 0 — Repo, docs y agentes

| ID | Trabajo | Esfuerzo |
|---|---|---|

## Fase 2 — Streaming O(chunk) ([ADR 001](architecture/decisions/001-streaming-append-delta.md), [ADR 002](architecture/decisions/002-no-ram-cap.md))

| ID | Trabajo | Esfuerzo |
|---|---|---|

Línea base F2-01, medida con `scripts/bench_stream.py` (900 fps, 40 IDs): el costo total
crece de 15.84 ms/flush al minuto 1 a 140.16 ms/flush al minuto 10. El `TableModel` pasa de
6.76 a 109.19 ms/flush y domina el costo; el filtro llega a 12.63 ms/flush.

## Fase M — Acceso para IA por MCP (después de la Fase D)

Un servidor MCP (`mcp_server/`, SDK oficial de Python, stdio) expone los servicios Qt-free para
que Claude, Codex u otro cliente MCP analicen logs y usen las funciones de la app.

| ID | Trabajo | Va después de | Esfuerzo |
|---|---|---|---|
| M-01 | Servidor MCP headless sobre archivos de log: `load_log`, `list_ids`, `id_stats`, `find_candidates`, `diff_ranges`, `constraint_search`, `export_log`, guardar señales y marcadores. Escritura de archivos habilitada; nunca escribe en la carpeta de logs de campo. Envío de frames al bus solo si el servidor arranca con `--allow-can-send`, y cada envío queda en el TX log | D-02 | 🟡 |
| M-02 | Herramientas con DBC (`decode_with_dbc`, `save_signal_to_working_dbc`) | F5-01, F4-01 | 🟢 |
| M-03 | Conexión a la sesión abierta de la app (log cargado, captura en vivo, marcadores, contexto de análisis) por un canal local entre procesos | F3-01, M-01 | 🟡 |

## Fase U — Pulido UX rápido (en paralelo con la Fase 2; cada ítem ≤ 1 día)

| ID | Trabajo | Esfuerzo |
|---|---|---|
| U-04 | CAN Send: botones con texto e ícono; estado vacío "Agrega un frame con +" | 🟢 |
| U-05 | Ribbon: Time Filter pasa de Settings a Home (es un filtro de datos, no un ajuste); botón global Start/Stop de la última conexión (F5 / Shift+F5) | 🟢 |
| U-06 | Precisión fija de 6 decimales en TS en todas las tablas; la tabla principal reajusta el ancho de TS al cambiar la zona horaria (Real-Time ya lo hace) | 🟢 |
| U-07 | Cada ventana secundaria recuerda su geometría entre sesiones (`saveGeometry`/`restoreGeometry` en `BaseWindowManager`) | 🟢 |
| U-08 | Menú contextual mínimo sobre un frame crudo en la tabla principal y Real-Time (copiar ID, copiar frame, plotear byte N, abrir en Candidate); hoy no aparece si la línea no está decodificada (`views/table/table_view.py:106`). F3-01 lo reemplaza por "Enviar a…" | 🟢 |
| U-09 | Diff Live: no mostrar "Run a comparison…" mientras el modo Live está activo | 🟢 |
| U-10 | Ventana "XY": elegir dos señales cualesquiera (DBC, BAM/J1939, derivadas o candidatas), alinearlas en el tiempo (`join_asof`) y dibujar Y contra X con color por tiempo; rango de tiempo y exportar CSV. Ventana propia que reutiliza el decodificador, sin tocar el plot que reescribe F2-06 | 🟡 |

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
| F6-11 | Estadísticas entre cursores en el plot (mín/máx/media/Δ) y modo XY integrado al plot principal (reusa U-10) | F2-06, U-10 | 🟢 |
| F6-12 | Clustering de candidatos correlacionados (señales hermanas o redundantes) | F6-04 | 🟡 |

## Fase 7 — Integraciones y RE activo (después de la Fase 5)

| ID | Trabajo | Va después de | Esfuerzo |
|---|---|---|---|
| F7-01 | J1939 completo: columnas PGN/SA/DA/prioridad, nombre de PGN, transporte BAM + CMDT, DM1/DTC, lista de nodos; las señales J1939 estándar sirven de referencia para F6-04 | F5-01, F6-04 | 🟡 |
| F7-02 | Error frames y contadores de error (hoy se descartan en `viewmodels/connection_stream_viewmodel.py`); observador ISO-TP/UDS/OBD; consultas J1939/OBD para obtener referencias | F5-02 | 🟡 |
| F7-03 | RE activo: replay de un subconjunto filtrado, generador de rampas por señal, "inyectar y observar" con diff automático | F5-02, F6-03, D-02 | 🟡 |

## Fase P — Plugins de terceros (después de F3-01, F4-01, F5-01 y D-02)

Las empresas extienden Canlytics con su propio código, que **no se versiona en este repo**. Un
plugin es una carpeta con `plugin.toml` + Python en `%APPDATA%\Canlytics\plugins\` (o
`CANLYTICS_PLUGINS_DIR`), o un paquete pip con *entry point* `canlytics.plugins`. Tiene
PySide6 completo y puede crear sus propias ventanas. Solo el SDK (`canlytics_sdk`) es API
estable con versión; importar `views/` o `viewmodels/` funciona pero puede romperse en cualquier
release. Un plugin es código de confianza (sin sandbox).

| ID | Trabajo | Va después de | Esfuerzo |
|---|---|---|---|
| P-01 | Cargador de plugins (carpeta + entry points, `plugin.toml` con `api_version`), aislamiento de errores, pantalla Configuración → Plugins (activar, desactivar, ver errores). SDK mínimo: contrato de frames, DBC cargado y de trabajo, servicios de análisis, exportar. Puntos de extensión: fuente de DBC (p. ej. base de datos de la empresa → DBC), importador y exportador de logs. Guía para autores en `docs/plugins.md` + plugin de ejemplo fuera del árbol de la app | F4-01, F5-01, D-02 | 🟡 |
| P-02 | UI de plugins: registrar ventanas propias (grupo "Plugins" en el ribbon, ciclo de vida y geometría como las ventanas de la app, tema), suscripción a datos en vivo O(chunk) que se desconecta sola al cerrar, acciones en "Enviar a…" y menús contextuales con `AnalysisContext`, marcadores y envío de frames | F3-01, P-01 | 🟡 |
| P-03 | Cada plugin puede exponer herramientas MCP que el servidor de M-01 publica junto a las propias | M-01, P-01 | 🟢 |
| P-04 | SDK de transmisión para plugins configuradores (p. ej. una ventana que configura un controlador por J1939): `send_frame`, `send_pgn` con transporte J1939 como emisor (BAM y RTS/CTS), `request_pgn` y `wait_for(pgn, sa, timeout)` sin bloquear la UI; bloques para Memory Access (DM14/DM15/DM16) cuando el fabricante lo use. Solo con conexión real (nunca en replay) y todo envío al TX log | F5-02, F7-01, P-02 | 🟡 |

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
| Fuzzing de frames | Pedido explícito y protocolo de seguridad para equipo real |
