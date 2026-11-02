# Changelog

Cambios de Canlytics por versión, escritos para quien usa la app. El trabajo pendiente está
en [docs/plan.md](docs/plan.md). Cada ítem que se cierra agrega su línea en `## Unreleased`
en el mismo commit.

## Unreleased

### Para quien instala
- Los ejecutables de Linux y macOS pesan menos: se quitan los símbolos de depuración y el
  plugin de tema GTK3, que la app no usa.
- `requirements.txt` fija las versiones exactas de todas las dependencias, así que una
  instalación limpia queda igual al entorno probado (PySide6 6.10.1, cantools 41.4.3).

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
