---
description: Corrige un bug de docs/bugs.md con regresión primero (rojo→verde) y actualiza el registro
argument-hint: "<id del bug, p.ej. B-02>"
allowed-tools: Read, Edit, Write, Grep, Glob, Bash
---

Corrige el bug **$ARGUMENTS** siguiendo el flujo regresión-primero.

Pasos:
1. Abre `docs/bugs.md` y localiza la
   entrada `$ARGUMENTS`: lee `archivo:línea`, descripción y **escenario de fallo**.
2. **Test de regresión primero:** escribe en `tests/` (usa el agente
   `test-engineer` si conviene) un test `unittest` que reproduzca el escenario y **falle**
   (rojo). Nómbralo con el id (p.ej. `test_b02_...`). Córrelo desde la raíz del repo y confirma
   el rojo:
   `.venv/Scripts/python.exe -m unittest tests.<modulo> -v`
   (Si el bug es UI puro y no hay superficie testeable sin app, decláralo y usa un smoke test
   headless en su lugar.)
3. **Fix mínimo** en la capa correcta (respeta MVVM: lógica en `services/`/viewmodel, la vista
   solo renderiza). Bug de lógica pura → considera `refactor-architect`; bug de UI/UX →
   `ui-ux-designer`.
4. Corre el test (**verde**) y luego la **suite completa** para no introducir regresiones:
   `.venv/Scripts/python.exe -m unittest discover -s tests -t .`
5. Si el bug tiene superficie visual, **verifica en la app** (`/verify-ui`), no solo que importe.
6. Actualiza `docs/bugs.md`: marca `$ARGUMENTS` como ✅ corregido (fecha + nota/commit), deja el
   test como su regresión permanente, y actualiza el bloque "Estado de corrección". Refleja el
   cambio en `docs/testing.md` si agregaste una regresión.

No marques el bug como resuelto sin el test en verde y (si aplica) verificación en la app.
No hagas commit sin aprobación del usuario.
