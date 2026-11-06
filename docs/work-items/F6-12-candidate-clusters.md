# F6-12 — Agrupar candidatos correlacionados

- **Estado:** Hecho
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-12-candidate-clusters` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F6-04
- **Base commit:** `607c1c3`
- **Referencias:** Meta 2026-11 de `docs/plan.md`, investigación `feature-gap.md` (solo lectura, fuera del repo)
- **Arquitectura:** [overview](../architecture/overview.md), [ADR 004](../architecture/decisions/004-analysis-context.md)

## Problema

Candidate muestra muchas interpretaciones ordenadas, pero no ayuda a reconocer señales de distintos IDs que siguen la misma magnitud o son redundantes. La investigación de referencia propone agrupar candidatos correlacionados para encontrar señales hermanas.

## Propiedad

- **Puede editar:** `services/candidate_correlation.py`, `viewmodels/candidate_interpretations_viewmodel.py`, `views/candidate_interpretations_window.py`, `views/candidate_correlation_dialog.py`, `config/defaults.py`, `config/ui_text.py`, `tests/test_candidate_correlation.py`, `docs/plan.md`, `CHANGELOG.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** generador y ranking de candidatos, servicios de detección, Mux Detection y HMI/OCR.

## Decisiones cerradas

- Agrupar por correlación de Spearman contemporánea; no buscar lag ni usar una correlación como confirmación de señal.
- Comparar solo los candidatos visibles después de los filtros actuales, con límite explícito; no cambiar score, eliminar candidatos ni reordenar la lista.
- Alinear series por tiempo con interpolación solo dentro de huecos compatibles con su cadencia; requerir muestras suficientes.
- Ejecutar el cálculo en un `QThread` con progreso, ETA y cancelación. Mostrar coeficiente y muestras en un diálogo; el usuario puede saltar a un candidato.
- La agrupación es una herramienta opcional y solo se calcula cuando el usuario la solicita.

## Trabajo

1. Crear el servicio Qt-free que alinea candidatos y devuelve grupos con coeficientes y muestras.
2. Añadir un worker cancelable en el ViewModel para ejecutar la agrupación de candidatos visibles.
3. Añadir una acción en Candidate Interpretations y un diálogo de grupos con navegación al candidato elegido.
4. Documentar límites, señales de evidencia y pruebas.

## Pruebas

- Regresión para correlación positiva/negativa, series asincrónicas, huecos grandes, constantes, insuficientes, sin coincidencias y cancelación.
- Suite completa verde; el servicio se importa sin Qt.
- `/verify-ui`: filtrar candidatos, calcular grupos, abrir un miembro y cancelar un cálculo.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` eliminada
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite completa: 1317 tests en verde
- [x] Revisión de código y MVVM aprobadas
- [x] Verificación visual: agrupación y navegación al candidato
