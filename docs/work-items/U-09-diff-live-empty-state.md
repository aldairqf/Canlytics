# U-09 — Diff Live empty state

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `fix/u-09-diff-live-empty-state` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** ce9e40a

## Problema
El texto “Run a comparison…” aparece también mientras Diff Live está capturando el baseline y
esperando que llegue el primer resultado.

## Propiedad
- **Puede editar:** `views/range_diff_window.py`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `viewmodels/`, `services/`, Mux Detection, HMI/OCR.

## Decisiones cerradas
- El estado vacío solo se oculta mientras Live esté activo y no haya resultados visibles.
- Si Live se detiene sin resultados, el estado vacío vuelve a mostrarse.

## Trabajo
1. Actualizar el estado vacío al cambiar el modo Live y al cambiar los resultados visibles.
2. Mantener el mensaje cuando una comparación normal no produce resultados.

## Pruebas
- Suite completa en verde.
- `/verify-ui`: alternar Live sin resultados y confirmar que el texto vacío aparece solo al salir de Live.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] suite completa (1027 tests) y UI verificada
