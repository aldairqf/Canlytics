# UI_DESIGN — Canlytics

> Diseño visual y de
> interacción de la app PySide6. El detalle de implementación de cada sistema vive en
> [architecture/overview.md](architecture/overview.md); acá está la referencia de diseño y el estado del audit de UI.

## Sistema de tema

`config/theme.py` — `Theme` (frozen dataclass) con tokens de diseño (colores, radios,
padding). `THEMES` tiene `"Dark"` y `"Light"`. `apply_theme(app, name)` arma `QPalette` +
QSS y los aplica global. Tema activo persistido en `SessionStateStore`, restaurado antes del
splash. Tras cambiar tema: `clear_icon_cache()` (`views/icons.py`) para regenerar pixmaps
cacheados por color.

**Regla:** leer colores por token (`get_active_theme().<token>`), **no** hardcodear hex.
Pendiente de migración: varios views con `setStyleSheet` de colores literales (los estados
`:disabled` de widgets interactivos ya están cubiertos global en QSS).

## Sistema de iconos

`views/icons.py` es el único entry point. Carga SVGs de `assets/icons/` (set **Lucide**,
MIT), sustituye `currentColor` por el fg del tema, cachea `QPixmap` por `@lru_cache`.

```python
from views.icons import icon, app_icon, clear_icon_cache
icon("plus")           # QIcon 20px, color fg del tema
icon("save", size=16)
```

Agregar un icono = descargar el SVG de https://lucide.dev/icons/ con el slug Lucide como
nombre y soltarlo en `assets/icons/` (sin cambio de código). `PySide6.QtSvg` **no** debe
estar en los excludes de PyInstaller.

## Ribbon bar

Estilo Excel/SolidWorks vía `QMainWindow.setMenuWidget(ribbon)`. La `menuBar()` queda oculta
(`setVisible(False)`) pero se construye igual para mantener vivos los shortcuts de `QAction`
(contexto `Qt::WindowShortcut` dispara aunque la barra esté invisible). Este mismo patrón
"menú oculto + toolbar de iconos" se aplicó a Candidate Interpretations (ver [bugs.md](bugs.md)
B-04). Archivos: `views/widgets/ribbon_button.py`, `ribbon_bar.py`, `views/plot/plot_ribbon.py`.
Soporta colapso/auto-hide estilo Excel (F10).

---

## Audit de UI — estado

### Completado (rama `feature/ui-redesign`, mergeado a `dev`)
Menú Archivo con separadores + atajos; regrupado panel CAN ID ("CAN IDs"/"Interpretation");
diálogo de cursor; colapsables "Advanced"; status bar en restore de DBC; DBC manager con
Close + confirmación; empty states; Analyze Data con leyenda + grid de stats; ribbon bar en
ventana principal y de plot. **Excluidos hasta que el usuario los reactive:** MUX Detection
(deshabilitado), HMI Video (intacto). **No re-agregar** el empty state "No signals yet" del plot.

### Rediseños de ventana recientes (mergeados en `dev` / en `feature/range-diff`)
- **Analyze Data:** stats colapsables en chip grid; CAN ID list movida a la derecha, plot
  dominante al centro; Mux + selección por byte movidos a un `QToolBar` (byte toggles como
  `QWidgetAction`+`QCheckBox`, no `QAction` checkable — un `QAction` checkable cierra el
  `QMenu` en cada clic, verificado con `QTest.mouseClick`).
- **Candidate Interpretations:** layout de 3 columnas (izq: CAN IDs + params colapsables;
  centro: detalles colapsables + plot; der: resultados + filtros valor/tag); progress con
  ETA + %; filtro por tipo de valor; menú oculto + toolbar de iconos (B-04).

### Ventanas nuevas / cambios de v0.4.0

- **Guardar como señal:** destino común de los menús de análisis, Diff y la tabla. El diálogo muestra el origen, conserva el CAN ID y prellena bits/bytes, endianess y caso MUX disponibles; permite completar la definición y reporta errores de validación junto a los campos.
- **Working DBC:** ventana accesible desde el ribbon y el menú Archivo. Presenta mensajes con sus señales en una lista jerárquica; permite agregar, editar y eliminar, persiste cada cambio y exporta una copia DBC.

- **CAN Send** (nueva ventana): tabla plana (Enabled/Label/CAN ID/Ext/DLC/Data/Source/Mode/
  Interval/Send Now/toggle Periodic con indicador "● TRANSMITTING") + tab "TX Log" de solo
  lectura. Diálogo de entrada con `QStackedWidget` alternando hex crudo (`HexByteRow`, 8
  `QLineEdit` validados) vs. asistido por DBC (combo DBC → combo mensaje → inputs de señal
  generados). Send Now/Periodic se deshabilitan sin conexión activa; editar la lista sigue
  disponible offline. `WA_DeleteOnClose` seteado (patrón estándar de toda ventana secundaria).
- **Signal Coverage:** botón de exportación CSV (icono `download`) junto a Filters; el CSV
  lleva columnas de geometría de decode (Start Bit/Length/Byte Order/Value Type/Scale/Offset/
  MUX) que la tabla visible no muestra — decisión explícita de no saturar la tabla con eso.
- **DBC Manager:** al cargar un CSV con formato no reconocido, `QMessageBox` con botones
  personalizados "CAI Order"/"DBC Order" (en inglés, custom `AcceptRole`) + Cancel — picker
  manual estilo SavvyCAN. Al detectar el formato automáticamente, `QMessageBox.information`
  confirma qué esquema se usó + conteo de mensajes/señales.

### Pendiente de diseño (ligado al [roadmap archivado](archive/roadmap-2026-07.md))
- **Diff Analyzer:** `QTabWidget` (Resultados / Plot); tab Plot con byte auto-ploteado y
  bandas A/B resaltadas; toggle "Live"; campos A/B legibles por timezone (B-02).
- **Analyze — vista matriz:** grilla de mini-plots (small multiples) + botón "ocultar
  señales sin movimiento" con auto-agregado en vivo (EPIC Analyze AN1-AN3).
- **Sensitivity invertido:** el slider más alto = más estricto; aclarar en UI el sentido.
- **Migración de tokens de tema** y **pase de accesibilidad** (tooltips en jerga, mnemónicos,
  validación inline en el diálogo de conexión).

## Reglas de interacción a respetar

- **Tab activo del ribbon:** `setProperty("active", bool)` + `unpolish/polish/update()`.
- **Toggle checkable:** `blockSignals` en el handler `action.toggled` para evitar el doble
  toggle.
- **Threading:** todo trabajo largo (carga, restore, mux, video, streaming) en `QThread`/
  worker de un ViewModel, nunca bloquear el event loop.
- **`WA_DeleteOnClose`:** toda ventana secundaria debe setearlo (evita fugas de memoria por
  ventanas solo-ocultas); excepción documentada: `fft_window` (reuso deliberado).
