# 002 — Sin tope de RAM en captura; guardián de memoria

**Estado:** Aceptado (2026-11-01)

## Contexto
Con el tráfico real (~900 fps, ~40 IDs), una hora de captura ocupa unos 110 MB de frames y
el proceso completo entre 300 y 400 MB. La RAM no explica el lag (ver ADR 001).

Una ventana deslizante rompería las herramientas que necesitan la historia completa:
Candidate, Signal Coverage, Diff por lotes, las estadísticas de Analyze y el historial del
Plot. Real-Time no se vería afectado, porque trabaja por ID.

En turnos de 8 h el proceso puede llegar a 2–2.5 GB. Si se pasa de la RAM física, Windows
pagina a disco y se pone lento todo el equipo, no solo la app.

## Decisión
- No hay tope ni descarte automático de frames.
- Un guardián de memoria muestra en la barra de estado la RAM del proceso, los frames y los fps.
- Avisa, sin bloquear, al pasar un umbral configurable en `DEFAULT_OPTIONS`: por defecto 2 GB o el 60 % de la RAM del sistema, lo que ocurra primero. El aviso ofrece "Grabar a disco y limpiar".
- Opcionalmente, la captura se graba a disco de forma continua (writer en hilo, formato candump).

## Consecuencias
- El usuario decide cuándo limpiar y nunca pierde datos sin enterarse.
- El writer a disco no puede bloquear el hilo de la UI.
