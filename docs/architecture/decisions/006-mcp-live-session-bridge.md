# 006 — Puente MCP local a la sesión abierta

- **Estado:** Aceptado
- **Fecha:** 2026-11-02

## Contexto

M-01 inicia un proceso MCP independiente que carga su propio log. No puede consultar la captura,
el log ni el `AnalysisContext` de la app gráfica. Pasar el DataFrame completo por cada llamada
duplicaría memoria y recorrería la historia durante la captura.

## Decisión

- La app publica una sesión local por usuario mediante un named pipe de Windows o socket local en
  otros sistemas, autenticado con una clave aleatoria y descubierto mediante un descriptor privado
  en el directorio de datos de Canlytics.
- Un `QThread` propiedad de `MainWindowViewModel` atiende el IPC. El hilo solo accede a un snapshot
  Qt-free con bloqueo; nunca llama a widgets ni a ViewModels.
- El snapshot conserva estado, IDs, origen, contexto y un anillo acotado de frames recientes,
  actualizado desde deltas. La lectura devuelve como máximo 500 frames.
- MCP puede consultar la sesión, frames recientes, contexto y marcadores efímeros, además de añadir
  marcadores con timestamp absoluto. No puede cambiar el contexto, cargar/reemplazar el log, borrar
  datos ni enviar CAN por este puente.
- La conexión solo existe mientras viva la app. El stdio de MCP sigue siendo el transporte entre
  cliente y servidor; este puente es exclusivamente local entre procesos.

## Consecuencias

- Los clientes MCP pueden observar la captura sin copiar el DataFrame completo ni retrasar el hilo
  de la UI con consultas históricas.
- Los marcadores añadidos por MCP viven en memoria durante esa sesión; `save_markers` sigue siendo
  una exportación JSON independiente.
- Los frames antiguos que ya salieron del anillo no están disponibles por este endpoint.
- La clave local protege el protocolo entre usuarios/procesos no autorizados; procesos del mismo
  usuario pueden leer archivos privados de la aplicación.
