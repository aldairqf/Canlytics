# D-02 — Exportación de logs en formatos estándar

- **Estado:** Hecho
- **Fase:** D
- **Rama:** `feature/d-02-standard-log-export` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** D-01
- **Base commit:** 4234f36

## Problema
El guardado de capturas escribía candump fila por fila desde el hilo de la UI. El usuario
necesita guardar formatos que usan otras herramientas CAN sin congelar la ventana y elegir
qué parte del log exportar.

## Propiedad
- **Puede editar:** `services/log_export.py`, `viewmodels/log_export_viewmodel.py`,
  `viewmodels/data_viewmodel.py`, `viewmodels/main_window_viewmodel.py`,
  `viewmodels/table_filter_viewmodel.py`, `views/main_window.py`,
  `views/widgets/log_export_dialog.py`, `config/ui_text.py`, las pruebas de D-02,
  `tests/README.md`, `docs/testing.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `scripts/` (F2), lógica de Mux Detection, HMI/OCR.

## Decisiones cerradas
- Formatos: candump (`.log`), ASC (`.asc`), BLF (`.blf`), TRC (`.trc`) y CSV (`.csv`),
  usando los writers y readers de `python-can`.
- El servicio de exportación no importa Qt. Un worker propiedad de un ViewModel procesa los
  mensajes y reporta avance; el diálogo muestra porcentaje y ETA y permite cancelar.
- Alcances: todos los frames, el filtro actual de la tabla (CAN IDs y rango activo) o un rango
  de tiempo elegido con el control existente y su zona horaria.
- El CSV estándar de python-can no incluye la identidad de bus; se rechaza para capturas
  multibus para evitar pérdida silenciosa. Los otros formatos conservan la separación por bus.
- El botón Save de un aviso D-01 siempre guarda todos los frames. Exportar un subconjunto no
  marca como guardada la captura completa.
- Si una acción destructiva requiere Save, detener y drenar primero la captura, tomar un
  snapshot completo, exportarlo y continuar solo si termina bien. Cancelar o fallar conserva
  los datos y el estado sin guardar.
- Una exportación manual durante captura toma un snapshot y no detiene el streaming. Solo se
  limpia `has_unsaved_capture` al terminar si el alcance fue completo y no llegaron frames
  nuevos durante la exportación.
- Escribir a un temporal con la misma extensión y reemplazar el destino al terminar; una
  cancelación o error no deja un archivo parcial en el destino.

## Trabajo
1. Crear un servicio Qt-free que seleccione los frames y los escriba con `python-can`.
2. Crear el worker y ViewModel con progreso, cancelación, error y limpieza de `QThread`.
3. Agregar un diálogo de alcance y conectar Save y Export con los cinco formatos.
4. Conservar D-01: guardar todos los frames antes de cerrar, limpiar, cargar o iniciar otra
   sesión, o cancelar la acción.

## Pruebas
- Regresión de selección por alcance, conversión de frames y round-trip con `can.LogReader`;
  el CSV multibus se rechaza. Cancelación y error no reemplazan el destino existente.
- Suite completa verde: 951 pruebas.
- `/verify-ui`: se verificaron los formatos, el filtro actual, el rango y el progreso/ETA; las
  capturas están en el scratchpad de la sesión.
- Verificación D-01 con replay de campo: 1244 filas en memoria, 1244 frames en archivo y
  flag sin guardar en `False`.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` retirada
- [x] `docs/testing.md` y `tests/README.md` actualizados
