# U-05 — Ribbon filters and connection controls

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `feat/u-05-ribbon-connection-controls` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 491b2b6

## Problema
Time Filter está en Settings aunque modifica los datos visibles. Iniciar o detener la última
configuración de conexión requiere abrir el diálogo.

## Propiedad
- **Puede editar:** `views/widgets/ribbon_bar.py`, `views/widgets/ribbon_button.py`, `views/main_window.py`, `views/settings/connection_dialog.py`, `config/ui_text.py`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `viewmodels/`, `services/`, Mux Detection, HMI/OCR.

## Decisiones cerradas
- Time Filter pasa al tab Home; Time Config permanece en Settings.
- Home ofrece Start/Stop de la última conexión configurada, con F5 para iniciar y Shift+F5 para detener.
- Si no hay una conexión configurada en esta sesión, F5 abre el diálogo para que el usuario la configure.
- Start conserva la confirmación existente de sesión nueva y el stop cancela el auto-reconnect SSH pendiente.

## Trabajo
1. Reubicar Time Filter a Home y conservar un único callback.
2. Agregar botón global Start/Stop con texto actualizado por el estado de conexión.
3. Añadir F5/Shift+F5 y reutilizar la validación y confirmación del diálogo actual.

## Pruebas
- Suite completa en verde.
- `/verify-ui`: verificar tabs Home/Settings, click de Time Filter, botón de conexión sin configuración y después de configurar; probar F5 y Shift+F5 sin hardware real.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] suite completa: 1021 tests
- [x] UI verificada: tabs, Time Filter, botón Start/Stop y atajos sin hardware
