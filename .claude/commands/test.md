---
description: Run the full characterization test suite
argument-hint: "[optional: test module, e.g. tests.test_formula_generator]"
allowed-tools: Bash(.venv/Scripts/python.exe:*)
---

Corre los tests de caracterización desde la raíz del repo. Siempre usa el venv del proyecto.

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -t . -v
```

Si se pasan `$ARGUMENTS`, corre solo ese módulo/caso:

```bash
.venv/Scripts/python.exe -m unittest $ARGUMENTS
```

Muestra el resumen final (`OK` / `FAILED`). Si falla algún test, incluye el traceback completo.
No hagas nada más — solo reporta el resultado.
