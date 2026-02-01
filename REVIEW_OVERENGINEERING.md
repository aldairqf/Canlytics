# REVIEW_OVERENGINEERING

## A. Hallazgos (por archivo / módulo)

### `services/decoder_service.py` → `SignalDecoderService.decode_signal`
- **Qué lo hace sobreingeniería:** wrapper innecesario que solo delega a `services.can_decoder.decode_signal`.
- **Costo:** capa extra sin lógica, más saltos para depurar y más imports sin valor.
- **Recomendación aplicada:** eliminar la clase y usar la función directa desde el ViewModel.

### `services/log_data_service.py` → `LogDataService.merge_frames`
- **Qué lo hace sobreingeniería:** clase con un único método sin estado real.
- **Costo:** complejidad accidental y acoplamiento innecesario a una “service class”.
- **Recomendación aplicada:** convertir en función pura `merge_frames` en `services/log_data.py`.

### `services/contracts.py` → Protocols (`DataService`, `DecoderService`, `LogLoaderService`, `DbcService`)
- **Qué lo hace sobreingeniería:** interfaces sin múltiples implementaciones reales.
- **Costo:** más archivos y tipos que no agregan valor operativo; dificulta navegación.
- **Recomendación aplicada:** usar tipos concretos (`DbcManager`, `CANLog`) y eliminar contratos.

### `config/app_config.json` + `config/app_config.py`
- **Qué lo hace sobreingeniería:** “mega archivo” mezclando strings y opciones; difícil navegación.
- **Costo:** menor legibilidad y mantenimiento, cambios dispersos.
- **Recomendación aplicada:** separar en `config/ui_text.py` y `config/defaults.py`, manteniendo
  overrides por `CANANALYZE_CONFIG`.

### `models/log_columns.py`
- **Qué lo hace sobreingeniería:** globals de UI/log en capa de modelos (dominio).
- **Costo:** mezcla de responsabilidades y más rutas de import.
- **Recomendación aplicada:** mover `DEFAULT_COLUMNS` a `config/defaults.py`.

### `models/view_signal.py`
- **Qué lo hace sobreingeniería:** clase ligada a UI (usa `QColor`) ubicada en `models/`.
- **Costo:** cruza responsabilidades (dominio ↔ UI), hace la estructura menos clara.
- **Recomendación aplicada:** mover a `viewmodels/view_signal.py`.

### `viewmodels/signal_viewmodel.py`
- **Qué lo hace sobreingeniería:** duplicado sin uso que solapa `ViewSignal`.
- **Costo:** ruido y ambigüedad al buscar “signal view model”.
- **Recomendación aplicada:** eliminar el archivo no referenciado.

## B. Señales típicas a buscar
- Clases `Manager/Helper/Handler` que solo delegan a otra función.
- Servicios con una sola implementación y una sola llamada (innecesarios).
- Interfaces/abstracciones sin múltiples implementaciones reales.
- 3–4 niveles de funciones que solo pasan parámetros.
- ViewModels demasiado delgados (solo passthrough) o demasiado gordos (mezclan IO/Qt).
- `utils/` con elementos de dominio o UI que deberían vivir en `core/` o `views/`.
- Config “mega archivo” con constantes mezcladas sin secciones claras.
