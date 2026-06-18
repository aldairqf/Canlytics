# Fixtures de prueba (DBC + logs reales)

Datos reales **pequeños** para tests de caracterización que los datos sintéticos no
cubren (señales multiplexadas reales, el formato exacto de tu candump/Kvaser, BAM, etc.).

## Convención

```
tests/fixtures/
  dbc/    <- coloca aquí tus *.dbc
  logs/   <- coloca aquí tus logs (candump / Kvaser Memorator), cualquier extensión
```

Los tests en [tests/test_fixtures_real.py](../test_fixtures_real.py) descubren **todos** los
ficheros de estas carpetas y validan invariantes genéricas (el DBC carga y tiene mensajes;
el log parsea a un DataFrame con el `FRAME_SCHEMA` correcto y no vacío). No necesitas tocar
los tests al añadir un fichero: aparecen como sub-tests nuevos automáticamente.

Si las carpetas están vacías, los tests se **SKIPean** (no fallan), para que la suite siga
corriendo en cualquier entorno.

## Contenido actual

- `dbc/j1939_clean.dbc` — base J1939 estándar (resuelve PGNs por modo `j1939`).
- `dbc/MS4M.dbc` — DBC propio mínimo.
- `logs/candump-sample.log` — recorte (~58 KB, 1150 líneas) de un candump real; contiene
  una sesión BAM completa (TP.CM + 5 TP.DT, PGN 0xFEE3) y tramas normales.

## Notas

- **J1939/BAM requiere modo `j1939`.** Al cargar un DBC su modo por defecto es `exact`;
  `decode_frame` / `get_message_by_pgn` solo resuelven PGNs (y BAM) si la entrada está en
  modo `j1939` (`mgr.set_entry_mode(name, "j1939")`). Por eso `test_real_bam_decode.py` lo
  fija en `setUpClass`.

## Reglas

- **Mantenlos pequeños.** Recorta los logs a unas pocas decenas/cientos de KB — lo justo
  para ejercitar el parseo y la decodificación. Los ficheros se commitean al repo y quedan
  en el historial para siempre (el log original de 37 MB se recortó a 58 KB).
- **No subas datos confidenciales/propietarios.** Usa solo material que pueda vivir en el
  repo público. Si un log es sensible, recórtalo/anonimízalo antes.
