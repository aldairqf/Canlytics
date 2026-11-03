# F4-02 — Registrar y persistir el DBC de trabajo

- **Estado:** Hecho
- **Fase:** 4 de `docs/plan.md`
- **Rama:** `feature/f4-02-working-dbc-persistence` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F4-01
- **ADR:** [003](../architecture/decisions/003-working-dbc.md)
- **Base commit:** `ab9374f`

## Problema

F4-01 ya implementó el servicio editable, pero aún no vive en la app ni sobrevive al reinicio.
`MainWindowViewModel` crea `DbcManager` y restaura DBCs externos; `SessionStateStore` no reserva
ni restaura `.canlytics_state/working.dbc`.

## Propiedad

- **Puede editar:** `services/dbc_manager.py`, `services/session_state.py`, `services/working_dbc.py`,
  `viewmodels/main_window_viewmodel.py`, `tests/test_dbc_manager.py`,
  `tests/test_session_state.py`, `tests/test_working_dbc_persistence.py`, `docs/plan.md`,
  `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** vistas, `main.py`, otras tarjetas F4, DBC externos, Mux Detection, HMI/OCR.

## Decisiones cerradas

- El archivo canónico es `.canlytics_state/working.dbc`; se excluye de la copia de respaldo de DBCs externos.
- La entrada Working DBC permanece activa y se incluye en el orden tras restaurar los DBCs externos.
- Guardar exporta primero de forma atómica y luego reemplaza la base registrada limpiando caches del manager.
- La carga al iniciar usa el worker existente de restauración; no se modifica ningún DBC cargado.

## Trabajo

1. Añadir la ruta canónica y excluirla de la sincronización/restauración de DBCs externos.
2. Inicializar una entrada Working DBC, restaurarla en el worker y mantenerla activa y ordenada.
3. Añadir `save_working_dbc()` para persistir cambios y actualizar `DbcManager` con cachés limpias.
4. Cubrir persistencia entre instancias y decodificación desde el DBC restaurado.

## Pruebas

- Round-trip por archivo `.canlytics_state/working.dbc` temporal; verificar que el DBC fuente externo no cambia.
- Integración QObject/worker de restauración; no construir widgets en `unittest discover`.
- Suite completa en verde: 1111 tests.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` cerrada
- [x] `docs/bugs.md` revisado; sin cambios aplicables
- [x] Suite completa en verde
