@AGENTS.md

## Solo para Claude Code

- Rol por defecto: **orquestador** (modo A en [docs/operations/orquestacion.md](docs/operations/orquestacion.md)). La implementación grande se delega a Codex con el subagente `codex:codex-rescue`, con una tarjeta y un worktree por tarea. Fixes chicos y documentación se pueden hacer directamente.
- Slash commands en `.claude/commands/`:
  - `/test`, `/commit`, `/merge-dev`, `/release`, `/build`;
  - `/verify-ui` (verificación con capturas de pantalla);
  - `/nuevo-bug`, `/fix-bug`.
- Subagentes en `.claude/agents/`. Pipeline típico de revisión: `code-reviewer` + `qt-mvvm-reviewer` → `qa-verifier` → `/verify-ui`.
- Después de editar `.claude/agents` o `.claude/commands`, corre `scripts/sync_agents.py` para regenerar el espejo de Codex.
- `.claude/settings.local.json` es personal y no se versiona.
