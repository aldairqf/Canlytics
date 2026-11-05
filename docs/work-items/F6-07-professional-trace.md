# F6-07 — Trace con diferencias y filtros de contenido

- **Estado:** Hecho
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-07-professional-trace` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F2-04, F3-05
- **Base commit:** `65fbe93`
- **Referencias:** [ADR 001](../architecture/decisions/001-streaming-append-delta.md), [ADR 004](../architecture/decisions/004-analysis-context.md)

## Problema

La tabla principal permite ver las tramas pero no resalta qué bytes cambiaron respecto de la
trama anterior del mismo ID ni filtrar por contenido. El usuario debe inspeccionar filas a mano
para seguir una señal en el trace.

## Propiedad

- **Puede editar:** `services/` para la comparación y filtros de trace, `viewmodels/table_filter_viewmodel.py`, `viewmodels/table_model.py`, `views/table/`, `views/main_window.py`, `config/ui_text.py`, pruebas de tabla y servicio, `CHANGELOG.md`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** Mux Detection, HMI/OCR, servicios de análisis no relacionados, arquitectura de streaming O(chunk) ni dependencias.

## Decisiones cerradas

- Comparar cada trama con la anterior del mismo CAN ID en orden de captura; no comparar IDs distintos.
- La comparación de payload indica índices de byte modificados y admite DLC variable.
- Los filtros de byte/máscara/valor/DLC se aplican al contenido crudo y se combinan con AND.
- «Solo con cambios» muestra únicamente tramas donde al menos un byte cambió respecto a la trama anterior del mismo ID; la primera trama de cada ID no cuenta como cambio.
- En vivo, el estado de comparación avanza por deltas crudos y nunca recorre el DataFrame acumulado por flush.

## Trabajo

1. Crear una primitiva Qt-free e incremental para anotar bytes cambiados por ID.
2. Aplicar filtros de contenido al flujo de tabla preservando el filtro completo al cambiar criterios.
3. Exponer controles compactos de filtros y una indicación visual legible en la tabla principal.
4. Documentar y verificar logs offline y captura/replay en vivo.

## Pruebas

- IDs intercalados, primer frame, payload igual/distinto, DLC variable y cortes arbitrarios de chunk.
- Filtros de byte, máscara/valor, DLC y solo cambios; equivalencia incremental con el resultado de referencia.
- Suite completa y `/verify-ui` con log cargado y replay.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa: 1273 tests en verde
- [x] Revisiones de código y MVVM
- [x] Capturas offline revisadas; 1150 filas iniciales y 4 cambios filtrados
