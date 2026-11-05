# F6-04 - Correlación contra referencia

- **Estado:** Hecho
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-04-reference-correlation` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-01, F4-03, F6-03
- **Base commit:** `f8e5786`
- **Referencias:** Meta 2026-11 de `docs/plan.md`, investigación `feature-gap.md` (solo lectura, fuera del repo)

## Problema

Candidate encuentra posibles señales pero no ayuda a relacionarlas con una magnitud conocida. Una referencia temporal permite identificar qué candidato sigue una señal real y estimar su escala y offset para guardarlo como señal DBC.

## Propiedad

- **Puede editar:** `services/reference_correlation.py`, `tests/test_reference_correlation.py`, `models/analysis_context.py`, `tests/test_analysis_context.py`, `viewmodels/reference_correlation_viewmodel.py`, `viewmodels/main_window_viewmodel.py`, `viewmodels/candidate_interpretations_viewmodel.py`, `views/candidate_interpretations_window.py`, `views/candidate_interpretations_window_manager.py`, `views/reference_correlation_window.py`, `views/reference_correlation_window_manager.py`, `views/main_window.py`, `config/defaults.py`, `config/ui_text.py`, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** logics de Mux Detection, HMI/OCR, servicios de detección/ranking ya cerrados ni otros work-items.

## Decisiones cerradas

- Buscar el lag que maximiza la correlación de Pearson o Spearman por ventanas temporales; interpolar la referencia sobre los timestamps del candidato y no recorrer el DataFrame acumulado por flush.
- Aceptar referencias de dos columnas tiempo/valor en CSV, señales decodificadas del DBC, otro candidato y estados ON/OFF de marcadores de evento.
- Ajustar `referencia = candidato * escala + offset` sobre las muestras alineadas del mejor lag; redondear como sugerencia editable, nunca como verdad ni poda de candidatos.
- Mostrar correlación, lag, muestras y ventanas para que el usuario evalúe la evidencia.
- Pasar ID, geometría y sugerencias de escala/offset por `AnalysisContext` al diálogo existente de Guardar como señal.

## Trabajo

1. Crear servicio Qt-free con normalización de series, búsqueda por lag, correlación por ventanas y ajuste lineal redondeado.
2. Añadir prueba para cada métrica, lags positivos/negativos, referencias discontinuas, valores constantes y ventanas con datos insuficientes.
3. Integrar fuentes CSV, DBC, candidato y marcadores desde Candidate Interpretations; cargar archivos y calcular fuera del hilo GUI.
4. Mostrar el resultado como evidencia y enviar la geometría y escala/offset sugeridos al flujo Guardar como señal.
5. Actualizar arquitectura, textos, mapa de tests, plan y changelog.

## Pruebas

- Regresión de correlación con series sintéticas de lag conocido y escala/offset conocidos.
- Suite completa verde; el servicio se importa sin Qt ni hardware.
- `/verify-ui`: probar CSV y DBC como referencias, revisar lag/coeficiente/sugerencias y guardar una señal; comprobar Dark/Light y que la UI siga respondiendo durante el cálculo.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] Suite, revisiones code-reviewer y qt-mvvm-reviewer
- [x] Capturas de UI revisadas
