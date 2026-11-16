# Plan — Canlytics

Este es el **único plan activo** y contiene **solo lo pendiente**. Al cerrar un ítem, se borra su
fila y se agrega su línea al `CHANGELOG.md` (en `## Unreleased`) **en el mismo commit**.
Cada ítem en curso tiene su tarjeta en `docs/work-items/<ID>-<slug>.md`. El cómo se trabaja
está en [operations/orquestacion.md](operations/orquestacion.md). La historia anterior está
en [archive/roadmap-2026-07.md](archive/roadmap-2026-07.md).

**Norte del producto:** ingeniería inversa de señales CAN, offline y en vivo. Una señal
encontrada tiene que poder recorrer todo el camino: detectar → confirmar → nombrar →
guardar en el DBC de trabajo → plotear, sin perder contexto entre ventanas. Evidencia y
diagnóstico: [review/2026-11-functional-review.md](review/2026-11-functional-review.md).

**Meta 2026-11:** llevar Canlytics al nivel de un banco de trabajo profesional de análisis CAN
(trace, estadística, cursores, formatos) y superarlo en lo que ninguno resuelve bien: descubrir
señales sin DBC. Orden de las fases para no rehacer trabajo: la base (Fases 2–5) primero; las
funciones nuevas (Fases 6–7) se apoyan en ella. El pulido UX (Fase U) corre en paralelo con la
Fase 2 porque toca vistas que la Fase 2 no reescribe.

**Criterio:** primero lo simple que el usuario siente (no perder datos, formatos estándar,
ergonomía); nada de complejidad sin un uso concreto. Lo grande y especulativo vive en el backlog.

Las fases D, 0–6, M y U están cerradas; consulta [CHANGELOG](../CHANGELOG.md) y [el archivo histórico](archive/roadmap-2026-07.md).

## Fase 6 — Ingeniería inversa avanzada (después de las Fases 3 y 4)

Reglas: todo lo de bits y cambios se construye **dentro** de la taxonomía de F3-05 (no una sexta
lógica); todo consumidor en vivo es O(chunk) sobre `rows_appended` (F2-02); toda salida viaja
con `AnalysisContext` (F3-01) y termina en "Guardar como señal" (F4-03).


## Fase 7 — Integraciones y RE activo (después de la Fase 5)

| ID | Trabajo | Va después de | Esfuerzo |
|---|---|---|---|

## Fase P — Plugins de terceros (después de F3-01, F4-01, F5-01 y D-02)

Las empresas extienden Canlytics con su propio código, que **no se versiona en este repo**. Un
plugin es una carpeta con `plugin.toml` + Python en `%APPDATA%\Canlytics\plugins\` (o
`CANLYTICS_PLUGINS_DIR`), o un paquete pip con *entry point* `canlytics.plugins`. Tiene
PySide6 completo y puede crear sus propias ventanas. Solo el SDK (`canlytics_sdk`) es API
estable con versión; importar `views/` o `viewmodels/` funciona pero puede romperse en cualquier
release. Un plugin es código de confianza (sin sandbox).

| ID | Trabajo | Va después de | Esfuerzo |
|---|---|---|---|

## Backlog (sin fecha; no se toca sin pedido explícito)

| Trabajo | Condición para retomarlo |
|---|---|
| HMI Video OCR + ID1 (correlación OCR ↔ señal detectada) | El usuario descongela OCR |
| Constraint Search: persistir precisión y tolerancia | Junto con F3-07 |
| Plot y diálogos: strings duplicados del menú oculto | Junto con F5-06 |
| CAN FD (64 bytes) y multi-bus | Cambia el contrato del DataFrame (`FRAME_SCHEMA`); hoy el campo es 1 bus clásico |
| Importar KCD/SYM/ARXML | Tras F5-01, si aparece un usuario que lo necesite |
| Match contra un corpus público de DBC | Bajo valor: los equipos de campo no son autos de serie |
| Ventanas acoplables (docks) con layouts guardables | Si U-07 (geometría por ventana) no alcanza en el uso real |
| Fuzzing de frames | Pedido explícito y protocolo de seguridad para equipo real |

## Fase U2 — Pulido UX (pedidos del usuario)

La Fase U original sigue cerrada; U2 agrupa los nuevos pedidos de ergonomía de análisis y visibilidad de sesión.

| ID | Trabajo | Va después de | Esfuerzo |
|---|---|---|---|
