# U-12 — Indicador de fuente activa

- **Estado:** Pendiente
- **Fase:** U2 de `docs/plan.md`
- **Rama:** `feat/u-12-active-source-indicator` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** D-01 (datos sin guardar), D-03 (grabación continua)
- **Base commit:** `<hash de dev al crear el worktree>`

## Problema
El usuario pide reconocer qué log está cargado o reproduciéndose: «que se vea que log has cargado o estas reproduciendo; que aparezca la ruta, abajo a la izquierda tal vez o arriba, pero que se vea bien, no solo un parche».

La barra de estado ya informa conexión, FPS, frames, RAM, DBC, filtro y zona horaria. El título actual solo muestra el nombre de la aplicación y la versión (`views/main_window.py:70`). `data_vm.source_paths` (`viewmodels/data_viewmodel.py`) puede contener varios logs añadidos con Append. La conexión distingue replay y conserva su ruta mientras corre (`viewmodels/connection_stream_viewmodel.py`). La grabación continua ya muestra su ruta en un estado aparte. Una captura viva en memoria puede no tener archivo y está marcada como no guardada.

## Propiedad
- **Puede editar:** `views/main_window.py`, `viewmodels/main_window_viewmodel.py` y/o `viewmodels/data_viewmodel.py` para exponer cambios de fuente/estado; `viewmodels/connection_stream_viewmodel.py` solo si hace falta exponer de forma segura el origen activo; `config/ui_text.py`, `docs/ui-design.md`, pruebas del indicador, `docs/plan.md`, `docs/testing.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** formato de logs/parsers salvo necesidad demostrada; Mux Detection; HMI/OCR; servicios de grabación salvo necesidad demostrada.

## Decisiones cerradas
- Diseñar un indicador de sesión integrado a la **izquierda de la barra de estado**, antes de los indicadores permanentes existentes. Ahí puede tener ancho y contraste propios, permanece en una ubicación estable y no compite con los controles del ribbon; concuerda con la petición de ubicarlo abajo y evita que una ruta larga desplace acciones principales.
- El indicador muestra el nombre del archivo y una ruta abreviada con elipsis en el medio cuando sea larga; el tooltip conserva la ruta completa. Con múltiples fuentes se muestra «N archivos» y el menú/tooltip permite consultar sus nombres y rutas.
- Icono acorde al tipo de fuente: log cargado, replay, captura en vivo Kvaser/SSH y múltiples archivos. La etiqueta de sesión indica el tipo de conexión cuando corresponda.
- La captura que aún no se ha guardado muestra un estado claro «Sin guardar», también cuando la captura viva todavía no tiene ruta. La grabación continua conserva la distinción entre archivo capturado y datos de sesión.
- El título de la ventana principal incluye el nombre de archivo activo además de producto/versión; para varios archivos indica el conteo.
- Clic o menú contextual ofrece «Copiar ruta» y «Abrir carpeta» para una fuente única. Con múltiples fuentes, las acciones se aplican a la fuente seleccionada en el submenú. Sin ruta de archivo, se ocultan o deshabilitan.
- Estilo coherente con tokens, iconos y estados de `docs/ui-design.md`, visible en temas claro y oscuro; no es un QLabel aislado.

## Trabajo
1. Definir un modelo de presentación de sesión que derive fuente, tipo, multiplicidad y estado sin guardar de `source_paths`, conexión/replay y estado de captura. Actualizarse al cargar, Append, limpiar, iniciar/detener conexión y guardar la captura.
2. Implementar el indicador completo en la zona izquierda de la barra de estado: icono, nombre/conteo, elipsis central para rutas largas, tooltip detallado, menú contextual, copiar ruta y abrir carpeta.
3. Actualizar el título de la ventana con el nombre de archivo o conteo de archivos, manteniendo producto y versión.
4. Documentar la interacción visual y asegurar contraste en ambos temas.

## Pruebas
- Caracterizar sin datos, un archivo cargado, varios archivos con Append, replay, captura en vivo sin archivo, captura sin guardar y archivo guardado. Verificar actualización al reemplazar/limpiar fuentes y que copiar/abrir carpeta opere sobre la ruta elegida.
- Suite completa verde.
- `/verify-ui`: revisar el indicador en tema claro y oscuro para log único, múltiples archivos, replay, conexión Kvaser/SSH, captura sin guardar y después de guardar; comprobar elipsis/tooltip, menú contextual, título y que los indicadores existentes sigan legibles.

## Cierre
- [ ] CHANGELOG `## Unreleased`
- [ ] fila de `docs/plan.md` cerrada
- [ ] `docs/bugs.md` si aplica
- [ ] `docs/ui-design.md` actualizado
