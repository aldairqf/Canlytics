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
5. **Integración.** Usa `/merge-dev` (merge `--no-ff`). Si hay conflictos en `CHANGELOG.md` o `docs/plan.md`, conserva ambas entradas. Después borra el worktree: `git worktree remove .claude/worktrees/<id>`.

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
  archivos completos; commits en inglés `type(scope): summary`, SIN Co-Authored-By ni mención a IA.
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
