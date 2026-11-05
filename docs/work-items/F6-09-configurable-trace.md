# F6-09 — Trace configurable y señales decodificadas

- **Estado:** Hecho
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-09-configurable-trace` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-06, F4-02
- **Base commit:** `a5a03b3`
- **Referencias:** [ADR 003](../architecture/decisions/003-working-dbc.md), [ADR 004](../architecture/decisions/004-analysis-context.md)

## Problema

La tabla principal muestra siempre el mismo conjunto y formato de columnas. El usuario necesita inspeccionar payloads en hexadecimal, decimal o bits, ver el tiempo entre tramas del mismo ID y el nombre de mensaje DBC, y conservar esa disposición entre ejecuciones. La expansión de DATA ya decodifica señales al hacer doble clic cuando Interpret está habilitado; se mantiene y se hace más visible, sin duplicar su lógica.

## Propiedad

- **Puede editar:** `config/defaults.py`, `config/ui_text.py`, `services/session_state.py`, `viewmodels/table_model.py`, `viewmodels/main_window_viewmodel.py`, `views/main_window.py`, `views/main_window_view.py`, `views/table/`, pruebas relacionadas con table/session/main window, `CHANGELOG.md`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** parser y esquema CAN, clasificación de señales, Mux Detection, HMI/OCR, ventanas secundarias fuera de la tabla principal.

## Decisiones cerradas

- Hexadecimal conserva el formato actual; decimal muestra cada byte en base diez y bits muestra ocho bits por byte.
- Δt se calcula sobre la historia CAN antes de aplicar filtros; es la diferencia en segundos respecto de la trama anterior del mismo CAN ID en el orden temporal de origen, no de la fila previa visible ni del orden de sort.
- Name usa el nombre de mensaje que resuelve el DBC activo; si no hay coincidencia, queda vacío.
- La preferencia de columnas y formato se persiste en `window_prefs`; al restaurar se validan claves y valores y se ignoran preferencias inválidas.
- La expansión existente de DATA se conserva: una fila muestra sus señales decodificadas usando el DBC activo y el menú contextual mantiene «Guardar como señal».

## Trabajo

1. Permitir hex/dec/bits y columnas opcionales Δt y Name sin añadir columnas sintéticas al DataFrame de dominio.
2. Calcular Δt antes de filtrar, de forma incremental para filas nuevas y estable al ordenar la vista.
3. Persistir y restaurar el formato y visibilidad de columnas de la tabla principal.
4. Probar formatos, Δt con ordenamientos e IDs intercalados, nombres DBC y preferencias inválidas/restauradas.
5. Verificar visualmente el menú de configuración, la tabla y filas expandidas con DBC.

## Pruebas

- Tests de modelo para los tres formatos y Δt por ID incluso con sort activo, empates y reemplazo de fuente.
- Tests de persistencia con `SessionStateStore` temporal y fallbacks para estado antiguo/dañado.
- Suite completa en verde y verificación en la app con log y DBC temporales.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa: 1296 tests aprobados.
- [x] code-reviewer y qt-mvvm-reviewer: sin defectos restantes.
- [x] Smoke UI: formato decimal, Δt, nombre DBC, preferencias restauradas y expansión de señal; capturas revisadas.
