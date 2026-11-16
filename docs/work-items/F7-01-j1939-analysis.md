# F7-01 — Análisis J1939

- **Estado:** Hecho
- **Fase:** 7 de `docs/plan.md`
- **Rama:** `feature/f7-01-j1939-full` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-01, F6-04
- **Base commit:** `4cef7e0`
- **Referencias:** Meta 2026-11 de `docs/plan.md`, [arquitectura](../architecture/overview.md), SAE J1939-21 (data link), SAE J1939-73 (diagnósticos)

## Problema

Canlytics ya extrae PGN, resuelve nombres si hay un DBC J1939 cargado y reensambla BAM. Aún no presenta prioridad/direcciones como columnas, no reensambla RTS/CTS, no interpreta DM1/DTC y no ofrece una lista de nodos detectados.

## Propiedad

- **Puede editar:** `models/j1939.py`, `utils/j1939.py`, `services/j1939_analysis.py`, `services/j1939_transport.py`, `services/bam_reassembly.py`, `services/bam_decode.py`, `viewmodels/table_model.py`, `viewmodels/main_window_viewmodel.py`, `views/main_window.py`, `views/widgets/ribbon_bar.py`, `views/table/trace_settings_dialog.py`, `views/table/trace_filter_bar.py`, nuevas vistas/servicios ViewModel/manager para el monitor J1939, `config/defaults.py`, `config/ui_text.py`, `tests/` de J1939 y tabla, `docs/plan.md`, `CHANGELOG.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** importación de logs, `FRAME_SCHEMA`, matching/decode J1939 existente salvo la reassembly de TP necesaria, CAN TX, Mux Detection, HMI/OCR, y otras tarjetas.

## Decisiones cerradas

- Para identificadores extendidos, PGN/SA/DA/prioridad se derivan del ID; DA solo se presenta para PDU1 y la dirección del byte PS no se trata como PGN.
- Las columnas J1939 son opcionales y sus valores se calculan en el modelo de tabla, sin agregar columnas al DataFrame de dominio ni recorrer el historial al llegar cada chunk; el cálculo completo se activa solo cuando una columna se muestra y usa expresiones Polars.
- Se muestran nombres conocidos de la base incluida o del DBC J1939 activo; para PGN desconocido se conserva el número. No se presenta una lista parcial como catálogo completo ni se redistribuyen datos con licencia SAE.
- Reensamblar BAM y RTS/CTS en un servicio Qt-free; aceptar solo sesiones completas, validar tamaño/paquetes/secuencia y aislar por SA/DA/PGN, con límite de 1785 bytes.
- El monitor J1939 muestra nodos observados mediante Address Claimed y códigos DM1/DTC (SPN, FMI, contador de ocurrencias y lámparas); es diagnóstico pasivo y no envía consultas ni modifica la red.
- Se acepta incluir EDP (bit 25 del ID) al extraer PGN, construir IDs y filtrar con selector J1939; el matching DBC conserva ese mismo PGN extendido.
- Las vistas reciben snapshots del ViewModel y servicios Qt-free. Cálculos sobre logs grandes corren en worker cancelable con progreso/ETA.

## Trabajo

1. Completar extracción/formatos de identificador J1939, nombres conocidos, claims de nodos y decodificación DM1/DTC.
2. Extender reassembly a BAM y conexión RTS/CTS sin cambiar el resultado observable de BAM actual.
3. Añadir columnas configurables al trace y un monitor con nodos y diagnósticos del log/captura actual.
4. Cubrir protocolos, límites, sesiones intercaladas y flujos UI; actualizar la arquitectura, plan y changelog.

## Pruebas

- PDU1/PDU2, prioridad, direcciones y entradas estándar CAN; Address Claimed; DM1 con cero/múltiples DTC y datos truncados.
- BAM actual y RTS/CTS completo, sesiones intercaladas, secuencias inválidas, aborto, timeout y límite de tamaño.
- La tabla calcula metadata solo para filas nuevas durante streaming y mantiene las preferencias.
- Suite completa verde; `/verify-ui` revisa columnas, nodos y DTC desde una captura o fixture.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` retirada
- [x] `docs/bugs.md` revisado; no aplica
- La ronda de correcciones quedó cubierta con regresiones para decodificación DM1, transporte TP, tabla, monitor e hilo real.
