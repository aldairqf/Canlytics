---
description: Registra un bug verificado en docs/bugs.md con el formato de la casa (id, severidad, archivo:línea, escenario)
argument-hint: "<descripción del bug o síntoma>"
allowed-tools: Read, Edit, Grep, Glob, Bash
---

Verifica y registra un bug nuevo en `docs/bugs.md`: **$ARGUMENTS**

Pasos:
1. **Verifica primero** (usa el agente `code-reviewer`): traza el fallo en el código con
   `archivo:línea` (rutas relativas a la raíz del repo). Si no puedes reproducirlo por lectura,
   márcalo PLAUSIBLE; si no hay evidencia, NO lo registres. Cuando ayude, reprodúcelo headless
   (`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe ...`).
2. Asigna el siguiente id libre (`B-05`, `B-06`, …) leyendo `docs/bugs.md`.
3. Añade la entrada en la sección correcta (Range Diff/Diff Analyzer, Real-Time, Candidate,
   etc.) con el formato:
   - **B-NN** [🔴/🟠/🟡] [CONFIRMADO/PLAUSIBLE] — título en 1 frase — [estado]
   - **Dónde:** `archivo:línea`
   - **Qué:** causa técnica en 1–2 frases
   - **Escenario:** entrada/pasos → resultado erróneo
   - **Fix sugerido:** dirección breve (no el parche completo)
4. Actualiza el bloque "Estado de corrección" del encabezado si corresponde.
5. Sugiere (sin escribirlo aún) el test de regresión que iría en `docs/testing.md` /
   `tests/`.

Sé escéptico: distingue CONFIRMADO de PLAUSIBLE y no dupliques bugs ya listados.
