# Plan de contenido para el README público

> Documento de planificación del README público (versionado en `docs/`).

**Por qué existe este archivo separado del plan:** [plan.md](plan.md) es
backlog técnico (fases, archivos, esfuerzo por capa) escrito para quien programa el
proyecto. Este documento es lo opuesto: **cómo se le explica Canlytics a alguien que
solo lo va a usar** (o a un visitante de GitHub que nunca va a leer una línea de
código) — sin jerga de MVVM/ViewModel/QThread/Polars, y siendo honesto sobre qué
funciona, qué está pausado y qué no.

---

## Catálogo de herramientas — estado a nivel usuario

Leyenda: ✅ funciona · ⚠️ funciona con una limitación conocida · ❄️ congelado (pausado,
no se está tocando) · 🚫 deshabilitado/cancelado (no accesible desde la UI hoy).

| Herramienta | Qué le permite hacer al usuario | Estado |
|---|---|---|
| **Cargar logs** (candump / Kvaser Memorator) | Abrir un archivo de captura CAN grabado y verlo en tabla | ✅ |
| **Conexión en vivo** (SSH / hardware Kvaser / replay) | Ver tramas CAN entrando en tiempo real, sin un archivo previo | ✅ |
| **CAN Send** | Armar y transmitir tramas CAN al bus (una vez o periódicas), desde hex crudo o asistido por una señal DBC ya cargada | ✅ (nuevo en v0.4.0; requiere conexión SSH o Kvaser activa, no disponible en modo replay) |
| **Decodificación DBC** | Cargar un archivo DBC y ver las señales ya traducidas (nombre + valor), no solo bytes crudos | ✅ |
| **Plot de señales** | Graficar cualquier señal decodificada o byte crudo, con filtros de suavizado, exportar a imagen/CSV | ✅ |
| **Señales derivadas** | Crear una señal nueva a partir de una fórmula (combinar otras señales, extraer bits, etc.) | ✅ |
| **Real-Time Analysis** | Ver en vivo qué bytes están cambiando ahora mismo, con estadísticas de periodo | ✅ |
| **Diff Analyzer** | Marcar "antes" y "después" (p. ej. antes/después de apretar un botón físico) y que la app diga qué byte cambió — sin necesitar DBC | ✅ (modo en vivo recién agregado, todavía en validación con uso real de streaming) |
| **Candidate Interpretations** | Buscar automáticamente qué bytes de un log parecen llevar una señal real (y no ruido/constante/checksum), sin DBC | ⚠️ funciona, pero la búsqueda puede tardar varios minutos en logs con muchos IDs distintos (100+); hay una causa identificada, aún no corregida |
| **Analyze Data** | Ver estadísticas y un mini-gráfico por cada CAN ID del log, con vista de "matriz" para barrer todos los IDs de un vistazo | ✅ |
| **Signal Coverage** | Ver qué señales de un DBC cargado realmente tienen datos en el log (y cuáles no aparecen nunca); exportar el resultado a CSV, y ese mismo CSV se puede reimportar como DBC | ✅ |
| **Constraint Search** | Buscar un valor conocido dentro del log (p. ej. "en algún momento la velocidad fue 80") para ubicar en qué byte/tiempo está | ✅ |
| **Exportar** (imagen / CSV) | Guardar gráficos o resultados para compartir fuera de la app | ✅ |
| **HMI Video / OCR** | Leer números desde una grabación de pantalla de un panel/HMI y cruzarlos con los datos CAN | ❄️ **Congelado indefinidamente** desde 2026-07-19 — no se está desarrollando ni corrigiendo, puede tener errores sin resolver |
| **Mux Detection** | (detección de multiplexado por entropía) | 🚫 **Deshabilitado** — no aparece en ningún menú, no funcionaba de forma confiable |
| **Modo Básico de señales derivadas** (constructor visual sin código) | Armar una señal derivada sin escribir una fórmula | 🚫 **Cancelado** — nunca se terminó de construir, no se va a hacer. Solo existe el modo Avanzado (con fórmula) |

---

## Propuesta de estructura para el README público

El README actual (`README.md`) ya es razonable para alguien que va a
instalar y correr el proyecto, pero mezcla todo en una sola lista de "Features" sin
distinguir estado. Propuesta de reorganización:

1. **Qué es** (1-2 líneas, sin cambios respecto a hoy).
2. **Screenshot o GIF corto** — hoy no hay ninguna imagen; es lo primero que mira
   cualquier visitante de GitHub antes de leer texto. (Pendiente: el usuario decide
   si quiere tomar una captura.)
3. **Qué puedo hacer con esto** — la tabla de arriba, en versión resumida (sin la
   columna técnica), agrupada en 3 bloques según el caso de uso real:
   - *Ver y decodificar un log* (cargar, DBC, plot, exportar)
   - *Encontrar señales sin DBC* (Candidate Interpretations, Diff Analyzer, Signal
     Coverage, Constraint Search) — esto es lo que diferencia a Canlytics de un
     visor CAN genérico, vale la pena destacarlo primero, no esconderlo al final
   - *Streaming en vivo* (SSH / Kvaser / Real-Time Analysis)
4. **Estado / limitaciones conocidas** — sección corta y honesta, no escondida:
   "HMI Video/OCR está pausado", "Candidate Interpretations puede ser lento en logs
   grandes con muchos CAN IDs". Esto genera más confianza que omitirlo — cualquiera
   que lo pruebe y choque con eso solo, sin aviso, lo va a leer como un bug no
   documentado en vez de una limitación conocida.
5. **Instalación / Quick start** (ya existe, no toca cambiar).
6. **Tests / Build** (ya existe, no toca cambiar).

## Leyenda de estados (para reusar en el README si se decide adoptar esto)

```
✅ Funciona
⚠️ Funciona, con una limitación conocida (se explica cuál)
❄️ Congelado / en pausa — no se está desarrollando activamente
🚫 Deshabilitado o cancelado — no accesible desde la interfaz
```

## Pendiente de decisión del usuario

- [ ] ¿Aplicar esta reorganización directo a `README.md`? Es un cambio
  solo de documentación, bajo riesgo — se puede hacer en la rama actual
  (`feature/detection-suite`, que ya tiene trabajo en curso sin commitear) o en una
  rama nueva dedicada solo a esto, para no mezclar el commit de docs con el trabajo
  de logging en curso. Recomendado: rama nueva desde `dev` si se quiere mergear
  independiente del resto.
- [ ] ¿Tomar una captura de pantalla o GIF para el README?
- [ ] ¿Agregar la descripción del repo + topics sugeridos en GitHub (`can-bus`,
  `automotive`, `canbus`, `dbc`, `reverse-engineering`, `python`, `pyside6`) — visto
  en la conversación anterior sobre por qué el repo no aparece en búsquedas?
- [ ] ¿Vale la pena mencionar en el README que `pipeline_builder.py` (Modo Básico)
  es código potencialmente muerto, o eso queda solo como nota interna en `docs/architecture/`?
