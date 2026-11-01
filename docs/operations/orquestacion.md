# Orquestación de agentes

Cómo se reparte el trabajo entre Claude Code y Codex en este repo. La decisión está en
[ADR 005](../architecture/decisions/005-dual-orchestration.md).

## Roles

| Rol | Hace |
|---|---|
| **Orquestador** | Entiende el pedido, lo divide en tarjetas, escribe el prompt, crea el worktree, revisa el resultado sin confiar en el resumen, corre los gates e integra a `dev` |
| **Implementador** | Escribe el código, los tests y la documentación de la tarjeta (CHANGELOG + plan) dentro de su worktree |
| **Usuario** | Aprueba lo irreversible: el release `dev` → `master` y el push |

Los modos posibles son dos:

- **Modo A, Claude orquesta y Codex implementa.** Es el modo por defecto. Claude lanza a Codex con el subagente `codex:codex-rescue` (plugin de Codex) en segundo plano.
- **Modo B, Codex orquesta y Codex implementa.** Codex lee `AGENTS.md` y usa sus subagentes de `.codex/agents/`, que se generan desde `.claude/agents/` con `scripts/sync_agents.py`. Las tarjetas, los gates y las reglas son exactamente los mismos.

Los commits en ramas de trabajo y los merges `--no-ff` a `dev` los aprueba el orquestador,
siempre que pasen los gates.

## Gitflow

```
master  ← solo releases aprobados por el usuario (/release: dev → master --no-ff + tag)
  dev   ← integración; solo entra trabajo terminado y probado (merge --no-ff)
    feature/<card> · fix/<card> · perf/<card> · refactor/<card> · docs/<card>   (salen de dev)
```

Nunca se commitea directo en `dev` ni en `master`. Nunca se usa `--squash`. Push manual,
porque el remoto tiene problemas de SSL.

## Ciclo de una tarjeta

1. **Tarjeta.** Copia `docs/work-items/_template.md` a `docs/work-items/<ID>-<slug>.md` y llena *Puede editar* / *No puede editar*. Así dos implementadores en paralelo no tocan los mismos archivos.
2. **Worktree.** Créalo a mano y comprueba la base:
   ```bash
   git worktree add .claude/worktrees/<id> -b <tipo>/<id>-<slug> dev
   git -C .claude/worktrees/<id> log --oneline -1   # debe coincidir con dev
   ```
   No uses el aislamiento de worktree integrado en la herramienta Agent. En gestion-pyme dejó al implementador sobre una base vieja.
3. **Prompt.** Usa la plantilla de abajo y lánzalo en segundo plano. El aviso de "agente terminado" del envoltorio llega antes de que el trabajo real termine. Confirma el estado con el job de Codex o con `git log` en el worktree.
4. **Revisión del orquestador.** Esto es obligatorio:
   - `git diff -w --stat dev...<rama>`. Codex a veces reformatea archivos completos; si el diff toca líneas no relacionadas, rechaza la tarjeta.
   - Cuenta los usos de los nombres clave para detectar borrados silenciosos.
   - Busca mojibake (`Ã©`, `Ã±`). Los docs están en español y el código es UTF-8.
   - Corre la suite completa **fuera** del sandbox de Codex.
   - Agentes de revisión: `code-reviewer` + `qt-mvvm-reviewer`, después `qa-verifier`.
   - Si la tarjeta toca algo visible, `/verify-ui` con capturas de pantalla revisadas una por una.
5. **Integración.** Usa `/merge-dev` (merge `--no-ff`). Si hay conflictos en `CHANGELOG.md` o `docs/plan.md`, conserva ambas entradas y une las secciones `###` repetidas. Después borra el worktree: `git worktree remove .claude/worktrees/<id>`.

## Lecciones del primer ciclo (F1-01 / F1-02)

- **Codex no puede commitear dentro de un worktree.** Su sandbox no puede escribir en `.git/worktrees/<id>/` (falla con `index.lock`). Por eso Codex deja los cambios sin commit, y el orquestador los revisa, corre los gates y hace commits pequeños. La plantilla ya lo pide así.
- **Codex rompe el encoding cuando escribe español desde PowerShell.** Los acentos y los emojis salieron como `?` en `docs/bugs.md`. Antes de commitear, revisa los docs con un script Python que busque `??`, `[a-z]?[a-z]` y `Ã`; `grep -P` no funciona en este entorno.
- **Verificar en la app real con el log de campo encuentra lo que los tests no ven.** En F1-02, la captura mostró que la ventana también reseteaba la selección de IDs, un segundo bug del mismo flujo. Los scripts de verificación van en el scratchpad, nunca en el repo. Corren con `QT_QPA_PLATFORM=offscreen QT_QPA_FONTDIR=C:/Windows/Fonts`, porque sin las fuentes Qt dibuja cuadrados, y con `chdir` a la carpeta de salida para que `.canlytics_state/` no caiga en el repo.
- **Nunca uses `git stash`**, ni siquiera de pasada: el stash es compartido entre todos los worktrees. Si pasa por accidente, recupera tu entrada por SHA con `git stash apply <sha>` y bórrala buscando su índice actual.
- **OneDrive bloquea archivos en `.git/worktrees/`.** `git worktree remove` puede fallar con `Permission denied`. Borra la carpeta del worktree y corre `git worktree prune`. Por eso el repo se movió fuera de OneDrive, a `C:\Users\Asus\Proyectos\CANAnalyzer`.

## Plantilla de prompt para el implementador

```
PASO 0 — Trabaja SOLO en <ruta worktree>, rama <rama>. Verifica: `git log --oneline -1` == <hash de dev>.
Qué leer primero: AGENTS.md, docs/architecture/overview.md, docs/work-items/<ID>.md (y el ADR que cite).
El problema (palabras del usuario): "<cita>".
Tareas:
  1. …
Pruebas obligatorias: <tests de regresión primero en rojo; invariantes>. Suite completa en verde:
  .venv/Scripts/python.exe -m unittest discover -s tests -t . -v
Documentación: tarjeta (Estado → Hecho), fila de docs/plan.md, entrada en CHANGELOG.md bajo "## Unreleased"
  (prosa para el usuario, no lista de archivos); docs/bugs.md si cierra un bug.
Límites: solo los archivos de "Puede editar"; no subas versión; no `git stash`; no push; no reformatees
  archivos completos. NO hagas commits (el sandbox no puede escribir en .git/worktrees): deja los cambios
  en el árbol de trabajo; el orquestador revisa y commitea. Escribe los archivos en UTF-8 desde Python,
  no con redirecciones de PowerShell (rompen acentos y emojis).
Gates antes de terminar: suite verde · `python scripts/sync_agents.py --check` si tocaste .claude/.
Reporte final: commits (hash + asunto), tests agregados, qué NO se hizo y por qué, riesgos.
```

## Agentes disponibles (`.claude/agents/`, con espejo en `.codex/agents/`)

| Agente | Cuándo |
|---|---|
| `code-reviewer` | Buscar bugs en un diff; separa CONFIRMED de PLAUSIBLE. Solo lectura |
| `qt-mvvm-reviewer` | Capas MVVM, cableado de señales, convenciones. Solo lectura |
| `qa-verifier` | Correr la suite y reportar. No corrige nada |
| `test-engineer` | Escribir tests de caracterización o regresión |
| `refactor-architect` | Movimientos estructurales sin cambio de comportamiento |
| `ui-ux-auditor` / `ui-ux-designer` | Auditoría o diseño de UI |
