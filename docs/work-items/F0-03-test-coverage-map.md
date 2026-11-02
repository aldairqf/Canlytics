# F0-03 — Actualizar el mapa de cobertura de tests

- **Estado:** Hecho
- **Fase:** 0
- **Rama:** `docs/f0-03-test-coverage-map` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 0546b21

## Problema
`tests/README.md` tenía el conteo y el mapa de cobertura desactualizados respecto a la suite.

## Propiedad
- **Puede editar:** `tests/README.md`, `docs/testing.md`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** código de aplicación, tests, lógica de Mux Detection, HMI/OCR.

## Trabajo
1. Actualizar el conteo real y añadir las entradas de cobertura de exportación y grabación continua.
2. Cerrar la fila del plan.

## Pruebas
- Conteo comprobado con `unittest discover`: 958 tests en 60 archivos.
- La suite completa pasó en D-03 justo antes de esta documentación: 958 tests.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `tests/README.md` y `docs/testing.md`
