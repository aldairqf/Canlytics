# F6-08 — Comparar dos logs

- **Estado:** Hecho
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-08-compare-logs` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-05, D-02
- **Base commit:** `3a4b9a2`
- **Referencias:** [ADR 001](../architecture/decisions/001-streaming-append-delta.md), [ADR 004](../architecture/decisions/004-analysis-context.md)

## Problema

Diff compara dos rangos temporales del log actual. Para comparar una referencia y una acción
registradas en archivos separados, el usuario tendría que importarlos y preparar una sesión
manual antes de ver las diferencias.

## Propiedad

- **Puede editar:** `services/range_diff.py`, `viewmodels/range_diff_viewmodel.py`, `viewmodels/range_diff_worker.py`, `views/range_diff_window.py`, `config/ui_text.py`, pruebas de range diff, `CHANGELOG.md`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** parser/exportador de logs salvo que una regresión concreta lo exija, otras vistas de análisis, Mux Detection, HMI/OCR.

## Decisiones cerradas

- El usuario elige un log base (A) y uno de acción (B); se compara el contenido completo de cada archivo por CAN ID y bytes usando la clasificación existente de `range_diff`.
- La selección es de solo lectura y no reemplaza ni altera el log que ya está abierto en Canlytics.
- Los archivos se cargan y comparan en un worker Qt propiedad del ViewModel; cerrar/cancelar conserva limpia la ventana y los datos principales.
- La exportación CSV y los filtros existentes operan sobre el mismo `RangeDiffReport`.
- La comparación de dos archivos se distingue del modo actual de dos rangos temporales y permite volver a él.
- Cancelar se comprueba después de cargar cada archivo y durante la clasificación; no interrumpe el parser a mitad de un archivo.

## Trabajo

1. Extraer la construcción de reportes para aceptar dos DataFrames independientes.
2. Cargar los dos logs y ejecutar el reporte en el worker de Diff.
3. Añadir la selección de archivos, estado visible y retorno al modo de rangos.
4. Verificar clasificación, errores/cancelación, aislamiento del log principal y exportación.

## Pruebas

- IDs comunes y exclusivos, cambios de bytes, LEN y DLC, y equivalencia con clasificar los dos grupos directamente.
- La vista-modelo conserva el DataFrame principal y usa ambos archivos; fallos no sustituyen el reporte válido anterior.
- Suite completa y `/verify-ui` con dos archivos distintos.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado (no aplica)
- [x] Suite, revisiones y capturas revisadas
