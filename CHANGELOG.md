# Changelog

Cambios de Canlytics por versión, escritos para quien usa la app. El trabajo pendiente está
en [docs/plan.md](docs/plan.md). Cada ítem que se cierra agrega su línea en `## Unreleased`
en el mismo commit.

## Unreleased

- Un cursor global sincroniza la tabla, Plot, Real-Time y Diff; los marcadores de eventos aparecen en las cuatro vistas.
- Real-Time permite inspeccionar un log cargado en el instante del cursor global, recorrer sus posiciones de tiempo y reproducir el registro sin iniciar una captura.
- Candidate permite correlacionar una interpretación con un CSV, una señal DBC, otro candidato o marcadores; muestra el lag y propone escala y offset editables al guardar la señal.
- Los marcadores ON/OFF de eventos se guardan por sesión y permiten comparar automáticamente el intervalo con su línea base anterior.

- Bit Activity muestra en un heatmap qué bits cambian por CAN ID, con límites y clases sugeridos, conteo de muestras e histogramas por byte; los segmentos se envían al flujo común para guardarlos como señales.
- Candidate ordena sus interpretaciones con la actividad y los límites de bits; las sugerencias de signo y endian son heurísticas, y los candidatos de contador y CRC quedan ocultos inicialmente.
- Los plugins habilitados pueden publicar herramientas MCP con argumentos tipados y nombres aislados por plugin.
- Los plugins de confianza pueden añadir ventanas al ribbon, acciones de análisis y recibir datos CAN en vivo; los intentos de transmisión quedan en TX Log y replay no permite enviar.
- La ventana Plugins permite importar carpetas o ZIPs al directorio configurado; el plugin queda desactivado hasta habilitarlo.
- Connect abre la configuración del origen y Start queda desactivado hasta que haya una conexión previa para reanudar.
- La aplicación permite revisar, activar y desactivar plugins de confianza; los errores de un plugin quedan aislados y visibles.
- Los colores de análisis y edición siguen los temas Dark y Light, y Connection ofrece acceso por teclado, explicaciones y errores junto al campo que hay que corregir.
- Plot desconecta sus cursores de los cambios globales de tema al cerrar la ventana.
- Las etiquetas de Analyze Data, Constraint Search y el constructor de señales derivadas se resuelven desde la configuración de textos.
- Los registros candump usan un único parser compartido y se retiraron sus wrappers antiguos sin consumidores.
- Cambiar la normalización de tiempo de un log ya no bloquea la ventana; los datos se actualizan al terminar la recarga y se conserva el estado vigente si hubo cambios concurrentes.
- La hora del dispositivo por SSH y las operaciones de FFT y exportación del plot se delegan a sus ViewModels, conservando los flujos actuales.
- SSH, Kvaser y replay comparten ahora el mismo flujo de recepción, conservando timestamps, bitrate y envío de frames.
- Working DBC ahora tiene una ventana para listar, agregar, editar y eliminar mensajes y señales, y exportar una copia `.dbc` sin sobrescribir DBC cargados.

### Para quien desarrolla
- Los marcadores de sesión se combinan con los marcadores MCP en `AnalysisContext`; `EventMarkersViewModel` conserva sus timestamps al cambiar la normalización.
- El SDK registra herramientas MCP mediante `register_mcp_tool`; el servidor headless solo carga plugins habilitados y les entrega contexto de lectura.
- `canlytics_sdk` registra ventanas, acciones contextuales, handoffs con `AnalysisContext`, listeners O(chunk) y transmisión de frames con los límites de seguridad de CAN Send.
- `canlytics_sdk` define el contexto de datos de solo lectura y los puntos de registro para fuentes DBC, importadores y exportadores de plugins.
- `DbcManager` ya no depende de Qt; el adaptador del ViewModel publica los cambios a la interfaz.
- El DBC de trabajo se registra activo en `DbcManager` y se guarda en `.canlytics_state/working.dbc`, separado de los DBC externos.
- El DBC de trabajo tiene un servicio Qt-free para crear y editar mensajes/señales, validar solapes y exportar archivos `.dbc`.
- El puente MCP local publica el estado de la sesión abierta, sus frames recientes, el contexto de análisis y marcadores efímeros.
- Las herramientas comparten un `AnalysisContext` para trasladar ID, bytes/bits, rangos y origen; el envío al plot ya publica ese contexto.
- El servidor MCP headless usa el SDK oficial y conserva una sesión de análisis por proceso.
- La guía de pruebas muestra el mapa de cobertura por módulo y el conteo actualizado de la suite.
- El flujo de streaming expone deltas de filas e IDs nuevos para que las herramientas incrementales
  procesen solo los datos recién recibidos.
- Los chunks fuera de orden reordenan solo la cola afectada durante la captura.
- La tabla principal filtra e inserta las filas nuevas por lotes, sin comparar todo el historial
  ni refrescar las celdas que no cambiaron.
- Matrix Live detecta movimiento comparando cada chunk con el último estado por CAN ID; solo
  materializa la serie completa cuando aparece un ID o empieza a moverse.
- Plot agrega por chunks los puntos nuevos de fórmulas basadas en señales, bytes o frames, incluso
  cuando alinean varias señales.

### Para quien instala
- Candidate, Diff, Analyze, Plot y la tabla permiten guardar una interpretación como señal en Working DBC con el contexto disponible ya rellenado.
- MCP puede decodificar frames con los DBC activos y guardar señales validadas en el DBC de trabajo de la app abierta.
- Los clientes MCP conectados pueden consultar la captura abierta de Canlytics y añadir marcadores con timestamp, sin copiar el log a otro proceso.
- Main, Real-Time, Analyze y Candidate comparten el selector de CAN ID; Ctrl+F busca un ID y salta a su primer frame en la tabla conservando los demás IDs seleccionados.
- Analyze, Candidate, Coverage, Real-Time y Diff comparten las mismas reglas para medir cambios de valores, manteniendo las clasificaciones y resultados existentes.
- El filtro temporal usa el mismo rango en la tabla, Analyze, Candidate y Mux Detection; el contexto A/B enviado a Candidate conserva sus ventanas.
- La configuración MUX se comparte entre Real-Time, Analyze, Candidate y Diff, y se conserva al reiniciar la aplicación.
- Al enviar un byte del Diff a Candidate, la búsqueda queda limitada al CAN ID, ese byte y las ventanas A/B, sin incluir el tiempo entre ellas.
- El menú contextual permite enviar una señal o candidato a Plot, Candidate, Diff, Analyze o Real-Time conservando su contexto. Working DBC se habilitará cuando exista el editor.
- Analyze Data envía los bytes seleccionados a Plot y a las herramientas de análisis; Constraint Search y Plot también permiten continuar con el candidato o la señal elegidos, conservando el contexto disponible.
- El servidor MCP permite consultar logs, buscar candidatos, comparar rangos y exportar resultados; los archivos de salida van a `~/.canlytics/mcp`.
- XY Plot compara dos señales del Plot en función de sus valores, permite acotar el tiempo y
  exportar los puntos alineados a CSV.
- Diff Live ya no muestra el mensaje para iniciar una comparación mientras espera datos.
- El menú contextual de los frames crudos permite copiar el ID o frame, plotear un byte y abrir
  el ID en Candidate desde la tabla principal y Real-Time.
- Las ventanas secundarias recuerdan tamaño y posición al cerrarse y abrirse de nuevo.
- Las tablas principal y Real-Time muestran TS con seis decimales; la tabla principal reajusta
  el ancho de esa columna al cambiar la zona horaria.
- Time Filter está en Home y el ribbon permite iniciar la última conexión con F5 o detenerla
  con Shift+F5.
- CAN Send muestra texto junto a los íconos de sus acciones y ofrece un botón para agregar el
  primer frame cuando la lista está vacía.
- Analyze Data agrupa Precompute y Free memory en el menú de opciones, deja la toolbar como
  acceso único a los controles de tiempo, muestra “Select a CAN ID” sin selección y ajusta el
  eje Y para series constantes.
- Real-Time muestra los valores únicos en una fila bajo los encabezados B0–B7; la etiqueta del
  período ahora usa los textos configurables.
- Real-Time muestra la columna Delta T. Refresh Interval y Highlight Hold están en Options, y el
  estado de la ventana aparece en su barra inferior.
- La herramienta Bus Statistics muestra fps globales y por CAN ID, períodos y jitter, y señala
  IDs nuevos o que dejaron de aparecer. La barra resume la actividad; la carga del bus es una
  estimación disponible cuando se conoce el bitrate Kvaser. Si las marcas de tiempo llegan fuera
  de orden, los períodos y jitter de ese ID quedan en blanco en vez de mostrar cifras erróneas.
- La barra de estado reúne conexión, fps, frames, RAM, DBC, filtro de tiempo y zona horaria. Si
  el proceso se acerca al umbral configurable de memoria, puedes guardar la captura completa; la
  medición se detiene tras drenar los últimos frames y solo se limpia si el guardado termina bien.
  Canlytics nunca descarta datos automáticamente.
- Los ejecutables de Linux y macOS pesan menos: se quitan los símbolos de depuración y el
  plugin de tema GTK3, que la app no usa.
- `requirements.txt` fija las versiones exactas de todas las dependencias, así que una
  instalación limpia queda igual al entorno probado (PySide6 6.10.1, cantools 41.4.3).

### Logs
- Se pueden abrir logs candump, Kvaser, ASC, BLF, TRC y CSV.
- Las capturas se pueden guardar en candump, ASC, BLF, TRC o CSV. Al exportar, elige todos los
  frames, el filtro actual de la tabla o un rango de tiempo; las exportaciones largas muestran
  avance y tiempo estimado y se pueden cancelar.
- El contador de frames de la barra de estado se actualiza al instante al cargar o reemplazar un log.
- CSV no conserva la identidad de bus; las capturas multibus se rechazan en ese formato para
  evitar pérdida silenciosa de datos.
- Las capturas y reproducciones se graban continuamente en candump en segundo plano. La ruta y
  el tamaño aparecen en la barra de estado; al reiniciar tras un cierre inesperado, puedes
  cargar la grabación interrumpida. La carpeta se configura con `continuous_recording_directory`.

### Correcciones
- Al cerrar, limpiar, cargar otro log o iniciar una conexión, Canlytics avisa si hay datos
  de captura sin guardar. Al iniciar una conexión puedes guardarlos, descartarlos, conservarlos
  y agregar la nueva sesión, o cancelar. El guardado incluye los últimos frames recibidos.
- Candidate Interpretations deshabilita la confirmación en Real-Time cuando no hay una captura
  en vivo o replay activo, e indica qué se necesita para habilitarla.
- Diff Live compara los cambios con los chunks crudos de la captura. Las filas nuevas
  ya no se confunden con filas anteriores cuando el orden de los datos cambia.
- Real-Time muestra los timestamps en la zona horaria elegida y actualiza la tabla al
  cambiarla. Los plots abiertos siguen actualizando su eje horario desde Time Config.
- Real-Time deja de procesar tráfico y detiene sus timers al cerrar su ventana; al abrirla,
  empieza una sesión limpia. Cerrar y reabrir la ventana ya no deja errores en segundo plano.
  "Confirm in Real-Time" la abre acotada al CAN ID pedido, y los IDs que aparecen después
  quedan marcados si tenías todos marcados (también en la lista de IDs de la ventana principal).
- CAN Send desactiva los envíos durante la reproducción de un log y explica por qué no están
  disponibles.
- Analyze Data procesa datos en vivo solo con la ventana abierta. Al cerrarla libera la memoria del
  análisis; al reabrirla, la matriz se calcula de nuevo.
- En Real-Time, los CAN ID mantienen su orden de llegada entre actualizaciones: los IDs nuevos
  aparecen al final, y si eliges ordenar por una columna, ese orden se conserva hasta que lo
  limpias con un tercer clic en el encabezado.
- Candidate Interpretations conserva los resultados calculados mientras llegan nuevos datos
  durante una captura en vivo, y también la selección de CAN IDs que hiciste; los limpia
  solo al cargar o reemplazar el log.

### Interno
- `scripts/bench_stream.py` mide también la tabla principal, Real-Time y Plot. La línea base
  con 900 fps y 40 IDs llega a 140.16 ms por flush a los 10 minutos; la tabla principal es el
  mayor costo medido.
- La documentación del proyecto (plan, bugs, pruebas, diseño de UI, arquitectura y
  decisiones) y la configuración de agentes de Claude y Codex ahora viven dentro del repo,
  versionadas con el código. `/release` sigue gitflow: `dev` pasa a `master` solo cuando el
  trabajo está terminado y probado.
- El repo se movió fuera de OneDrive, a `C:\Users\Asus\Proyectos\CANAnalyzer`, y se eliminaron las copias viejas
  de los docs que estaban fuera de git.

## 0.4.0 (2026-07-22)

### Enviar frames al bus
- **CAN Send.** Envía frames únicos o periódicos por Kvaser o SSH, escribiendo el hex a mano
  o eligiendo un mensaje del DBC y llenando sus señales. Incluye un historial de envíos. La
  lista de frames se guarda entre sesiones; los envíos periódicos siempre arrancan apagados.

### Signal Scan
- Exporta a CSV con la geometría completa de cada señal (bit inicial, largo, orden, escala,
  offset, mux), y ese CSV se puede volver a importar como DBC.
- Las señales PDU1 de J1939 se ocultan por defecto, para no ver la misma señal repetida por
  cada dirección.

### DBC
- Importa dos formatos de CSV, "CAI Order" y "DBC Order", detectados solos. Si no reconoce el
  formato, te pregunta cuál es.

### Logs
- Al guardar un log capturado por Kvaser, se anota el bitrate en la primera línea.

### Correcciones
- Las alturas de fila de la tabla ya no se desfasan al cambiar el filtro de CAN ID.

## 0.3.1 (2026-07-22)

### Diff Analyzer (antes Range Diff)
- Compara dos ventanas de tiempo y clasifica qué cambió en cada byte, sin necesidad de DBC.
- Modo Live con baseline: compara lo que va llegando contra un momento capturado.
- Pestaña de plot con las ventanas A y B resaltadas.

### Más
- Ventana de Debug Log y un modo debug persistente.
- Matriz de Analyze Data en vivo: un CAN ID que empieza a moverse aparece solo en la matriz.
- Candidate Interpretations: categorías de señal, pestaña Matrix y detección de fragmentos
  multi-byte. Ahora recuerda los parámetros de búsqueda.

### Rendimiento
- Logs grandes usan bastante menos memoria: en un log real de 4 millones de filas la tabla
  de datos bajó de 415 MB a 172 MB.

### Para quien instala
- Un solo build genera el `.exe` portable y la carpeta. El extractor de video HMI queda
  oculto por ahora.

## 0.3.0 (2026-07-21)

### Conexión
- SSH más resistente: detecta desconexiones silenciosas y puede reconectar solo.
- Kvaser puede probar varios bitrates hasta encontrar el que trae tráfico real.

### Rendimiento
- Las ventanas que se actualizan en vivo (Signal Coverage, Plot) agrupan los repintados.
  Las ventanas cerradas ya no trabajan en segundo plano.

### Correcciones
- Cerrar Plot o Real-Time ahora libera su memoria (antes la ventana solo se ocultaba).

## 0.2.0 y anteriores (2026-06-15 → 2026-07-15)

Primeras versiones:
- carga de logs candump y Kvaser Memorator;
- decodificación con DBC (exact, J1939, BAM);
- plots con señales derivadas, FFT y exportación;
- Analyze Data y Candidate Interpretations;
- Real-Time Analysis;
- interfaz con ribbon y temas claro/oscuro.

El detalle está en `docs/archive/` y en los tags `v0.1.0`…`v0.2.0`.
