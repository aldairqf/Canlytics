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
se cargan al iniciar la app. La preferencia se guarda en `plugins.json` dentro del directorio
de estado por usuario (`%APPDATA%/Canlytics/state` en Windows); los
plugins nuevos empiezan desactivados.

Un plugin de carpeta lleva `plugin.toml` y el módulo indicado por `entry_point`:

```toml
[plugin]
id = "company-csv-export"
name = "Company CSV Export"
version = "1.0.0"
api_version = 2
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

## Herramientas MCP

Un plugin puede registrar callbacks tipados para que `python -m mcp_server` los publique:

```python
def register(api, context):
    def scale_value(value: float, factor: float = 1.0) -> float:
        return value * factor

    api.register_mcp_tool(
        "scale_value", scale_value, description="Scale a numeric value"
    )
```

El servidor publica el nombre namespaced `p18_company-csv-export_scale_value`. El prefijo lleva
la longitud del ID para evitar colisiones entre plugins cuyos IDs contienen guiones bajos; los
nombres del tool aceptan hasta 43 letras, números, guiones o guiones bajos. Las anotaciones del
callback definen y validan el esquema de entrada. Solo se cargan los plugins habilitados
en el directorio de estado por usuario; el servidor MCP usa el mismo archivo que la app. Define
`CANLYTICS_STATE_DIR` para cambiar la raíz compartida, o `CANLYTICS_PLUGIN_STATE` para indicar
directamente el archivo `plugins.json`. En modo headless el contexto permite leer el DataFrame y usar análisis Qt-free, pero no
ofrece DBC, acciones de UI, suscripciones en vivo ni transmisión CAN.

## Plugin de ejemplo

`examples/plugins/csv_snapshot` registra un exportador CSV. Cópialo a la carpeta de plugins para
probarlo; la app no lo instala ni activa automáticamente.

Los entry points de paquetes deben resolver a un `PluginDescriptor` con `id`, `name`, `version`,
`api_version` y `register`. El host usa SDK API 2 y mantiene compatibilidad con API 1; los plugins API 1 siguen cargando, pero las funciones de transmision nuevas requieren API 2. Declara el entry point en `pyproject.toml` bajo el grupo
`canlytics.plugins`; el nombre del entry point debe coincidir con `id` del descriptor, y la
versión de API se valida contra `SUPPORTED_PLUGIN_API_VERSIONS`; el host sigue cargando API 1 y API 2.

## Transmision J1939

`context.send_pgn(pgn, data, source_address=..., destination_address=255)` transmits J1939 PGNs; `request_pgn(...)` requests one and `wait_for(pgn, sa, timeout, local_source_address=...)` awaits a response asynchronously. Pass `local_source_address` to `wait_for` before calling `request_pgn` when the response may use CMDT.
`send_pgn` and `wait_for` return `concurrent.futures.Future`. Their completion callbacks are queued to the GUI thread, including callbacks attached after an immediate failure. If the GUI application is unavailable, the future fails and its callbacks are not run. Never block the UI waiting for a result.
Large payloads use BAM for the global address or RTS/CTS for a directed address. The sender supports partial and repeated CTS windows, CTS hold, T3 for CTS/EOM ACK, T4 for CTS hold, Abort, and timeout. The CMDT receiver caps each CTS by the peer RTS limit and configured window; it uses T2 after CTS and T1 between DT packets. Local source addresses are scoped to each `wait_for` call, so register the waiter before requesting the response.
BAM sends DT frames at a configurable 50 ms interval (50-200 ms). Every frame passes through CAN Send validation and enters TX Log; replay is rejected without extra confirmations or rate limits. `wait_for` timeouts are capped at one hour. DM14/DM15/DM16 are outside this generic API. Use this non-blocking pattern from a GUI action:

```python
def on_done(future):
    try:
        response = future.result()
    except Exception as error:
        show_error(error)
    else:
        show_response(response)

future = context.wait_for(0xFECA, 0x80, timeout=2.0, local_source_address=0xF9)
future.add_done_callback(on_done)
request = context.request_pgn(0xFECA, source_address=0xF9, destination_address=0x80)
```

Completion callbacks are queued onto the GUI thread, including callbacks attached after an immediate failure; keep them short. Never call `future.result()` before completion from a GUI action.
