---
description: Stage and create concise atomic commit(s) following repo conventions (no push)
argument-hint: "[opcional: pista de scope o mensaje]"
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git log:*)
---

Crea uno o más commits con los cambios actuales del working tree. Sé breve.

## Convención (Conventional Commits, en inglés — así es el repo)
- Asunto: `type(scope): summary` en imperativo, ≤ 60 caracteres.
  Tipos: `feat`, `fix`, `refactor`, `test`, `style`, `docs`, `chore`, `perf`.
- Cuerpo: **opcional** y solo si aporta — máximo 3 viñetas con lo principal (qué/por qué).
  Nunca listes archivos uno por uno ni cambios triviales.
- **NUNCA** añadas líneas de coautoría (`Co-Authored-By`) ni firmas de Claude/IA. Regla del usuario.

## Pasos
1. Mira `git status`, `git diff` y `git log --oneline -5` (para el estilo vigente).
2. Si los cambios son de naturalezas distintas (p. ej. `test` + `refactor`), sepáralos en
   commits atómicos; stagea de forma selectiva (no `git add -A` a ciegas).
3. Commitea. **No hagas push** (este repo tiene problemas de SSL con el remoto).
4. Si hay argumentos (`$ARGUMENTS`), úsalos como pista de scope/mensaje.

Al terminar, muestra `git log --oneline -3`.
