# Revisión funcional de Canlytics (rama `dev`) — 2026-11-15

**Línea base:** [docs/review/2026-11-functional-review.md](app/docs/review/2026-11-functional-review.md) (2026-11-01).
**Qué se probó:** la app real (`MainWindowViewModel` + `MainWindow`, Qt offscreen, tema Dark y Light) manejada con scripts QTest/`grab()`. Cada afirmación va marcada **CONFIRMADO** (visto en la app o en una captura de `screenshots/`) o **PLAUSIBLE** (solo por lectura de código).
**Datos:** `log candump real de 154 MB` (154 MB, 3 031 318 tramas, 184 IDs, 1 bus `can1`, tráfico J1939), `otro log candump`, `segundo log de campo` (58 MB) y `log de dos minutos` (51 619 tramas, 39 IDs). Ningún log fue modificado.
**Snapshot:** `git archive dev` al inicio de la revisión (cabeza `4cef7e0`), copiado a `app/` dentro de esta carpeta. El repo no se tocó.
**Verdad-terreno para el flujo de ingeniería inversa:** en log candump real el ID `0CF00400` es el EEC1 de J1939; la velocidad del motor es 16 bit little-endian desde el bit 24, escala 0,125 rpm. Sirve para saber si la app encuentra y guarda una señal correcta.
**Nota de método:** para poder trabajar con log candump real en los scripts del flujo (cargar repetidas veces) sustituí en *mi harness* `TableModel._rebuild_time_index` por una versión vacía; los números de carga/RAM "reales" salen de las corridas **sin** ese parche (ver §7). El resto de las capturas del flujo no dependen del índice.

---

## 1. Veredicto

**El flujo completo funciona de punta a punta** (cargar → aislar un ID → Candidate → "Save as signal" → Working DBC → decodificación en la tabla → Plot) y con log candump real **encuentra la señal correcta** (`start 24, len 16, LE, score 1,0`) y la decodifica como `EngineSpeed: 1741.375 rpm`. Eso es un salto grande frente a la línea base, donde no se podía guardar ninguna señal.

Lo que hoy lastima al usuario no es la falta de funciones sino:
1. **Carga de logs grandes:** con log candump real la app queda **congelada ~31 s** (≈7 s de parseo con la GUI sin responder + **24 s de reconstrucción síncrona de un índice de tiempo** en el hilo de la GUI) y gasta **~1,7 GB de RAM extra** por ese índice. La rutina nueva del cursor global (`TableModel._rebuild_time_index`) es la causa. El diálogo de carga es una barra indeterminada: **sin % ni ETA** (regla del proyecto).
2. **El aviso de memoria nunca aparece** en logs grandes: `memory_warning_requested = Signal(int, int)` desborda con valores > 2 GiB (`OverflowError`), justo cuando el aviso hace falta.
3. **Defaults que ocultan la señal:** Candidate busca solo señales de **8 bits** (`Max Length = 8`, oculto bajo "Configuration"). En un bus J1939 la señal real (16 bit) no aparece hasta que el usuario descubre ese panel.
4. **Funciones duplicadas** (sección 5): la más clara es **XY Plot (ventana) vs modo XY** — son el *mismo* widget con dos botones; además hay dos sistemas de "nombrar" una señal (Tag de Candidate vs Working DBC) que no se hablan, dos reproductores (Playback del Plot vs transporte offline de Real-Time) y cuatro formas de ver "qué se mueve" a distintos niveles.
5. **Terminología, formato de tiempo/ID y tema Light** inconsistentes (ribbon "Bit Map" vs ventana "Bit Activity", "Scan" vs "Signal Scan/Coverage", `0CF00400` vs `CF00400`, epoch crudo con 2 y 6 decimales, plots negros en Light).

**Contra la línea base (2026-11-01):** mejoró casi todo lo estructural (DBC de trabajo editable, "Save as signal" desde 6 sitios, `AnalysisContext` que viaja con el "Send to…", cursor global, Ctrl+F, Real-Time offline, CAN Send deshabilitado en replay con mensaje, MUX único compartido). **Sin cambio:** Mux Detection sigue inalcanzable. **Regresiones nuevas:** el congelamiento/RAM de la carga (índice del cursor global) y el desborde del aviso de memoria (aviso de >2 GB).

---

## 2. Inventario de funciones (desde el punto de vista del usuario)

Ribbon: pestañas **Home / Analysis / Settings**. Además existe un menú oculto con atajos (`Ctrl+O`, `Ctrl+S`, `Ctrl+F`, `Ctrl+M`, `F5`, `Shift+F5`, `F10`).

| Función | Dónde vive | ¿Funciona? | Notas |
|---|---|---|---|
| Cargar log (candump) / Append / Save / Clear / Recientes / arrastrar y soltar | Home › File; `Ctrl+O/S` | Sí (solo candump probado) | Carga log candump real en 7 s de parseo + 24 s de congelamiento posterior (§7). Diálogo de carga indeterminado sin % ni ETA (`03_load_dialog.png`). Otros formatos (ASC/BLF/TRC/CSV) **no probados**. |
| Guardar/exportar (candump, ASC, BLF, TRC, CSV) con alcance "All frames/…" | Home › Save | Diálogos OK (`82_export_dialog.png`) | Escritura real **no probada**. |
| Tabla principal (Trace) con resaltado de bytes que cambiaron, Hex/Dec/Bits, filtros Byte/Mask/Value/DLC/Only changes, Columns… (Δt, nombre DBC) | Central | Sí | `80_only_changes.png`, `80_byte_filter.png`, `80_datamode_Bits.png`, `81_columns_dialog.png`. Ver B-13/B-14 (filas sin cambios, orden de ID). |
| Panel de CAN IDs (buscar, seleccionar, "Interpret frames", Expand/Collapse) | Central derecha | Sí | Filtrar a 1 ID en log candump real: 1,9 s (`12_filter_single_id.png`). Muestra etiqueta DBC (`0CF00400 EEC1`). |
| Ctrl+F (saltar a un CAN ID) | Atajo global | Sí | `53_ctrlf_jump.png` (diálogo con lista y búsqueda). |
| Time Filter | Home › Filter; también en Analyze y Candidate | Sí | `05_timefilter.png` (campos Timestamp y Date). Solo afecta tabla, Analyze, Candidate (§5.10). |
| Time Config (normalizar, zona horaria) | Settings; además botones en Plot, Analyze, Candidate, Connection | Sí | Por defecto `Raw seconds` → todo el programa muestra epoch crudo (`05_timeconfig.png`). |
| Plot (señales, derivadas, presets, export imagen/CSV) | Analysis › Add Plot; "Add new graph" desde menús | Sí | EngineSpeed de 98 824 puntos sobre 3 M tramas en 2,6 s (`23_plot_enginespeed.png`). |
| Plot: cursores A/B, snapshot, Follow, Snap, Playback | Plot › Cursor/Tools | Sí | `24_plot_dual_cursor.png` (A y B nacen en el mismo punto, Δt 0). Valores del cursor con dígitos tenues. |
| Plot: carriles de estado por bit | Plot › Tools › "Add bit lane" | Sí | `25_plot_state_track.png`. Etiqueta `0CF00400 · D4 · b0` (vs `B3` en el resto). Botón truncado ("Add b… lane"). |
| Plot: modo XY (dentro de la ventana) **y** ventana XY Plot | Plot › Tools › XY | Sí | **Mismo widget** (`26_plot_xy_mode_one_signal.png` vs `26_xy_window.png`). |
| Plot: FFT | Plot › Tools › FFT | **Dudoso** | Ventana en blanco con 2 señales de 98 k muestras no uniformes tras 2 s (`27_fft.png`). Ver B-16. |
| Real-Time Analysis en vivo (replay) | Analysis › Real Time | Sí | `71_realtime_live.png` (Track Changes, Changes Only, Compare from now…). Barra inferior dice "Idle" mientras corre (B-24). |
| Real-Time offline en el cursor (anterior/siguiente/play, slider) | Analysis › Real Time con log cargado | Sí | `50_cursor_realtime.png`, `captura_log_grande`: 184 IDs, índice en 0,17 s. Controles de cambio deshabilitados ("disponible durante captura en vivo"). |
| Cursor global sincronizado (tabla, Plot, Real-Time, Diff, status bar) | `time_cursor_vm` | Sí | `50_cursor_*.png`: línea en el Plot, slider en Real-Time, fila 25 804 en la tabla, `Cursor: 1779024089.55` en la barra. |
| Marcadores de eventos ON/OFF + "Diff between events" | Analysis › Events (`Ctrl+M`) | Sí | `52_markers_window.png`, `52_markers_to_diff.png`. Botón sin icono; sin estado vacío; tiempo con 6 decimales. |
| Analyze Data (series por byte, estadísticas, Matrix, MUX, "Send to", opción de precómputo) | Analysis › Analyze | Sí | `60_analyze_*.png`, `61_analyze_matrix.png` (Matrix de sparklines por byte, 1 s). |
| Candidate Interpretations (parámetros, resultados, tags, filtros, import/export de tags) | Analysis › Candidates | Sí | `14_*`, `15_*`, `16_*`. 1 ID: 6 s; 4 IDs: 17 s. Lista truncada (B-05). |
| Candidate: correlación con referencia (CSV, señal DBC, candidato, marcadores) | Candidate › "Correlate with Reference" | Parcial | Ventana abre; no ejercitada con referencia real. |
| Candidate: "Find correlated candidates…" (clusters) | Candidate (botón inferior) | Ver §4.5 | Rechaza más de 500 candidatos (`candidate_correlation_max_candidates`). |
| Candidate: Matrix | Candidate › pestaña Matrix | Ver §4.5 | |
| Value at Time Search (antes "Constraint Search") | Candidate › "Value Search" | Ver §4.5 | Nombre inconsistente: menú "Value at Time Search", barra "Value Search", código "Constraint Search". |
| Bit Activity (heatmap ID×bit, segmentos sugeridos, histograma por byte, "Send selected signal to…") | Analysis › "Bit Map" | Sí | `04_bitactivity_0.png`; en log candump real el análisis tarda 42 s con la GUI libre. Título de la ventana: "Bit Activity". |
| Bus Statistics (FPS, periodo min/media/max, jitter, estado) | Analysis › Bus Stats | Sí | `captura_log_grande`. Orden por defecto: CAN ID descendente (texto). |
| Signal Scan / Signal Coverage (DBC activos × log) | Analysis › "Scan" | Sí | `captura_log_grande` (1 señal del Working DBC). Sin estado vacío cuando no hay DBC (`04_coverage_0.png`). |
| Diff Analyzer: rangos A/B, timeline, opciones, MUX, Live, Compare two logs | Analysis › Diff Analyzer | Sí | `31_diff_*.png`, `33_diff_two_files.png`, `73_diff_live.png`. Compare 10 s vs 10 s de 3 M tramas: 1,2 s. Dos logs completos (log candump real vs otro log candump): 5,8 s. |
| DBC Manager (cargar/borrar/activar DBC) | Home › DBC | Sí | `05_dbcmanager.png`: "Working DBC" aparece como una entrada más, con "Delete DBC". |
| Working DBC (listar/añadir/editar/borrar mensajes y señales, exportar `.dbc`) | Home › Working DBC | Sí | `19_working_dbc_after_save.png`. ID mostrado como `CF00400` (sin el 0). |
| Save as signal (diálogo con contexto) | Menús "Send to", Bit Activity, tabla, Candidate… | Sí | `18_save_signal_dialog.png`, `19_save_signal_filled.png`. Error inline si el nombre ya existe. |
| Conexión: SSH / registrador CAN / Replay; Start/Stop (`F5`/`Shift+F5`) | Home › Connect/Start | Replay sí; SSH/registrador CAN **no** | `70_connection_replay.png`, `70_live_replay_main.png`. |
| Grabación continua | Automática al conectar | Sí | En replay también graba (B-19). Directorio `~/Canlytics/Recordings`. |
| CAN Send | Home › Send | Sí | En replay: "Sending is not available while replaying a log" (`72_cansend_during_replay.png`); sin conexión: "Not connected" (`04_cansend_0.png`). Transmisión real **no probada**. |
| Mux config (`Edit MUX Rules`) | Botón en Analyze, Candidate, Diff, Real-Time | Sí | `85_mux_dialog.png`: tabla vacía sin ayuda. |
| Mux Detection (ventana) | — | **Inalcanzable** | No hay manager ni botón (`grep MuxDetectionWindowManager` solo lo encuentra en su propio archivo). Zona congelada. |
| Plugins (importar, habilitar) | Settings › Plugins | Abre | `05_plugins.png` (sin plugins). No se probó importar. |
| Debug Log | Settings › Debug Log | Sí | `84_debug_log.png`. |
| Theme Dark/Light, About | Settings | Sí | Light: ver B-06. |
| HMI Video/OCR | — | Inalcanzable | Congelado por decisión del usuario. |
| Servidor MCP / puente | Proceso aparte | No probado | |

---

## 3. Recorrido del flujo de ingeniería inversa en log candump real

Pasos reales (capturas en `screenshots/`). Tiempos medidos en la corrida, sin el parche del índice salvo que se indique.

1. **Cargar** `log candump real de 154 MB` → 7 s de parseo, luego ~24 s de GUI congelada (§7). Barra de progreso sin % ni ETA. `captura_log_grande`.
2. **Encontrar IDs interesantes.** La tabla muestra 3 M filas y 184 IDs. Opciones reales: Bus Stats (ordena por ID, no por actividad; `captura_log_grande`), Bit Activity (42 s, heatmap por bit; `13_bitactivity_*.png`), Diff Analyzer entre dos tramos, Analyze › Matrix. **Fricción:** no hay una vista que diga "estos son los IDs que cambian más / que más correlacionan con el ruido del motor". En el Diff entre el tramo de menos y el de más rpm (`31_diff_selected_id_expanded.png`) aparecen **96 IDs con cambios** ordenados por CAN ID descendente; la mayoría son "Only in A/B" (tramas lentas de 1–2 s que simplemente no cayeron en el tramo de 10 s), y el EEC1 está enterrado entre ellos. No hay orden por p-value/Δ medio ni "ocultar presencia".
3. **Aislar el ID** en el panel de la tabla: filtro a `0CF00400` (1,9 s), resaltado azul de bytes cambiados, byte 3–4 cambian (`12_filter_single_id.png`).
4. **Detectar candidato (Candidate).** Con los defaults (bytes de 8 bits) solo se proponen fragmentos de 8 bits: el mejor es el byte 3 (score 0,806), un diente de sierra sin sentido (`captura_log_grande`). Hay que abrir **"Configuration"** (colapsado), cambiar *Max Length* a 16 y recalcular (5 s): entonces el primero es `start 24 / len 16 / LE / unsigned / score 1,000` (`15_candidate_results_16bit.png`, `16_candidate_details.png`). **Fricción:** el empate 1,0 con el mismo bit-range en big endian (`start 23`) obliga a elegir; y la lista no muestra scores (ver B-05).
5. **Confirmar visualmente.** La gráfica del candidato muestra el valor crudo 0–18 000 (sin escala); la tabla decodificada mostrará luego 1741 rpm. Escala y unidad **no se infieren** si no hay CSV de referencia (el diálogo "Save" trae `scale = 1.0`). El usuario debe saber 0,125.
6. **Nombrar.** Dos caminos que no se conectan: **Tag** del Candidate (campo "Signal name / meaning", guarda un `signal_tags.json`, marca la fila con ★; `17_tagged.png`) y **Save as signal → Working DBC** (`18_*`, `19_*`). Etiquetar *no* crea la señal DBC, y guardar la señal *no* marca el candidato.
7. **Guardar en Working DBC.** Menú contextual del plot del candidato → "Working DBC" (`17_send_to_menu.png`, que ofrece "Candidate Interpretations" desde el propio Candidate) → diálogo prellenado con ID, start, length, endianness, mux (`18_save_signal_dialog.png`). Tras completar nombre/escala/unidad: mensaje de estado largo (ruta del `.dbc`) que la barra recorta (`19_save...`). El nombre duplicado se rechaza con error inline: bien.
8. **Ver la señal decodificada.** En la tabla: activar "Interpret frames" + "Expand all" → cada fila muestra `EngineSpeed: 1741.375 rpm` (`20_table_interpret_expanded.png`). El panel de IDs muestra `0CF00400  EEC1`. Plot: menú del texto decodificado → "Add new graph" → curva de 1 700 rpm con ralentí a 600 rpm (`23_plot_enginespeed.png`); verifica el resultado contra la verdad-terreno (ralentí ≈ 600 rpm, máx 2266 rpm).
9. **Contexto que se pierde en el camino:**
   - La selección de IDs de la tabla **no** viaja: Analyze, Candidate y Real-Time empiezan con su propia lista (Analyze ni muestra la etiqueta DBC; `60_analyze_bytes.png`).
   - Del Candidate al Save sí viaja ID/bits/endianness/mux (bien), pero **no** viaja el rango de tiempo ni la escala.
   - Time Filter: lo respetan tabla/Analyze/Candidate; Bit Activity, Bus Stats, Signal Scan, Plot y Real-Time lo ignoran (código: `time_range_vm` solo en Analyze/Candidate/tabla/Mux).
   - Desde el Diff, "Send to Candidate" sí lleva byte y ventanas A/B (mejora vs línea base).
10. **Callejones sin salida / puntos de fricción:** abrir Candidate, Analyze y Diff son tres ventanas independientes, cada una con su propio selector de IDs y tiempo; "Real Time" (offline) abre una ventana sin Track Changes ("disponible durante captura en vivo"); el menú "Working DBC" del Diff no es el mismo que el del Candidate (lista distinta); Mux (si el ID fuera multiplexado) solo se puede declarar a mano (`85_mux_dialog.png`, tabla vacía sin ayuda) porque Mux Detection es inalcanzable.

---

## 4. Hallazgos adicionales por ventana

### 4.1 Tema Dark/Light
- **CONFIRMADO** (`40_light_candidate.png`, `40_light_analyze.png`): en Light, los plots de Candidate y Analyze Data siguen **negros** (el Plot principal sí cambia a blanco: `40_light_plot.png`).
- **CONFIRMADO** (`40_light_main.png`): la barra del botón dividido "Load Log" es un bloque negro con flecha blanca en ambos temas.
- Resto de ventanas en Light correctas (`40_light_diff.png`, `40_light_bitactivity.png`, `40_light_realtime.png`).

### 4.2 Estados vacíos
- **CONFIRMADO:** Signal Scan sin análisis (`04_coverage_0.png`), Event Markers sin eventos (`04_markers_0.png`), Working DBC sin mensajes (texto sí: "No messages in Working DBC yet."), Plot sin señales (un recuadro vacío), Candidate ("No candidate signals yet…" sí). Faltan pistas en Signal Scan (no dice que necesita DBC) y en Event Markers.
- **CONFIRMADO** (`13_bitactivity_progress.png`): Bit Activity al abrirse con un log cargado dice "No frames to analyze. Load a log or start a capture." hasta que termina la primera pasada.

### 4.3 Diálogos de espera (regla %/ETA)
- Carga de log: **sin %/ETA** (barra deslizante indeterminada; `QProgressDialog(…, 0, 0)` en `views/main_window.py:793-797`; `LogLoadViewModel` no tiene señal de progreso).
- Candidate, Bit Activity, Diff: `EtaProgressDialog` con % y "~Ns left"/"finishing up (Ns elapsed)" (`14_candidate_progress.png`). Cumplen.
- Reconstrucción del índice de la tabla (24 s) y reemplazo del DataFrame: **sin diálogo** (GUI congelada).

### 4.4 Real-Time, replay y grabación
- Replay: la tabla muestra TS **relativo** (`0.000000`) mientras el mismo log cargado offline muestra epoch (`1779024042.846`) — mismo dato, dos bases de tiempo (`70_live_replay_main.png`).
- Grabación continua durante un replay: escribe un duplicado del log reproducido en `~/Canlytics/Recordings` (1,6 MB para 2 min; hay 25 archivos de este tipo ya acumulados por sesiones anteriores). **CONFIRMADO.** (El archivo que generé yo en esta revisión lo borré.)
- La barra del Real-Time dice "Idle" aunque esté recibiendo (`71_realtime_live.png`).

### 4.5 Candidate: clusters, matrix, Value at Time, referencia
- **Clusters** (`Find correlated candidates…`, 4 IDs / 180 candidatos): termina y muestra un diálogo casi vacío con "No candidate groups met the correlation threshold." (`64_cluster_1.png`); no se pudo juzgar su utilidad con esta entrada. Con todos los IDs de log candump real el botón se niega (>500 candidatos): **PLAUSIBLE** por código, no se llegó a medir (la corrida de "todos los IDs" se canceló por tiempo).
- **Matrix del Candidate** (`64_candidate_matrix.png`): agrupa por categoría (Binary 16, Enum 8…) con sparklines por candidato; por defecto "Include constant bytes" está activo, por lo que bytes constantes (`0CF00400 b48/16`, FF FF) aparecen como celdas "Binary" planas: ruido. Distinta de la Matrix de Analyze (por byte/ID).
- **Value at Time Search** y **Correlate with Reference**: se abren, pero no se ejercitaron con datos (cortado por tiempo).

---

## 5. Funciones duplicadas (pedido principal)

Veredicto: **justificado** = atajo que reutiliza la misma lógica/semántica; **redundante/confuso** = comportamiento, resultado o nombre distintos, o innecesario.

| # | Función | Dónde está | ¿Misma lógica? | Veredicto | Recomendación |
|---|---|---|---|---|---|
| 1 | **Vista XY** | Plot › Tools › "XY Plot" (ventana `XYWindow`) y "XY mode" (toggle dentro del Plot) | **Sí: el mismo `XYPlotWidget`** (`views/plot/xy_window.py:27`, usado en `plot_window.py:654` y por `XYWindow`) | **Redundante** (dos botones juntos con nombres casi iguales, mismos controles X/Y/rango/Snapshot/Refresh/Export; `26_plot_xy_mode_one_signal.png` = `26_xy_window.png`) | Quitar la ventana o convertirla en "pop-out" del modo. Dejar un solo botón "XY". |
| 2 | **Qué bits/bytes se mueven** | Bit Activity (heatmap por bit + segmentos), Analyze Data › Matrix (sparklines por byte), Candidate › Matrix (celdas por candidato), Candidate "bit rank" (ordenación) | Parcial: Bit Activity/Candidate comparten la actividad de bits (CHANGELOG); Analyze Matrix tiene su propio cálculo por byte | **Bit Activity: justificado** (único con bit×ID y envío al flujo); **Analyze Matrix y Candidate Matrix: redundantes entre sí** | Fusionar las dos Matrix en una sola vista o quitar la del Candidate; en Analyze, enlazar a Bit Activity para la vista de bits. |
| 3 | **"Qué cambió"** | Resaltado azul en la tabla (vs trama anterior del mismo ID), Diff Analyzer (rango A vs B), Real-Time "Track Changes" (solo vivo), "Only changes" del filtro | Reglas compartidas según el CHANGELOG; semánticas distintas (por trama, por rango, en vivo) | **Justificado** | Nombrar distinto en pantalla ("Δ vs trama previa", "Δ entre rangos", "Δ en vivo") y documentar. El Track Changes deshabilitado offline debería ocultarse, no mostrar un texto largo. |
| 4 | **Estado del bus en un instante** | Real-Time offline (último frame por ID en el cursor) vs tabla principal (cronológica) | No: la tabla no ofrece "último valor por ID en t" | **Justificado**, mal nombrado | Rotular como "Bus State at cursor" cuando es offline; ensanchar la columna TS (aparece `179469…`). |
| 5 | **MUX** | `Edit MUX Rules` (4 ventanas, un solo estado compartido) y Mux Detection | Mux config: una sola fuente. Mux Detection: no se puede abrir | Config: **justificado**. Mux Detection: **muerta para el usuario** | Mantener el botón único; decidir si Mux Detection se reexpone o se quita del build. Añadir ayuda/ejemplo en el diálogo vacío. |
| 6 | **"Send to…"** | `analysis_send_destinations`/`plot_send_destinations` (Candidate, Analyze, Bit Activity, Signal Scan, Plot, Constraint Search, tabla) vs menús propios (Diff `range_diff_window.py:680`, menú de frame, Real-Time) | Sí en 7 sitios | **Justificado** con 3 excepciones | Unificar etiquetas ("Add new graph" vs "Plot"); quitar el destino a sí mismo (Candidate se ofrece "Candidate Interpretations", `17_send_to_menu.png`); hacer que Diff y menú de frame usen el helper común. |
| 7 | **Estadísticas por ID** | Bus Statistics (ms, FPS, jitter) vs Real-Time Details ("Period [s] min/max/avg") vs Signal Scan (min/max/mean/Unique) vs Analyze "Statistics" | Cálculo de periodo duplicado, **unidades distintas** (ms vs s) | **Redundante en periodo**, justificado en lo demás | Un solo cálculo de periodo; mostrar siempre ms. En Real-Time enlazar a Bus Stats para el detalle. |
| 8 | **Nombrar una señal** | Tag del Candidate (`signal_tags.json`, TXT export/import) vs Working DBC | **No**: tags y DBC no se sincronizan (`17_tagged.png`: el DBC sigue vacío) | **Redundante/confuso** | Que "Tag" cree/prellene una señal en Working DBC (o eliminar tags y quedarse con "Save as signal"). |
| 9 | **DBC** | DBC Manager (externos + "Working DBC" como entrada con Delete) vs ventana Working DBC; mismo icono `database` en ambos botones | Misma base `DbcManager` | **Justificado**, con riesgo | Distinguir iconos; bloquear Delete sobre Working DBC en el manager. |
| 10 | **Tiempo** | Time Config (7 puntos de entrada: ribbon, menú, Plot, Analyze, Candidate, Connection, Mux) y Time Filter (ribbon, Analyze, Candidate) con `time_range_vm` único | Misma fuente | **Justificado**, pero Time Filter lo ignoran Bit Activity, Bus Stats, Signal Scan, Plot, Real-Time (PLAUSIBLE por código) | Mostrar insignia "Time filter activo" en las ventanas que lo ignoran, o aplicarlo. |
| 11 | **Selector de CAN ID** | 8 listas independientes (tabla, Analyze, Candidate, Real-Time, Bit Activity (caja de filtro), Value Search, diálogo Ctrl+F, derivadas) | Misma clase base para varias, selección **no compartida** | **Parcialmente redundante** | Opción "Usar selección de la tabla" en cada ventana; mostrar la etiqueta DBC en todas (hoy solo en la tabla). |
| 12 | **Reproducir en el tiempo** | `PlaybackBar` del Plot vs transporte offline de Real-Time (Prev/Play/Next + slider) | No (dos implementaciones, ambas atadas al cursor global) | **Redundante** | Un solo reproductor atado al cursor global (en la barra de estado o en una ventana ligera). |
| 13 | **Exportar CSV** | Plot, Diff, Signal Scan, XY (cada uno su propio diálogo y formato) | Distintos datos | **Justificado** | Nada; unificar el nombre ("Export CSV"). |
| 14 | **Marcadores de evento** | Ventana Events + líneas en Plot, tabla (fila teñida), Real-Time y Diff | Misma fuente (`event_markers_vm`) | **Justificado** | — |
| 15 | **Plot: entrada** | Ribbon "Add Plot", menú "Add new graph/Add last graph", botón "Signal" dentro del Plot | Mismo gestor | **Justificado** | Renombrar "Add Plot" → "New Plot". |
| 16 | **Etiquetado de bytes/bits** | Plot: `B3`; carriles: `D3·b0`; Bit Activity: `D0`, `b0`; Analyze: `B0`; Candidate: `startBit 24` | n/a | **Redundante (terminología)** | Elegir `B` o `D` y bit LSB/MSB únicos. |

---

## 6. Bugs y problemas visibles (ordenados por severidad)

Severidad: **Alta** (bloquea o daña el trabajo), **Media** (confunde o pierde información), **Baja** (cosmético/pulido).

| ID | Sev. | Qué pasa | Pasos | Captura | `archivo:línea` (si se sabe) | Estado |
|---|---|---|---|---|---|---|
| R-01 | **Alta** | Tras cargar log candump real la GUI queda congelada **24 s** y consume **~1,7 GB extra** (2,98 GB vs 1,24 GB). segundo log de campo (58 MB): 11 s. | Cargar `log candump real de 154 MB`. Perfil: 6,06 M `df[row, col]` + 3 M `QPersistentModelIndex` | `captura_log_grande` | `viewmodels/table_model.py:462-475` (`_rebuild_time_index`, llamada desde `set_dataframe` y todo cambio de filtro) | CONFIRMADO |
| R-02 | **Alta** | El aviso de memoria nunca llega: `OverflowError` al emitir `Signal(int, int)` con 2 923 294 720 / 2 147 483 648 y luego `AttributeError: Slot '_offer_memory_cleanup(int,int)' not found`; `_warning_active` ya quedó en `True` y no se reintenta. | Cargar log candump real (memoria > 2 GiB). | (stderr de `s02_bigload`) | `viewmodels/measurement_status_viewmodel.py:25,77` | CONFIRMADO |
| R-03 | Media | Diálogo de carga indeterminado: sin % ni ETA; durante ~6 s de parseo la GUI no pinta (el diálogo no anima). | Cargar cualquier log grande. | `03_load_dialog.png` | `views/main_window.py:793-797`; `viewmodels/log_load_viewmodel.py` | CONFIRMADO |
| R-04 | Media | Candidate busca solo señales de 8 bits por defecto; el EEC1 de 16 bit no aparece. El panel que lo cambia está colapsado y no hay pista. | Candidate › ID `0CF00400` › Recalculate. | `captura_log_grande` vs `15_candidate_results_16bit.png` | `viewmodels/candidate_interpretations_viewmodel.py:185-186` (`_min_length = 8`, `_max_length = 8`) | CONFIRMADO |
| R-05 | Media | La lista de candidatos corta el texto (solo `ID: … startBit: 24 sigLe…`); no se ve score, tipo ni endianness; los 60 candidatos parecen idénticos. | Candidate con resultados, ventana 1700 px. | `16_candidate_details.png`, `17_tagged.png` | `views/candidate_interpretations_window.py` (`candidate_list`, columna derecha ~320 px) | CONFIRMADO |
| R-06 | Media | Plots de Candidate y Analyze negros en Light. | Settings › Theme › Light, abrir Candidate/Analyze. | `40_light_candidate.png`, `40_light_analyze.png` | (renderer de esos plots) | CONFIRMADO |
| R-07 | Media | "Tag" no crea ni actualiza Working DBC; dos fuentes de nombres. | Tag "EngineSpeed" y mirar Working DBC. | `17_tagged.png`, `19_working_dbc_after_save.png` | `views/candidate_interpretations_window.py:1542`, `services` de tags | CONFIRMADO |
| R-08 | Media | El Diff devuelve 96 IDs ordenados por CAN ID descendente; "Only in A/B" domina; no hay orden por relevancia. | Diff 10 s vs 10 s (rpm bajo vs alto). | `31_diff_selected_id_expanded.png` | `views/range_diff_window.py` (`_make_id_row`) | CONFIRMADO |
| R-09 | Baja | FFT en blanco con 2 señales (98 k muestras no uniformes) tras 2 s. | Plot › Tools › FFT. | `27_fft.png` | `views/plot/fft_window.py` | CONFIRMADO (causa: PLAUSIBLE, muestreo no uniforme) |
| R-10 | Baja | Mux Detection inalcanzable. | Buscar en ribbon/menú. | — | `views/mux_detection_window_manager.py` (sin referencias) | CONFIRMADO |
| R-11 | Baja | `Events` sin icono en el ribbon. | Analysis tab. | `05_ribbon_analysis.png` | `views/widgets/ribbon_bar.py:303-305` (pide el icono `bookmark`, que no existe en `assets/icons/`) | CONFIRMADO |
| R-12 | Baja | Textos truncados: "Load Log" con bloque negro, "Plugins" → "Plugi", "Add b… lane", "Real-Time" TS `179469…`, TS de la tabla `1779024042.846…`. | Ver ribbon Settings y Tools. | `05_ribbon_settings.png`, `24_plot_dual_cursor.png`, `captura_log_grande` | — | CONFIRMADO |
| R-13 | Baja | Filas sin bytes cambiados (primera trama de cada ID) se dibujan tenues con algunas letras (A–D) brillantes en modo Hex. Probablemente efecto de fuente/offscreen, pero es lo que muestran las capturas. | Cargar `log de dos minutos`. | `01_main_loaded_dark.png` (ampliado en `01b_table_dim_rows_crop.png`) | `views/table/decode_line_layout_delegate.py:14-20` (`super().paint`) | CONFIRMADO en captura; causa PLAUSIBLE |
| R-14 | Baja | Orden por ID es alfabético: `1A0` antes que `80`. | Clic en la columna ID. | `83_sort_by_id.png` | `viewmodels/table_model.py` (sort) | CONFIRMADO |
| R-15 | Baja | `Reconectar automáticamente` en español dentro de una UI en inglés. | Connection › SSH. | `05_dbcmanager.png`(dialogo Connection) | `config/ui_text.py:394` | CONFIRMADO |
| R-16 | Baja | Formato de ID: Working DBC y Signal Scan muestran `CF00400` y la tabla `0CF00400`. | Working DBC / Scan. | `19_working_dbc_after_save.png`, `captura_log_grande` | — | CONFIRMADO |
| R-17 | Baja | Formato de tiempo: Events con 6 decimales y epoch crudo, Diff con 2, ejes de Plot/Candidate `1794695000.00`, replay en tiempo relativo. | Ver capturas. | `52_markers_window.png`, `31_diff_*.png`, `70_live_replay_main.png` | — | CONFIRMADO |
| R-18 | Baja | Candidate se ofrece a sí mismo en "Send to". | Clic derecho en el plot del candidato. | `17_send_to_menu.png` | `views/candidate_interpretations_window.py:1136-1146` | CONFIRMADO |
| R-19 | Baja | La grabación continua también guarda los replays. | Conexión › Replay. | `70_live_replay_main.png` (barra "● Recording · canlytics_…replay_log de dos minutos") | `services/continuous_recorder.py` | CONFIRMADO |
| R-20 | Baja | Real-Time muestra "Idle" estando en vivo. | Replay + Real Time. | `71_realtime_live.png` | `views/realtime_analysis_window.py` | CONFIRMADO |
| R-21 | Baja | El mensaje de guardado de señal es largo y se corta en la barra de estado. | Save as signal. | `19_save_signal_filled.png` / `20_table_interpret_on.png` | `views/main_window.py:1292-1304` | CONFIRMADO |
| R-22 | Baja | Ribbon: "Add Plot" y "Bit Map" usan el mismo icono (`chart-line`); "DBC Manager" y "Working DBC", el mismo (`database`). | Ver ribbon. | `05_ribbon_analysis.png`, `01_main_loaded_dark.png` | `views/widgets/ribbon_bar.py` | CONFIRMADO |
| R-23 | Info | `Find correlated candidates…` se niega si hay más de 500 candidatos (con parámetros por defecto y todos los IDs de log candump real, siempre). | Seleccionar todos los IDs y buscar clusters. | (ver §4.5) | `views/candidate_interpretations_window.py:1180-1195` | CONFIRMADO por código; mensaje: ver §4.5 |

---

## 7. Rendimiento con `log candump real de 154 MB`

| Medida | Valor | Cómo |
|---|---|---|
| Tamaño / tramas / IDs | 154 MB / 3 031 318 / 184 | status bar |
| Parseo (hilo de trabajo) hasta `loaded` | **5,5–7,6 s** | `s03/s02` |
| GUI sin responder durante el parseo | **≈6 s** | sonda de `QTimer` (50 ms) |
| Congelamiento posterior (índice de tiempo) | **24,1 s** (segundo log de campo 58 MB: 11,4 s) | misma sonda; perfil `prof1.py` (47 s bajo cProfile) |
| Tiempo desde "abrir" hasta poder usar la tabla | **≈31 s** | suma |
| RAM tras cargar (sin parche) | **2 980 MB** (pico 3 023) | `GetProcessMemoryInfo` |
| RAM tras cargar (con el parche del índice vacío) | **1 244 MB** (pico 2 323) | idem |
| Diferencia atribuible al índice | **≈1,7 GB** | |
| Filtrar a 1 ID (98 824 filas) | 1,9 s | |
| Bus Statistics: abrir | 1,7 s | |
| Bit Activity (todo el log) | 42 s, GUI libre (parón máx 0,23 s), % + ETA | |
| Candidate, 1 ID × 8 bits | 6,0 s (parón 0,85 s) | |
| Candidate, 1 ID × 8–16 bits | 5,1 s | |
| Candidate, 4 IDs × 8–16 bits | 17,3 s (parón 1,4 s) | |
| Diff 10 s vs 10 s | 1,2 s | |
| Diff dos logs completos (log candump real vs otro log candump) | 5,8 s (parón 0,04 s) | |
| Analyze: Matrix | 1,0 s | |
| Real-Time offline: índice | 0,17 s | |
| Signal Scan | 0,24 s | |
| Plot de 98 824 puntos (3 M tramas) | 2,6 s | |

Memoria total del equipo de prueba: 15,6 GB. Con dos instancias de log candump real simultáneas la máquina quedó con 2,5 GB libres (por eso conviene recortar el índice).

---

## 8. Recomendaciones priorizadas

**P0 — rápidas y de gran efecto**
1. **Reescribir `_rebuild_time_index`** (`table_model.py:462`) con operaciones vectorizadas: `ts = df["TS"].to_numpy()`, `np.argsort`, y guardar solo `times` y `rows` como arrays; el `QPersistentModelIndex` por fila no hace falta (usar la fila + generación del modelo). Debe ser O(n) numpy (< 0,5 s para 3 M) y no gastar 1,7 GB.
2. **Corregir el desborde del aviso de memoria**: `Signal(object, object)` (o `float`) en `memory_warning_requested` y su slot; y no marcar `_warning_active = True` hasta que la emisión tenga éxito.
3. **Diálogo de carga con % y ETA** (bytes leídos / tamaño o líneas), y que el parseo no haga starve de la GUI (el worker debe ceder o procesar en chunks).
4. **Candidate: abrir "Configuration" cuando el log tiene IDs de 29 bit / J1939** o subir `max_length` por defecto a 16, y rotular en el estado vacío ("solo 8 bits por defecto; ajusta la longitud en Configuration").

**P1 — resolver duplicados**
5. Un solo XY (quitar la ventana o hacerla pop-out del mismo modo).
6. **Un solo mecanismo de nombrar**: "Tag" → crea/prellena señal en Working DBC; o eliminar tags.
7. Un solo reproductor atado al cursor global.
8. Fusionar Analyze Matrix y Candidate Matrix (y enlazar a Bit Activity).
9. Unificar el cálculo y las unidades del periodo (Bus Stats vs Real-Time).

**P2 — flujo de ingeniería inversa**
10. Ordenar los resultados del Diff por relevancia (p-value, Δ medio, tamaño) y ocultar "Only in A/B" por defecto.
11. Mostrar en el Candidate la **escala sugerida**/valor físico cuando hay referencia, y exponer el empate LE/BE como una sola fila ("start 24 LE ≡ 23 BE").
12. Compartir la selección de IDs entre ventanas (opcional) y mostrar la etiqueta DBC en todas las listas.
13. Insignia "Time filter activo / no aplica" en ventanas que lo ignoran.
14. Hacer legible la lista de candidatos (columnas con score, longitud, endian, tipo).

**P3 — pulido**
15. Terminología única (Bit Activity/Bit Map, Signal Scan/Coverage, Diff Analyzer/Range Diff, Value at Time/Constraint/Value Search, Add Plot/New Plot), ID siempre con 8 dígitos hex en extendidos, tiempo con el mismo formato (2 o 3 decimales) y TS relativo opcional, iconos distintos, icono de "Events", textos truncados, tema Light en Candidate/Analyze, "Idle" en Real-Time, estados vacíos en Scan/Events.
16. Decidir sobre Mux Detection (reexponer, con ayuda, o retirar del build) y sobre grabar replays.

---

## 9. Qué no se pudo probar
- **Hardware en vivo** (registrador CAN, SSH): solo replay. Transmisión real de CAN Send, auto-reconexión SSH, hora del dispositivo por SSH.
- **Formatos de entrada** ASC/BLF/TRC/CSV y **escritura real** de exportación (solo se vieron los diálogos).
- **Importar un plugin**, ejecutar un plugin que añada ventanas, y el servidor MCP.
- **Normalizar timestamp** y zona horaria no "raw" con logs largos; "Append log"; menú de recientes; recuperación de una grabación interrumpida.
- **Captura en vivo larga** (900 fps durante minutos): no hay hardware; solo un replay de 2 min a 10x. Por tanto el estado de F1-01/F1-02 (reordenamiento de filas en Real-Time vivo, pérdida de resultados del Candidate en vivo) **no se re-verificó**.
- **HMI Video/OCR** (congelado).
- **Candidate con referencia real** (CSV / señal DBC): solo se abrió la ventana.
- **Alto DPI, accesibilidad por teclado**, y tema Light en todos los diálogos.
- Todas las capturas son con Qt offscreen y Segoe UI 9: algunos artefactos de texto (R-13) podrían ser propios de ese modo.
