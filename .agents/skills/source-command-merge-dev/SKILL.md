---
name: "source-command-merge-dev"
description: "Merge current feature branch into dev with --no-ff"
---

# source-command-merge-dev

Use this skill when the user asks to run the migrated source command `merge-dev`.

## Command Template

Merge la rama feature actual en `dev` con `--no-ff`.

## Gates (gitflow: a `dev` solo entra trabajo terminado y probado)
- La rama actual es `feature/…`, `fix/…`, `perf/…`, `refactor/…` o `docs/…`, nunca `dev` ni `master`.
- La suite completa está en verde: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -v`.
- Si el cambio es visible para el usuario, quedó verificado con `/verify-ui`.
- `CHANGELOG.md` (`## Unreleased`) y `docs/plan.md` se actualizaron en la propia rama.
Si algún gate falla, detente y repórtalo; no hagas el merge.

## Pasos
1. Lee `git branch --show-current` y `git log --oneline -5` para entender qué va a entrar.
2. Haz `git checkout dev`.
3. Merge con `--no-ff` usando el formato:

```
merge: integrate <feature-branch> into dev

- <qué se añadió / cambió — máximo 3 bullets concisos>
```

4. Muestra `git log --oneline -5` al terminar.

## Reglas
- Nunca hagas push (el remoto tiene problemas de SSL).
- Nunca uses `--squash` — se preservan los commits atómicos de la feature branch.
- Si hay conflictos, resuélvelos y luego completa el merge; no abortes sin avisar.
