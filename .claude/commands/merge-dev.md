---
description: Squash-merge current feature branch into dev as one commit
allowed-tools: Bash(git checkout:*), Bash(git merge:*), Bash(git commit:*), Bash(git log:*), Bash(git branch:*), Bash(git status:*), Bash(git diff:*)
---

Integra la rama actual en `dev` con `--squash`: entra como **un solo commit** que resume todas
sus funcionalidades.

## Gates (gitflow: a `dev` solo entra trabajo terminado y probado)
- La rama actual es `feature/…`, `fix/…`, `perf/…`, `refactor/…`, `docs/…` o `chore/…`, nunca `dev` ni `master`.
- La suite completa está en verde: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -v`.
- Si el cambio es visible para el usuario, quedó verificado con `/verify-ui`.
- `CHANGELOG.md` (`## Unreleased`) y `docs/plan.md` se actualizaron en la propia rama.
Si algún gate falla, detente y repórtalo; no hagas el merge.

## Pasos
1. Lee `git branch --show-current` y `git log --oneline dev..HEAD` para ver todo lo que va a entrar.
2. Haz `git checkout dev` y `git merge --squash <rama>`.
3. Commitea con un mensaje que resuma todas las funcionalidades de la rama:

```
type(scope): summary de toda la rama (60 caracteres como máximo)

- <funcionalidad o cambio 1>
- <funcionalidad o cambio 2>
- <funcionalidad o cambio 3; máximo 3 bullets>
```

4. Borra la rama con `git branch -D <rama>` (después de un squash, git no la ve como mergeada).
5. Muestra `git log --oneline -5` al terminar.

## Reglas
- Nunca hagas push (el remoto tiene problemas de SSL).
- Nunca pongas `Co-Authored-By` ni menciones IA en el mensaje.
- Si hay conflictos, resuélvelos y luego completa el commit; no abortes sin avisar.
