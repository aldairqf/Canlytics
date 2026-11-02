# F2-08 — Abrir logs en formatos estándar

- **Estado:** Hecho
- **Fase:** 2
- **Rama:** `feat/f2-08-standard-log-import` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** D-02
- **Base commit:** 4687d35

## Problema
La app puede exportar candump, ASC, BLF, TRC y CSV, pero `load_can_dataframe()` solo reconoce
candump y Kvaser Memorator. Los logs estándar exportados no pueden volver a abrirse en la app.

## Propiedad
- **Puede editar:** `services/can_data_parser.py`, `config/ui_text.py`, `views/main_window.py`,
  `viewmodels/measurement_status_viewmodel.py`, `tests/test_can_data_parser.py`,
  `tests/test_log_import.py`, `tests/test_measurement_status_viewmodel.py`, `tests/README.md`,
  `docs/testing.md`, `docs/architecture/overview.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** exportación D-02, `requirements.txt`, lógicas de Mux Detection y HMI/OCR,
  logs reales del usuario.

## Decisiones cerradas
- Todos los formatos se cargan mediante el `load_can_dataframe()` Qt-free compartido por `CANLog`
  y replay; los readers de `python-can` se importan de forma perezosa.
- ASC se lee con `relative_timestamp=False` para preservar timestamps absolutos de los archivos
  exportados por D-02. BLF, TRC y CSV usan el reader de `python-can` seleccionado por extensión.
- El canal del formato se representa como `canN`; CSV, que no almacena identidad de bus, se carga
  como `can0`. Los archivos de campo no se reescriben.
- La importación conserva `FRAME_SCHEMA` y la opción actual de normalizar tiempo. Rechaza CAN FD,
  frames de error y remotos que el esquema actual no puede representar, en vez de truncarlos o
  transformarlos silenciosamente. Kvaser y candump mantienen su parser existente.

## Trabajo
1. Detectar ASC, BLF, TRC y CSV por extensión sin leer binarios como texto.
2. Adaptar mensajes `python-can` a `FRAME_SCHEMA` y aplicar la normalización temporal compartida.
3. Ampliar el diálogo de apertura y el drag & drop; comprobar que el replay usa el mismo cargador.
4. Publicar al instante el conteo de frames tras cargar o reemplazar un log.
5. Caracterizar cada formato con round-trip de D-02, rechazar frames no representables y actualizar
   arquitectura/documentación.

## Pruebas
- Para ASC, BLF, TRC y CSV: exportar una muestra y volver a cargarla; comprobar timestamps, ID,
  payload, canal y esquema. ASC debe conservar epoch absoluto.
- Los frames CAN FD, de error y remotos se rechazan con un error claro para no perder información.
- Candump y Kvaser existentes siguen pasando sin regresiones.
- `/verify-ui`: abrir un log exportado de cada formato desde el diálogo; verificar filas, IDs,
  timestamps y replay de al menos un formato nuevo.
- Suite completa verde.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/testing.md` y `tests/README.md`
- [x] Suite completa y verificación UI

## Evidencia
- Suite completa: 1014 tests, todos pasan; `code-reviewer` y `qt-mvvm-reviewer`: ship.
- Round-trip de logs ASC, BLF, TRC y CSV: la tabla mostró 3, 3, 3 y 2 filas respectivamente,
  con IDs, datos, canales y timestamps correctos. ASC conservó el epoch absoluto.
- Replay de TRC por el mismo cargador: agregó los 3 frames al log abierto. Capturas revisadas
  fuera del repo en `%TEMP%/canlytics-f208/`.
