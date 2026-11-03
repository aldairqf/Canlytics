# F5-07 — Tokens de tema y accesibilidad en flujos activos

- **Estado:** Hecho
- **Fase:** 5 de `docs/plan.md`
- **Rama:** `refactor/f5-07-theme-accessibility` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F5-06
- **Base commit:** `f81d03b`
- **Arquitectura:** [overview](../architecture/overview.md)
- **Diseño UI:** [ui-design](../ui-design.md)

## Problema

`docs/ui-design.md` mantiene pendiente migrar colores literales de vistas y completar accesibilidad con ayudas para jerga, teclado y validación en el diálogo de conexión. El inventario incluye colores de cursores, curvas, categorías de Candidate y el editor de señales derivadas.

## Propiedad

- **Puede editar:** `config/theme.py`, `views/icons.py`, `views/candidate_constraint_search.py`, `views/candidate_interpretations_window.py`, `views/plot/cursor_controller.py`, `views/plot/plot_window.py`, `views/signal/derived_signal_dialog.py`, `views/widgets/sparkline_widget.py`, `views/settings/connection_dialog.py`, `config/ui_text.py`, tests relacionados, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/ui-design.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `views/widgets/hmi_frame_editor_widget.py`, lógica de Mux Detection, servicios/ViewModels fuera del contrato del diálogo, otras tarjetas.

## Decisiones cerradas

- Las vistas leen colores semánticos desde `get_active_theme()`; los colores por categoría y por serie tienen tokens con pares legibles para Dark y Light.
- Los colores negro/blanco calculados en `views/signal/tabs/style_tab.py` se mantienen: calculan contraste contra el color que escoge el usuario. El fallback de icono sin QApplication y los colores de marca del SVG de la app tampoco son tokens de vistas.
- No se modifica HMI/OCR. El tema actual conserva su apariencia salvo en superficies que hoy ignoran el tema.
- El diálogo de conexión ofrece mnemonics/buddy para sus campos, ayudas en los conceptos de timestamp/offset y errores asociados al campo con foco y texto accesible.

## Trabajo

1. Migrar los colores literales de las vistas activas listadas a tokens de tema, ampliando `Theme` con tokens semánticos cuando haga falta.
2. Mejorar el acceso por teclado y el contexto accesible del diálogo de conexión sin cambiar el flujo de conexión ni sus validaciones.
3. Añadir cobertura de ambos temas, tokens y validación accesible; comprobar que no queden colores visuales literales en las vistas incluidas.

## Pruebas

- Suite completa en verde.
- Verificar que los tokens funcionan con tema Dark y Light, que el contraste de texto se mantiene en muestras de ambos extremos y que errores del diálogo se ven y anuncian junto al campo correspondiente.
- `/verify-ui`: capturas de Candidate Search, Candidate Interpretations, Plot con cursores, editor de señal derivada y diálogo de conexión en Dark y Light.

## Cierre

- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md` cerrada
- [x] `docs/ui-design.md`
- [x] Suite completa: 1161 tests en verde; capturas Dark/Light revisadas una por una
- [x] Bug B-35 registrado y corregido con test de regresión
