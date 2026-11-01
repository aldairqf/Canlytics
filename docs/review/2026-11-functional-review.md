# Revisión funcional de Canlytics — 2026-11-01

**Alcance:** se revisaron todas las ventanas a las que el usuario puede llegar, cómo se
conectan entre sí y qué tan uniformes son, el rendimiento en captura larga y la deuda de
arquitectura.

**Método:** tres exploraciones en paralelo sobre el código (inventario de features,
pipeline de streaming con Real-Time, y el repo de referencia gestion-pyme), un benchmark
del pipeline y la medición de los logs reales de Fase 02.

**Verificación:** los hallazgos marcados con ✔ los comprobé directamente en el código. El
resto viene de las exploraciones con `archivo:línea`. Hay que confirmarlos al abrir la
tarjeta correspondiente, porque el código puede haber cambiado.

## 1. Resumen

La app tiene herramientas potentes para detectar señales: Diff Analyzer, Candidate,
Analyze, Signal Coverage y Real-Time. Pero **funcionan como islas**:
- Cada una reimplementa sus propios conceptos (rango de tiempo, mux, "qué cambió", selector de ID).
- Solo Plot recibe resultados de las demás, y Plot no envía nada a ninguna parte.
- **No existe una forma de guardar una señal encontrada** como señal DBC.

Por eso la ingeniería inversa termina siendo manual: el usuario lleva la evidencia de una
ventana a otra en la cabeza.

En vivo hay dos problemas concretos que dañan el trabajo de campo:
1. La app se vuelve lenta con la duración de la captura, porque varios consumidores
   recalculan sobre todo el log en cada flush.
2. Real-Time reordena sus filas solo, y eso impide seguir con la vista los cambios de un byte.

## 2. Cómo trabaja el usuario (flujo objetivo)

1. Se conecta al equipo (Kvaser, ~900 fps, ~40 IDs).
2. Mueve un actuador y observa qué IDs y bytes reaccionan (Real-Time, Diff Live).
3. Propone una interpretación: bits, orden, signo, escala (Candidate).
4. La confirma visualmente (Plot).
5. Le pone nombre y la guarda para reutilizarla en tabla, plot y real-time (**esto no existe hoy**).

Cada paso tiene que recibir el **contexto** del anterior: ID, bytes y ventana de tiempo.

## 3. Inventario (15 ventanas)

| Ventana | Offline / en vivo | Recibe de | Envía a | Observación |
|---|---|---|---|---|
| Tabla principal + panel de IDs | Ambos | log, conexión | Plot (solo desde una línea ya decodificada por DBC) | Un byte crudo o un ID no tiene menú contextual |
| DBC Manager | — | archivos | decodificación | Solo lectura: no crea ni edita señales |
| Conexión (SSH/Kvaser/replay) | En vivo | — | todo el pipeline | — |
| Real-Time Analysis | Solo en vivo | `chunk_ready` | Diff Live ("Compare from now") | No tiene menú contextual; no puede enviar a Plot ni a Candidate |
| Plot (derivadas, FFT, cursor, export) | Ambos | tabla, Candidate, Diff, Coverage | nada | Es un sumidero. Sin filtro de tiempo. Las derivadas se recalculan completas |
| Analyze Data (+ Matrix) | Ambos | dataframe | nada | Callejón sin salida |
| Candidate Interpretations (+ Matrix, tags) | Offline | dataframe, IDs | Plot, "Confirm in Real-Time" | ✔ En vivo borra sus resultados en cada flush |
| Constraint Search | Offline | candidatos | nada | Su ventana de resultados no permite plotear ni etiquetar |
| Signal Coverage / Scan | Ambos (solo el último valor) | DBC + dataframe | Plot; CSV que se reimporta como DBC | No envía a Candidate (ROADMAP P1.1 decía que sí) |
| Diff Analyzer | Por lotes + en vivo | dataframe | Plot (byte), Candidate (**solo el ID**) | ✔ El modo en vivo usa un watermark por filas, que no es seguro |
| CAN Send | En vivo | DBC | bus | Habilitado en replay aunque el envío falla |
| Time Config / Time Filter | — | — | — | El filtro de tiempo solo afecta a la tabla principal |
| Debug Log, About, Tema | — | — | — | Independientes |
| Mux Detection | **Inalcanzable** | — | — | Se crea su ViewModel, pero nunca se cablea. Congelado |
| HMI Video OCR | **Inalcanzable** | — | — | ✔ El manager nunca se construye. Congelado |

## 4. Hallazgos y cómo mejorarlos

### 4.1 Real-Time reordena las filas ✔ (crítico para el usuario) → F1-01
- **Qué pasa:** cuando llega un ID nuevo, aparece arriba. Cuando un ID se demora, baja. Con "Changes only" se nota más.
- **Causa:**
  - `views/table/table_view.py:14` activa `setSortingEnabled(True)`. Con eso Qt llama implícitamente a `model.sort(0, Descending)` y la columna 0 es TS.
  - `TableModel.sort` guarda ese orden incluso con la tabla vacía.
  - Desde el commit `509fc98` (fix B-09), `set_dataframe` reaplica el orden en cada tick de 100 ms.
  - El test de B-09 no lo detectó porque usa un `TableModel` sin vista.
- **Mejora:** sin orden implícito; cada ID en una posición fija (orden de aparición), con los nuevos al final. Si el usuario elige un orden, que sea estable (`maintain_order`) y que pueda volver al orden natural con un tercer clic en el header. Conviene bloquear el orden por TS y ΔT, porque cambian en cada tick y no pueden ser estables.

### 4.2 Lentitud en captura larga ✔ (crítico) → Fase 2
- **Medición:** el costo por flush crece lineal con las filas acumuladas.
  - Con el perfil real (900 fps, 40 IDs), cuatro etapas suman 4.3 ms por flush a los 5 min y 30.2 ms a los 20 min (`scripts/bench_stream.py`). La que más crece es el filtro de tabla, que nunca hace rechunk.
  - Fuera de esa medición, `_same_row_identity` de `TableModel` agrega 9.6 ms a 1.8M filas.
  - A eso se suman el repintado, Real-Time y Plot.
- Además:
  - se re-ordena todo el df cuando un chunk llega desordenado;
  - Matrix Live filtra el df completo por cada ID quieto;
  - ✔ Real-Time mantiene sus timers activos aunque su ventana no exista;
  - Analyze Data recalcula aunque su ventana esté cerrada.
- **Mejora:** contrato append-delta (ADR 001). Cada consumidor trabaja solo sobre lo nuevo. Sin tope de RAM, con un guardián de memoria (ADR 002).

### 4.3 Candidate pierde sus resultados en vivo ✔ → F1-02
`set_dataframe` llama a `_clear_results()` en cada flush (`candidate_interpretations_viewmodel.py:139-144`). Mientras se captura, los resultados desaparecen cada 100 ms. Solo deben limpiarse cuando el log se reemplaza.

### 4.4 Los traspasos pierden contexto → F3-01, F3-02
Diff → Candidate pasa solo el CAN ID (`range_diff_window.py:590`). Se pierden el byte que reaccionó y la ventana A/B, y Candidate vuelve a buscar en todo el log. **Mejora:** un `AnalysisContext` (ID, bytes, rango, mux, origen) que viaje con cada "Enviar a…".

### 4.5 No se puede guardar una señal encontrada → Fase 4
`DbcManager` es de solo lectura. Las etiquetas de Candidate se guardan como TXT `label = name`, sin geometría. **Mejora:** un DBC de trabajo editable (ADR 003) y "Guardar como señal" en todas las ventanas de detección. Las señales guardadas decodifican al instante en tabla, Real-Time y Plot.

### 4.6 Conceptos duplicados y no uniformes → Fase 3

| Concepto | Hoy | Propuesta |
|---|---|---|
| Rango de tiempo | 4 implementaciones con estado propio (tabla, Analyze, Candidate solo de display, Diff timeline, Constraint) | Un solo componente y estado; el rango viaja en el contexto |
| Configuración de mux | 3 copias (Real-Time, Analyze, Candidate), ninguna persistida | Una sola, persistida en `session_state` |
| "Qué cambió" | 5 lógicas (Diff `classify_byte`, Real-Time frame a frame, Analyze `np.diff`, Coverage `unique>=2`, Candidate `classify_signal_type`) | Una taxonomía en `services/range_diff.py` |
| Selector de CAN ID | 4 widgets distintos | `CanIdPanelWidget` en todas, más un buscador global Ctrl+F |
| Selección de bytes | Checkboxes, menú con bit inicial fijo, spinboxes, texto | Que venga del contexto |
| "Agregar al plot" | Helper compartido en 2 ventanas, menús propios en otras 2 | Menú común "Enviar a…" |
| Formato de tiempo | Real-Time ignora la timezone; `PlotWindowManager.set_timezone` nunca se llama | F1-07 |
| Persistencia de preferencias | Solo Candidate y Diff | Todas las ventanas con parámetros |

### 4.7 Otros problemas para el usuario
- "Confirm in Real-Time" offline abre una ventana vacía, porque Real-Time solo recibe datos de la conexión (F1-08).
- CAN Send está habilitado en replay y el envío falla (F1-06).
- Hay strings en inglés hardcodeados: menú del plot, Constraint Search, "Period [s]" y los diálogos de cierre (F5-06).
- No hay forma de saltar a un CAN ID desde cualquier ventana (F3-06).

### 4.8 Deuda de arquitectura → Fase 5
- `services/dbc_manager.py` es un `QObject`.
- `connection_dialog.py` tiene un `QThread` que abre SSH.
- `plot_window.py` llama a FFT y export directamente.
- `connection_stream_viewmodel.py` (547 líneas) contiene lógica de hardware.

Código muerto:
- `PipelineBuilder` (984 líneas, Basic Mode cancelado);
- `can_frame_formatter.py` y `candump_parser.py`, que no importa nadie;
- `RealTimeAnalysisViewModel.set_enabled`, que nadie llama.

### 4.9 Documentación desactualizada (corregido en esta rama)
- `CLAUDE.md` y `AGENTS.md` eran duplicados de unas 1700 líneas, fuera de git.
- Decían que HMI seguía accesible, cuando no lo está.
- Ubicaban `LiveByteAccumulator` en el archivo equivocado.
- Describían un `CandidateMatrix*` que no existe.
- Mostraban un diagrama de cableado distinto del real.

Ahora la fuente es `docs/architecture/overview.md`.

## 5. Prioridad recomendada

1. **F1-01 y F1-02**: los dos problemas que más afectan el trabajo de campo y los de menor esfuerzo.
2. **Fase 2 (streaming)**: elimina la causa de "hay que borrar los datos".
3. **Fase 3 y Fase 4 (contexto + DBC de trabajo)**: convierten las islas en un pipeline y quitan el trabajo manual de detección.
4. **Fase 5**: deuda interna, sin cambios visibles.
