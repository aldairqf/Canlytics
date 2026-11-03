# F5-06 — Completar anotaciones y textos de tres flujos activos

- **Estado:** Hecho
- **Fase:** 5 de `docs/plan.md`
- **Rama:** `refactor/f5-06-i18n-annotations` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-05
- **Base commit:** `19586cb`
- **Arquitectura:** [overview](../architecture/overview.md)

## Problema

Hay 22 módulos Python sin `from __future__ import annotations` en `config/`, `models/`,
`services/`, `utils/`, `viewmodels/` y `views/`. Además, los flujos activos de Analyze Data,
Constraint Search y el constructor de señales derivadas muestran etiquetas y botones directamente
en el código en vez de resolverlos con `get_text()`.

## Propiedad

- **Puede editar:** los 22 módulos que carecen de `from __future__ import annotations` al iniciar
  la tarjeta; `views/analyze_data_window.py`, `views/candidate_constraint_search.py`,
  `views/signal/pipeline_builder.py`, `config/ui_text.py`, sus tests, `docs/plan.md`,
  `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** lógica Mux Detection, HMI/OCR, otras vistas/servicios/ViewModels,
  otras tarjetas.

## Decisiones cerradas

- Los valores persistidos o usados como datos (`exact`, `j1939`, nombres de operación y bytes) no
  se traducen; solo etiquetas visibles.
- Las claves nuevas van en `config/ui_text.py` y las vistas las obtienen con `get_text()`.
- Los imports futuros se agregan sin reformatear el resto del módulo.

## Trabajo

1. Agregar anotaciones futuras en los módulos que faltan.
2. Internacionalizar las etiquetas estáticas de los tres flujos listados.
3. Mantener estables los valores internos y probar las etiquetas y operaciones visibles.

## Pruebas

- Tests de valores estables en controles del constructor y de textos vía `get_text()`.
- Suite completa en verde y capturas de Analyze Data, Constraint Search y Pipeline Builder revisadas.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] Suite completa en verde: 1152 tests
- [x] Capturas revisadas: Analyze Data, Constraint Search y Pipeline Builder

## Evidencia

- `tests/test_f5_06_i18n.py` cubre el texto de tiempo y los valores almacenados en los combos de fuente, endianess, tipo y transformación.
- Suite completa: `Ran 1152 tests ... OK`.
- Capturas verificadas en `%TEMP%\canlytics-f506-verify`.
