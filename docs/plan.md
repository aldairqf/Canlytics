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

## Fase U — Pulido UX rápido (en paralelo con la Fase 2; cada ítem ≤ 1 día)

| ID | Trabajo | Esfuerzo |
|---|---|---|

## Fase 3 — Contexto de análisis y conceptos unificados ([ADR 004](architecture/decisions/004-analysis-context.md))

| ID | Trabajo | Esfuerzo |
|---|---|---|

## Fase 4 — DBC de trabajo ([ADR 003](architecture/decisions/003-working-dbc.md))

| ID | Trabajo | Esfuerzo |
|---|---|---|

## Fase 5 — Deuda de arquitectura (sin cambio de comportamiento)

| ID | Trabajo | Esfuerzo |
|---|---|---|

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
