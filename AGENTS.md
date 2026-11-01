# AGENTS.md — Canlytics

Guía para agentes (Codex, Claude Code) y personas. Es la entrada corta; el detalle vive en
`docs/`, así que lee solo lo que la tarea necesita.

## Orden de lectura
1. Este archivo.
2. [docs/plan.md](docs/plan.md): qué está pendiente y en qué fase.
3. La tarjeta de la tarea, en `docs/work-items/<ID>-*.md`, si existe.
4. [docs/architecture/overview.md](docs/architecture/overview.md): capas, flujo de datos, contrato del DataFrame.
5. El ADR que cite la tarjeta (`docs/architecture/decisions/`). No leas los ADR completos si la tarjeta no los pide.

| Doc | Para qué |
|---|---|
| [docs/plan.md](docs/plan.md) | Único plan activo; solo lo pendiente |
| [CHANGELOG.md](CHANGELOG.md) | Lo hecho, por versión (`## Unreleased` arriba) |
| [docs/bugs.md](docs/bugs.md) | Bugs verificados (id, severidad, `archivo:línea`, escenario, estado) |
| [docs/testing.md](docs/testing.md) · [tests/README.md](tests/README.md) | Plan de pruebas · mapa de cobertura |
| [docs/ui-design.md](docs/ui-design.md) | Tema, íconos, ribbon, reglas de interacción |
| [docs/operations/orquestacion.md](docs/operations/orquestacion.md) | Claude→Codex / Codex→Codex, gitflow, plantilla de prompt |
| [docs/review/](docs/review/) | Revisiones funcionales con evidencia |
| [docs/archive/](docs/archive/) | Histórico (no es fuente de verdad) |

## Qué es
App de escritorio PySide6 (MVVM estricto) para ingeniería inversa de señales CAN, offline
(logs candump/Kvaser) y en vivo (Kvaser/SSH/replay). El DBC cargado es solo de ayuda; la
detección no depende de él. Tráfico real de referencia: ~900 fps, ~40 IDs, 1 bus.

## Comandos (desde la raíz del repo, con el venv del proyecto)
```bash
.venv/Scripts/python.exe main.py                                         # correr la app
.venv/Scripts/python.exe -m unittest discover -s tests -t . -v           # suite completa (unittest, NO pytest)
.venv/Scripts/python.exe -m unittest tests.test_kvaser_config            # un módulo
.venv/Scripts/python.exe scripts/sync_agents.py [--check]                # regenerar/verificar config de Codex desde .claude/
.venv/Scripts/pyinstaller.exe --clean --noconfirm --distpath "dist\Windows" --workpath "build\Windows" Canlytics.spec
```
No hay linter. El OCR de HMI necesita Tesseract, pero el OCR está congelado.

## Gates (antes de dar por terminada cualquier tarea)
1. La suite completa en verde.
2. Si el cambio es visible, verificarlo en la app real con `/verify-ui` y revisar las capturas de pantalla. Que los tests pasen no prueba la feature.
3. Si tocaste `.claude/`: `scripts/sync_agents.py --check` en verde.
4. Docs actualizados en el mismo commit:
   - entrada en `CHANGELOG.md` (`## Unreleased`, en prosa para el usuario);
   - fila de `docs/plan.md` cerrada;
   - `docs/bugs.md` si aplica;
   - `docs/architecture/overview.md` si cambió algo de lo que describe.

## Reglas que no se negocian
- **Gitflow.**
  - Ramas `feature/` `fix/` `perf/` `refactor/` `docs/` salen de `dev` y vuelven con `merge --squash`: un solo commit en `dev` que resume todo lo de la rama.
  - `dev` → `master` solo con trabajo terminado y probado, vía `/release`, aprobado por el usuario.
  - Nunca commits directos a `dev`/`master`, nunca `--squash` de `dev` → `master`, nunca push (el remoto tiene problemas de SSL; el push es manual).
- **Commits.**
  - En inglés, Conventional Commits `type(scope): summary`, asunto de 60 caracteres como máximo, cuerpo de 3 bullets como máximo.
  - Pequeños, un tema cada uno.
  - **Nunca `Co-Authored-By` ni firma o mención a IA.**
  - Los commits en ramas de trabajo y los merges a `dev` los aprueba el orquestador si pasan los gates.
- **MVVM.**
  - `models/`, `utils/` y `services/` sin Qt (los servicios se importan sin hardware: `can`/`paramiko` con import perezoso).
  - Las vistas nunca llaman a servicios.
  - Los ViewModels son adaptadores delgados.
- **Streaming O(chunk)** (ADR 001).
  - Nada recorre el df completo en cada flush.
  - Los consumidores incrementales leen el chunk crudo de `chunk_ready`; nunca un watermark por cantidad de filas sobre el df acumulado.
  - Sin tope de RAM (ADR 002).
- **Hilos.** Trabajo largo en un `QThread` propiedad de un ViewModel. Los diálogos de espera muestran **% y ETA**.
- **Configuración.** Constantes ajustables en `config/defaults.py` / `DEFAULT_OPTIONS`; textos vía `get_text()`; nada hardcodeado.
- **Áreas congeladas.**
  - No tocar la lógica de Mux Detection.
  - No tocar HMI Video/OCR.
- **Datos de campo.** Los logs reales (carpeta `Fase 02` del usuario) son de **solo lectura**: nunca borrarlos ni modificarlos.
- **Comentarios y docstrings** de una línea, sin fechas.
- `from __future__ import annotations` y type hints en todos los módulos.

## Versionado
- Fuente única: `config/version.py` (`APP_VERSION`), SemVer.
  - PATCH: fixes, ajustes de UI, refactors.
  - MINOR: feature completa.
  - MAJOR: cambio incompatible de esquema `.conf` / `.canlytics_state`.
- `/release` lleva la versión a `dev`, cierra `## Unreleased` en el CHANGELOG, hace merge `--no-ff` de `dev` → `master` y crea el tag `vX.Y.Z`.
- Build etiquetado sin tocar la versión: `CANLYTICS_BUILD_SUFFIX=alpha`.

## Dónde está cada cosa
```
main.py                     splash → MainWindowViewModel → MainWindow
config/                     defaults, app_config (get_option/get_text), theme, version, ui_text
models/                     dataclasses de dominio
utils/                      funciones puras (can_id, can_bytes, timezone_format, filters)
services/                   lógica + I/O Qt-free (parser, dbc_manager, range_diff, candidate_*, analyze_data, …)
viewmodels/                 QObject + workers; main_window_viewmodel.py = composition root
views/                      ventanas, *_window_manager.py, widgets/, plot/, table/, settings/, dbc/
tests/                      unittest de caracterización (Qt-free + algunos offscreen); fixtures/ con logs y DBC reales
scripts/                    sync_agents.py, bench_stream.py
docs/                       plan, bugs, testing, ui-design, architecture/ (+decisions/), operations/, work-items/, review/, archive/
.claude/ · .codex/ · .agents/   agentes, comandos y skills (fuente: .claude/)
Canlytics.spec · _build_common.py   build PyInstaller (onefile + onedir)
```

## Trampas conocidas
- **Ventanas secundarias:** siempre `Qt.WA_DeleteOnClose`. Sin eso se filtran la ventana, sus curvas y sus timers. Excepciones deliberadas: `FFTWindow` (se reusa) y el diálogo de Conexión, que no puede pasarse a `True` sin antes resetear la referencia en `destroyed`.
- **Ventanas que consumen datos en vivo:** conectarse a `dataframe_changed`/`chunk_ready` al crearse y desconectarse al destruirse (patrón `CandidateInterpretationsWindowManager`).
- **`DataTableView`:** `setSortingEnabled(True)` dispara `model.sort(0, Desc)` implícito. No asumas que no hay orden activo (bug F1-01).
- **Menú oculto:** `menuBar().setVisible(False)` mantiene vivos los atajos. No quites `build_main_menu()`: registra los shortcuts.
- **Ribbon:**
  - Para el estado `active` usa `setProperty` + `unpolish/polish/update()`.
  - Los toggles sincronizados con `QAction` usan `blockSignals`.
  - `RibbonBar` necesita `reload_icons()` después de `apply_theme()`.
  - Al cambiar de tema, llama a `clear_icon_cache()`.
- **Timezone en Plot:** no llames `plot.setAxisItems` (destruye los viewboxes auxiliares); usa `renderer._apply_axis_mode_ui()`.
- **Checkboxes dentro de `QMenu`:** usa `QWidgetAction` + `QCheckBox`. Un `QAction` checkable cierra el menú en cada clic. Pruébalo con `QTest.mouseClick`, no con `.trigger()`.
- **`QListWidget` con checkboxes:** usa `itemActivated`, no `itemClicked` (doble toggle).
- **No re-agregar** el overlay "No signals yet" en el plot (decisión del usuario).
- **Hora del dispositivo por SSH:** parsea `candump -ta` con `parse_candump_line()`, no `date +%s`.
- **Codex** a veces reformatea archivos completos o rompe el encoding. Revisa `git diff -w --stat` y busca mojibake antes de integrar. Dentro de un worktree no puede commitear: commitea el orquestador.
- **Nunca uses `git stash`**: el stash es compartido entre worktrees. Usa un commit WIP.
- **No pongas el repo dentro de OneDrive**: bloquea archivos en `.git/worktrees/`. El repo vive en `C:\Users\Asus\Proyectos\CANAnalyzer`.
