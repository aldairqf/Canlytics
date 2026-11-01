# 005 — Orquestación dual de agentes y configuración versionada

**Estado:** Aceptado (2026-11-01)

## Contexto
Los docs y la configuración de agentes vivían en la carpeta contenedora, fuera de git. Por
eso no tenían historial ni acompañaban a las ramas. El usuario quiere el flujo de
gestion-pyme ("Claude orquesta, Codex implementa"), y además que Codex pueda orquestar por
sí solo. A diferencia de gestion-pyme, que ignora en git la parte de Codex, aquí se versiona todo.

## Decisión
- Se versionan en el repo: `.claude/`, `.codex/agents/`, `.agents/skills/`, `AGENTS.md`, `CLAUDE.md` y `docs/`.
- `.claude/` es la fuente. `scripts/sync_agents.py` genera la configuración de Codex, y `--check` falla si quedó desactualizada.
- Hay dos modos, descritos en `docs/operations/orquestacion.md`:
  - (A) Claude orquesta y Codex implementa.
  - (B) Codex orquesta e implementa.
- En ambos modos el trabajo sigue el mismo ciclo: tarjeta en `docs/work-items/`, un worktree y una rama por tarjeta, y merge `--squash` a `dev` (un commit por rama) siguiendo gitflow.

## Consecuencias
- Hay que mantener las dos configuraciones sincronizadas: `sync_agents.py --check` corre antes de cada merge que toque `.claude/`.
