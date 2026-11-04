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

Desde **Settings > Plugins > Import** puedes elegir una carpeta o un archivo ZIP. La carpeta
se copia al directorio configurado. El ZIP debe contener `plugin.toml` en la raíz o dentro de
una única carpeta superior; sus archivos se extraen al directorio configurado. En ambos casos
se valida la metadata, no se sobrescriben IDs existentes y el plugin queda desactivado.
Los ZIP rechazan rutas inseguras y symlinks; se limitan a 4096 entradas, 50 MiB por archivo y
100 MiB descomprimidos en total.

Para distribuir un paquete Python con dependencias se puede publicar un wheel (`.whl`) con el
entry point `canlytics.plugins` e instalarlo con pip en el directorio de plugins. Wheel es el
formato estándar de distribución de Python. El ZIP de Import usa el manifiesto propio de
Canlytics y no instala dependencias.

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

`PluginAPI` permite registrar ventanas con `register_window(name, factory)`, acciones de
`Enviar a…` con `register_send_to_action(name, callback)` y acciones contextuales con
`register_context_action(name, callback)`. Las ventanas aparecen en el grupo Plugins del ribbon;
las acciones reciben `AnalysisContext` y sus errores no interrumpen la app.

Para datos incrementales, `context.subscribe_live_chunks(callback, lifetime=widget)` entrega
copias de chunks crudos en el hilo de UI y se desconecta al destruir el widget o desactivar el
plugin. Cada callback procesa solo el chunk recibido. `AnalysisContext.markers` lleva marcadores
cuando quien crea el contexto los incluye.

`context.list_session_markers()` consulta los marcadores efímeros de la sesión.
`context.send_frame(can_id, data, extended=False)` transmite frames clásicos solo con una
conexión real activa; replay y desconexión se rechazan y cada intento aparece en TX Log.

## Plugin de ejemplo

`examples/plugins/csv_snapshot` registra un exportador CSV. Cópialo a la carpeta de plugins para
probarlo; la app no lo instala ni activa automáticamente.

Los entry points de paquetes deben resolver a un `PluginDescriptor` con `id`, `name`, `version`,
`api_version` y `register`. Declara el entry point en `pyproject.toml` bajo el grupo
`canlytics.plugins`; el nombre del entry point debe coincidir con `id` del descriptor, y la
versión de API debe coincidir con la del host.
