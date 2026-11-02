# F3-03 — Configuración MUX única y persistida

- **Estado:** Hecho
- **Fase:** 3 de `docs/plan.md`
- **Rama:** `feature/f3-03-shared-mux` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-01
- **Base commit:** `7135132`

## Problema
Real-Time, Analyze y Candidate mantienen listas independientes de `MuxConfigEntry` en sus ViewModels; se reinician vacías y Diff no tiene acceso al editor. Una regla cambiada en una herramienta no llega a las demás ni sobrevive al reinicio, aunque ADR 004 define una sola configuración compartida y persistida.

## Propiedad
- **Puede editar:** `models/mux_config.py`, `services/session_state.py`, `services/analyze_data.py`, `viewmodels/main_window_viewmodel.py`, `viewmodels/mux_configuration_viewmodel.py`, `viewmodels/analyze_data_precompute_worker.py`, ViewModels de Analyze, Candidate y Range Diff, ventanas/managers de Real-Time, Analyze, Candidate y Range Diff, `views/settings/mux_configuration_dialog.py`, pruebas relacionadas, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `CHANGELOG.md`, `docs/architecture/overview.md`, esta tarjeta.
- **No puede editar:** lógica de Mux Detection, HMI/OCR, servicios de streaming, cálculo de la taxonomía de Range Diff (F3-05), otras tarjetas.

## Decisiones cerradas
- Un `MuxConfigurationViewModel` del composition root es la fuente única de reglas.
- Las reglas se guardan en `SessionStateStore` y se restauran al iniciar; el JSON existente y sus claves ajenas se conservan.
- Las cuatro herramientas editan el mismo conjunto mediante `MuxConfigurationDialog`; al aceptar un cambio todas reciben la configuración actualizada.
- Una regla con LEN exacto tiene prioridad para ese largo; la regla wildcard se usa para los demás. No se aceptan reglas contradictorias para la misma pareja ID/LEN.
- `MuxConfigEntry` y el almacenamiento permanecen Qt-free; la lógica congelada de Mux Detection no se conecta ni modifica.

## Trabajo
1. Añadir lectura/escritura validada de reglas MUX en `SessionStateStore` y un ViewModel Qt que las cargue, publique y persista.
2. Conectar Real-Time, Analyze y Candidate al estado compartido, quitando sus listas independientes y refrescando el análisis cuando cambie la regla.
3. Añadir acceso al mismo editor compartido desde Range Diff para que el usuario pueda mantener las reglas desde cualquiera de las cuatro herramientas.
4. Cubrir restauración, validación, actualización en vivo entre herramientas y preservación de otras claves de sesión.
5. Cerrar tarjeta, plan, CHANGELOG, mapa de pruebas y arquitectura.

## Pruebas
- Regresión primero: persistencia/validación de reglas; dos consumidores ven cada cambio; restaurar conserva el estado previo.
- Suite completa verde.
- `/verify-ui`: cambiar una regla desde cada una de las cuatro herramientas, confirmar propagación y reinicio de la app conservando la regla.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] `docs/bugs.md` revisado; no aplica
- [x] Suite y verificación de UI
