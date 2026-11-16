# U-11 — Enviar bytes de Analyze a un plot

- **Estado:** Pendiente
- **Fase:** U2 de `docs/plan.md`
- **Rama:** `feat/u-11-analyze-bytes-to-plot` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-01 (AnalysisContext), F4-03 (configurar/guardar señal), U-03 (Analyze Data)
- **Base commit:** `<hash de dev al crear el worktree>`

## Problema
El usuario pide que desde Analyze se pueda enviar una señal a otra pantalla o a un plot nuevo: «desde la ventana Analyze, cuando ves los bytes haces clic derecho y salen las opciones por defecto, pero deberia poder anadirse a un plot o abrir un nuevo plot, al menos que se autocomplete el CAN ID y abra la configuracion; o si le haces clic a una de las senales, que se pueda ir a add new plot; eso sirve para mandar una senal a otra pantalla».

La ventana ya tiene botón de toolbar «Send to» (`views/analyze_data_window.py`, `_open_send_to_menu` y `_send_selected_bytes_to_plot`) y los destinos compartidos en `views/plot/add_to_plot_menu.py` (`show_send_to_menu`, `analysis_send_destinations`). El menú contextual de celdas/bytes y el de señales/series no ofrece esos destinos. El patrón de contexto reutilizable está en `views/table/frame_context_menu.py`; `AnalysisContext` conserva CAN ID, bytes/bits y origen.

## Propiedad
- **Puede editar:** `views/analyze_data_window.py`, `views/plot/add_to_plot_menu.py`, helpers de menú contextual de Analyze si se extraen; ViewModel solo si hace falta el flujo de configuración de señal; `config/ui_text.py`; pruebas de contexto/handoff; `tests/README.md`, `docs/testing.md`, `docs/plan.md`, `docs/ui-design.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** servicios de análisis sin necesidad demostrada; Mux Detection; HMI/OCR; lógica de otras ventanas fuera del cableado estrictamente necesario.

## Decisiones cerradas
- Tanto el menú contextual sobre bytes seleccionados como el menú contextual de una señal/serie ofrecen «Añadir al plot actual», «Nuevo plot» y «Configurar señal...».
- «Configurar señal...» abre el diálogo de configuración de señal de Plot con CAN ID, bytes/bits y contexto de análisis ya rellenados. Se reutiliza el handoff existente con `AnalysisContext`; no se crea un segundo flujo de configuración.
- El botón «Send to» y los menús contextuales comparten una única fuente de acciones/destinos y constructores de contexto. No duplicar lógica de creación de señal, selector exacto, destino de plot ni persistencia del contexto. Seguir el patrón de `views/table/frame_context_menu.py` para menú reusable.
- **Alcance:** Analyze Data, sus bytes seleccionados y sus señales/series. Candidate y Bit Activity ya tienen acciones «Send to»/destinos de análisis y plot; comprobar que siguen funcionando, pero no rediseñarlos. Real-Time tiene acciones de frame crudo para plotear bytes vía U-08, pero no el menú completo con nuevo plot y configuración de señal; esa ampliación queda explícitamente fuera de U-11.

## Trabajo
1. Extraer o ampliar el builder compartido para producir acciones de plot actual, nuevo plot y configuración de señal desde un `AnalysisContext`.
2. Conectar el clic derecho de bytes seleccionados y de series a ese menú compartido, creando contexto preciso para cada selección.
3. Hacer que el botón de toolbar invoque la misma fuente de acciones y conserve el comportamiento actual de destinos de análisis.
4. Verificar el llenado del diálogo de configuración y la transferencia a otra ventana/plot.

## Pruebas
- Caracterizar contextos con bytes seleccionados, señal/serie y ausencia de selección; verificar CAN ID y geometría de bytes/bits.
- Suite completa verde.
- `/verify-ui`: desde Analyze, abrir ambos menús contextuales; añadir al plot actual, crear un plot nuevo y abrir «Configurar señal...» con campos rellenados. Confirmar que el botón de toolbar ofrece el mismo flujo y revisar Candidate, Bit Activity y Real-Time para no perder sus acciones existentes.

## Cierre
- [ ] CHANGELOG `## Unreleased`
- [ ] fila de `docs/plan.md` cerrada
- [ ] `docs/bugs.md` si aplica
- [ ] `docs/ui-design.md` actualizado
