# Plugins de Canlytics

Los plugins amplían Canlytics con código Python de confianza. Se ejecutan con los permisos
del usuario, dentro del proceso de la app y sin sandbox. Activa solo plugins de fuentes que
confíes; uno defectuoso puede bloquear la interfaz, leer archivos o acceder al hardware.

## Instalar y administrar

Coloca cada plugin en una carpeta dentro de `%APPDATA%/Canlytics/plugins` (Windows) o define
`CANLYTICS_PLUGINS_DIR` para usar otra carpeta. Los paquetes instalados pueden publicar un
entry point en el grupo `canlytics.plugins`. Para instalar uno junto a la app, usa el mismo
directorio como destino de pip:

```powershell
python -m pip install --target "$env:APPDATA/Canlytics/plugins" package-name
```

El cargador también busca allí los metadatos `.dist-info` y añade esa ruta al importar el
paquete. Abre **Settings → Plugins** para ver el origen,
el estado y los errores de cada plugin, y para activarlo o desactivarlo. Los plugins habilitados
se cargan al iniciar la app. La preferencia se guarda en `.canlytics_state/plugins.json`; los
plugins nuevos empiezan desactivados.

Un plugin de carpeta lleva `plugin.toml` y el módulo indicado por `entry_point`:

```toml
[plugin]
id = "company-csv-export"
name = "Company CSV Export"
version = "1.0.0"
api_version = 1
entry_point = "plugin:register"
```

El módulo debe definir `register(api, context)`. El cargador valida la metadata y llama esa
función al activar el plugin. Los errores quedan en la pantalla Plugins y no impiden cargar
los demás.

## SDK inicial

Importa el contrato desde `canlytics_sdk`. `PluginAPI` permite registrar fuentes de DBC,
importadores y exportadores de logs. Cada nombre debe ser único dentro de su tipo. El `context`
ofrece:

- `frame_schema` y `get_frames()` para leer una copia del DataFrame con el contrato de frames.
- `list_dbc_names()`, `decode_frame(...)` y `get_working_dbc_messages()` con información del DBC
  cargado y un snapshot inmutable del DBC de trabajo.
- `analysis.summarize(...)`, `analysis.candidates(...)` y `analysis.compare_ranges(...)`, que
  llaman los servicios Qt-free compartidos. Candidate usa por defecto señales de 8 bits little
  endian sin signo; se pueden ajustar longitud, granularidad, tipo, endianess y bytes.
- `export_log(dataframe, path)`, que escribe los formatos estándar y protege logs y DBCs fuente
  contra sobrescritura.

Los callbacks registrados forman la interfaz para las pantallas de Plugins de las siguientes
tarjetas. Esta tarjeta los descubre y valida, pero no añade todavía acciones ni ventanas de
plugins al flujo principal.

## Plugin de ejemplo

`examples/plugins/csv_snapshot` registra un exportador CSV. Cópialo a la carpeta de plugins para
probarlo; la app no lo instala ni activa automáticamente.

Los entry points de paquetes deben resolver a un `PluginDescriptor` con `id`, `name`, `version`,
`api_version` y `register`. Declara el entry point en `pyproject.toml` bajo el grupo
`canlytics.plugins`; el nombre del entry point debe coincidir con `id` del descriptor, y la
versión de API debe coincidir con la del host.
