# Spike Mux Detection — informe

Análisis de solo lectura sobre muestras de logs de campo y el código existente. Se analizaron muestras de 6–30 MB por log (200k–650k tramas), no los 19 GB completos.

## 1. Resumen

1. El mux real de estas máquinas **no es el mux "de manual" (1 byte, round-robin, DBC `M`/`mN`)**. Predominan dos familias:
   - **Parámetro-por-ID** ("publicación de parámetros"): `[tag:1][índice:2][subíndice:1][valor:4]`. Es el patrón de Epiroc en `3E0/3E1` y `3F0` y de Komatsu en `16FF0021/16FF2100`. El selector mide **3–4 bytes** y tiene **40–100 valores**; el valor es float32/int32.
   - **Bloque: contador + índice de paquete**: Komatsu `24F/26F/20F/221…` (byte 0 = contador de bloque que rueda, **byte 1 = selector**, 8 valores, un bloque cada 100 ms).
2. La verdad de campo viene de los `.conf` del usuario (`mux_start`, `mux_bytes`, `mux_value`): las ~70 señales de Epiroc usan `3E0/3E1` con **mux_start 0, 4 bytes** (ej. `30 80 E5 00`); Komatsu usa 4 bytes en `16FF0021` (`0x2100000A`, payload float32 BE ≈ 87) y **1 byte en la posición 1** en `24F/26F`.
3. El detector actual **falla en lo que importa** (selecciona contadores y prefijos, tarda 14–48 s por ID). El experimento NMI (`d17ac10`) acierta el selector de 1 byte de Komatsu (`24F/26F/20F`, 0.1–0.3 s por ID) pero **nunca llega a 3–4 bytes** y no modela multi-nivel.
4. El **DLC varía dentro del mismo ciclo de mux** (Epiroc `4E0/4EC/4F0`: valores 0–2 con DLC 8 y valor 3 con DLC 4; Komatsu `16FFxxxx`: DLC 2,3,4,5,7,8). Agrupar por (ID, LEN) parte el ciclo. El detector debe agrupar por ID y tratar LEN como contexto.
5. Propuesta: selector contiguo de 1–4 bytes en cualquier posición (más nibbles/bits como exploración), puntuado por ganancia de información condicional por byte con corrección de sesgo, más reglas de secuencia (tasa de cambio, determinismo, periodicidad), más un paso de **extensión** de ancho. Cabe en ADR 001 (batch en QThread con %/ETA; en vivo con contadores incrementales O(chunk)).

## 2. Hallazgos por máquina

Notación: `Bs+w` = bytes `s..s+w-1` concatenados. K = valores del selector con soporte suficiente. "Verdad" = `.conf` del usuario.

| Máquina | ID (LEN) | Selector observado | Valores | Patrón / periodo | Tipo |
|---|---|---|---|---|---|
| Boltec | `3E0` (8; también 5) | verdad `B0+4`; medido `B1+3`, 70 valores distintos, K≈42 con soporte | 42–70 | Dirigido por eventos; periodo mediano 70–160 ms por valor, ráfagas (CV>10); los `0x20` son petición/ack (`20082C01 FFFFFFFF`), los `0x30` son valores | Parámetro-por-ID (tag+índice16+subíndice+float32 LE) |
| Boltec | `3F0` (8) | `B0+4`, 17 valores distintos (K16) | 16 | Mezcla irregular: 28 ms a 5 s según valor (`A9` 28 ms, `B0` 160 ms, `FC` 300 ms, `A7..B1` 1.5–2 s) | Parámetro-por-ID |
| Boltec | `4EC/4F0` (8 y 4) | `B0+1` | 4 (00–03) | **Round-robin estricto** 00,01,02,03; 161.8 ms por valor (CV 0.08); el valor 03 llega con DLC 4 | Mux clásico con DLC variable |
| Boltec | `4E0` (8, 7, 4, 3, 6) | `B0+1` | 3 (00,01,02) | Secuencia 00,01,00,01,02 (5 tramas/ciclo), 8 tramas de datos de 7 B con índice `02 xx xx` | Transporte tipo TP / multi-trama, no mux de señales |
| Boltec | `460` (8) | bytes 0–3 | 3–4 | Los 4 bytes son un ID J1939 encapsulado (`18FFD0CF`, `14FF7A80`) + 4 B de datos | Pasarela J1939, selector de 4 bytes |
| Jumbo | `3E0/3E1` (8) | `B0+4`; byte 0 = `0x30`+boom; extensión recupera K65 de 70 | 65–70 | Igual que Boltec; `3E1` = boom 2 | Parámetro-por-ID |
| Jumbo | `3F0` (8) | `B0+3/4`, 18–20 valores | 18–20 | 82–483 ms por valor | Parámetro-por-ID |
| Jumbo | `4E0/4E1/4F0` (8) | `B0+1` | 3 | Round-robin 00,01,02; 169 ms por valor (CV 0.02–0.04) | Mux clásico |
| Simba | `3E0`, `3F0`, `4EC/4F0/4F1` | igual que Jumbo | 15–30 / 3–5 | Mismos IDs y estructura que Boltec/Jumbo | ídem |
| Simba (todas) | `1D8/1D9/1DA/1DB`, `2A0`, `2A2` | candidatos con K 7–50 y ganancia alta | — | Telemetría analógica con bytes de estado; **no verificado** como mux (sin verdad de campo) | Dudoso |
| Komatsu 785 | `24F`, `26F`, `20F`, `221` (8) | verdad `B1+1` (mux_start 1, 1 byte) | 8 (01–08) | Bloque cada 100 ms; byte 0 = contador de bloque (`1A,1B,1C…`); no todos los índices aparecen en cada bloque (a veces falta 04 o 06) | Contador + índice de paquete |
| Komatsu 785 | `16FF0021` (8; también 2,3,4,5,7) | verdad `B0+4`, 94 valores distintos | 94 | Jerarquía: byte 1 ∈ {C3, FF, 02, 04, 00} (K5), luego `[FFFF 4A..57]` o `[C3 08 xx]`; `2100000A` = Payload float32 BE, periodo 0.56 s; `21C308xx` 0.70 s (CV 0.01–0.07) | Multi-nivel + parámetro-por-ID, DLC variable |
| Komatsu 785 | `16FF2100`, `16FF0121`, `16FF0421/0621`, `16FF2104/2106` | verdad `B0+4` (Hourmeter, `mux_value` "13") | K 4–90 | DLC 2–8 mezclados: petición/respuesta propietaria PropB (`PGN FF00`) con transporte | J1939 propietario con selector multibyte |
| Komatsu 785 | `14F` (8) | verdad: **sin mux** (Speed directo) | — | Un detector ingenuo marca `B0` (K7, tasa de cambio 0.00) | Control negativo |
| otra máquina de perforación | 3 IDs de 1 Hz–62 fps | sin candidatos > 0.5 | — | Control negativo; mejor candidato `182 B2+1` con G=0.47 (por debajo del umbral) | Sin mux |

Notas:
- otros equipos Jumbo solo trae exportes Ethernet (no CAN); otros logs de campo no se pudo leer con mi cargador (formato distinto). Ambos **sin verificar**.
- Distinción: heartbeats CANopen (`0x700+nodo`, `720..770`) y el resto de IDs de ~12 fps con campos constantes **no son mux**. En Epiroc `3EC` el byte 4 (`30,31,32…`) es un **contador**. En Komatsu el byte 0 de `24F` es un **contador de bloque**. Ninguno debe elegirse como selector.
- No se vio DM1/BAM en estos logs de forma que confundiera al detector: los `18FECA00/01` de Komatsu son DM1 con 32 y 520 tramas (por debajo del soporte mínimo).

## 3. Evaluación de los detectores actuales

Misma muestra, tiempos por ID en una sola máquina:

| Caso (verdad) | Detector actual | NMI `d17ac10` | Propuesta (prototipo `scan2/ext`) |
|---|---|---|---|
| Komatsu `24F` (`B1+1`) | `6B 04` (contador+índice, 35 tramas), **48 s** | `B1+1` K8 ✔ (0.1 s) | `B1+1` K8 ✔ |
| Komatsu `26F` (`B1+1`) | `4D` (byte 0), 22 s ✘ | `B1+1` K8 ✔ | `B1+1` K8 ✔ (G 0.78) |
| Komatsu `20F`, `221` | `2E` ✘, 14 s | `B1+1` K8 ✔ | `B1+1` K8 ✔ (G 1.00) |
| Komatsu `14F` (sin mux) | **falso positivo** `06 93`, 45 s | **falso positivo** `B0+1` K7 (0.58) | descartado por tasa de cambio ≈ 0 |
| Komatsu `16FF0021` len 8 (`B0+4`, 94) | `21 00` y 4 prefijos sueltos ✘ (3 s) | `B1+1` K5 (parcial) | **falla**: `B1+1` K5; el multi-nivel no se recupera con la extensión (ver 5.4) |
| Epiroc `3E0` len 8 (`B0+4`) | mejor `20` (el byte de petición); los patrones `30 05`, `30 80` aparecen sueltos; 1.9 s | `B1+1` K12 (parcial) | `B1+2` K40 → extensión `B1+3` K42 (Boltec) / **`B0+4` K65 (Jumbo)** ✔ |
| Epiroc `3F0` len 8 (`B0+4`) | `00 05` (K1 dominante) | `B2+1` K17 | `B2+1` → extensión `B0+4` K16 ✔ |
| Epiroc `4EC/4F0` (`B0+1`) | `00` (3 patrones de 4230) | `B0+1` K3 ✔ (marca *counter-like*) | `B0+1` K3 G 1.00 ✔; hay que fusionar LEN para ver el 4º valor |
| Epiroc `4E0` len 8 | `01 00` | `B0+1` K3 (G 0.66) | `B0+1` K3 (G 0.33–0.67): es transporte, no mux de señales |

Conclusiones:
- **Actual:** devuelve prefijos de 1–4 bytes ordenados por soporte/entropía; no distingue contador de selector; no devuelve "un selector + tabla de valores"; sin umbral para "no hay mux". Coste alto (14–48 s por ID con 40–55k tramas; unos 3 min para 5 IDs de Komatsu), sin respetar ADR 001.
- **NMI:** rápido y correcto con selectores de 1 byte; su regla de parsimonia elige siempre el selector **más angosto**, y el ancho máximo (`candidate_widths (1,2,3,4)`) sirve pero la cardinalidad máxima (32 y 20 % del grupo) y `min_covered_ratio` descartan selectores de 40–100 valores. Falso positivo en `14F`.
- Ninguno agrupa por ID con LEN variable ni modela multi-nivel.

## 4. Algoritmo propuesto

### 4.1 Entradas y agrupación
Agrupar por **CAN ID** (no por ID+LEN). Cada trama aporta (ts, len, bytes rellenados con cero y máscara de validez). Un valor de selector solo existe si `len > s+w-1`; las tramas más cortas pasan al selector ampliado `(len)` como contexto (resuelve `4EC` con valor 03 en DLC 4).

### 4.2 Candidatos de selector
- **Núcleo (MVP):** ventanas contiguas de 1 a 4 bytes (`B0+1`…`B7+1`, `B0+2`…, hasta 4) = 26 ventanas para DLC 8. Cubre todos los casos verificados (1, 2, 3 y 4 bytes).
- **Exploratorio (fase 2):** nibbles (`NL/NH`) y ventanas de 2–8 bits en cualquier posición. En mis pruebas las ventanas de bits arbitrarias **generaron muchísimo ruido** sobre bytes analógicos (R alto con selectores que son un sensor), así que solo se activan si no hay candidato de byte y con un umbral más estricto.
- Endianness: el selector se trata como entero big-endian de los bytes; solo importa para mostrar. Para exportar a DBC se emite con el orden que el usuario confirme.

### 4.3 Filtros de admisión
Para una ventana con valores `v`:
- `K` = valores con soporte `≥ max(5, 0.1 % n)`; `2 ≤ K ≤ 128` (Epiroc 42–70, Komatsu 94: el tope del NMI de 32 es insuficiente).
- Cobertura `≥ 0.97` de las tramas dentro de valores con soporte (descarta ventanas que cortan un sensor: `B1+4` de `3E0` tiene cobertura 0.63).
- Tasa de cambio del selector entre tramas consecutivas `chg ≥ 0.05` (descarta estados lentos como `14F`; round-robin ≈ 1.0, eventos ≈ 0.2–1.0).

### 4.4 Puntuación
- **G (ganancia condicional):** para cada byte `c` fuera del selector con entropía marginal `H(c) ≥ 0.5` bit, `g_c = (H(c) − H(c|sel) − sesgo) / H(c)`, con corrección de Miller-Madow `sesgo = (K−1)(kx−1)/(2 n ln2)`. `G` = media de la **mitad superior** de los `g_c` (un selector no debe ser castigado por convivir con un sensor independiente). Umbral de aceptación `G ≥ 0.5`.
- **Estructura de secuencia:** `chg` (tasa de cambio), `P` = determinismo del sucesor (`Σ max_succ / n`, round-robin ≈ 1.0), periodo por valor y CV (`perval.py`: Epiroc 4EC 161.8 ms CV 0.08; Komatsu `21C308xx` 0.70 s CV 0.01).
- **Contador vs selector:** un contador (byte 0 de Komatsu `24F`, byte 4 de Epiroc `3EC`) tiene `G ≈ 0` y su sucesor `v+1` con determinismo alto; se marca `counter_like` y se excluye de la elección (NMI ya lo marca). Se confirma además con la tasa de bits que cambian (READ, ver §8): el LSB de un contador cambia en cada trama y un selector round-robin con K no potencia de 2 no sigue la regla `y_j = 2 y_{j-1}`.
- **Confianza:** `0.5·G + 0.25·cov + 0.25·P` (propuesta; calibrar con fixtures), mostrada como bajo/medio/alto.

### 4.5 Elección y extensión
1. Entre los admitidos, quedarse con los que alcanzan `≥ 0.9 × G_max`; priorizar menor ancho y posición más baja (parsimonia como NMI).
2. **Extensión** (prototipo `ext.py`): desde el mínimo, añadir el byte vecino (izq. o der., hasta 4) si `cov ≥ 0.97`, `K_nuevo ≤ 2 × K` y `G_nuevo ≥ 0.9 × G`. Resultado medido: Jumbo `3E0` pasa de `B1+2` K42 a **`B0+4` K65** (coincide con la verdad); Boltec `3E0` llega a `B1+3` (el byte 0 `0x20/0x30` no se fusiona); `3F0` y `4EC` llegan a `B0+4`. La UI deja al usuario reducir o ampliar.
3. **Multi-nivel:** si tras elegir selector `S1` un subconjunto de sus valores tiene un segundo selector con `G` alta *condicionado a ese valor*, ofrecerlo como nivel 2 (`16FF0021`: `B1` K5, luego `B2+2`/`B3+1`). **Fuera del MVP**; el MVP solo informa "hay estructura jerárquica" cuando el K aumenta más de 2× al extender.

### 4.6 Valores y tabla por valor
Para el selector confirmado: valor (hex), frecuencia, periodo mediano y CV, DLC dominante, rango de cada byte restante, huella "regular / dirigido por eventos". Esta es la tabla que alimenta Candidate y Bit Activity.

### 4.7 Complejidad
- **Offline (batch en QThread con % y ETA):** por grupo ≈ 26 ventanas × ≤ 7 columnas × `bincount(K·256)` = O(n · 200). Prototipo en NumPy: 0.2–0.9 s por log de 175k–650k tramas con tope de 60k tramas por grupo. Progreso = grupos terminados / total; ETA por tramas procesadas.
- **En vivo (O(chunk)):** por (ID, ventana) mantener contadores acumulados: tabla `K × 256` por columna, tabla de transiciones `K × K`, último valor, último timestamp por valor. Actualizar con el chunk crudo de `chunk_ready` (sin recorrer el df acumulado). Si `distinct > 128`, la ventana se marca muerta y se libera. La puntuación se recalcula sobre los contadores (O(K·256) por ventana), no sobre tramas.
- Sin tope de RAM global (ADR 002): estado acotado por ID × 26 ventanas × (K·256·7).

## 5. Integración

- **Config MUX compartida (F3-03):** `MuxConfigEntry(can_id, length|None, mux_bytes)` ya soporta bytes sueltos y LEN `None` (comodín). El resultado `B1+3` → `mux_bytes=(1,2,3)`, `length=None`. "Aplicar a configuración compartida" crea o reemplaza la regla (el normalizador rechaza reglas contradictorias para la misma pareja ID/LEN, hay que avisar al usuario).
- **Candidate / Bit Activity (F6-01/F6-02):** reutilizan los perfiles por grupo ID/LEN/MUX; el detector no calcula bit activity, solo el selector. Con la regla aplicada, Candidate ya separa por valor; la tabla por valor del detector sirve para filtrar valores con soporte insuficiente.
- **Working DBC (F4-01):** `services/working_dbc.py` ya acepta `is_multiplexer`, `multiplexer_signal`, `multiplexer_ids`. Verificado con  41.4.3: un mensaje con selector de 16 bits `SG_ Sel M : 8|16@0+` y señales `m1285/m1286` produce `signal_tree = [{'Sel': {1285: ['P1'], 1286: ['P2']}}]`. Al guardar una señal desde un grupo mux, exportar el selector como `M` y la señal como `m<valor>`. **Atención:** `message.decode()` lanza `DecodeError` si el valor del selector no está declarado; el decoder del Working DBC debe capturar el error o prefiltrar por los valores declarados, o un valor nuevo rompe la decodificación del mensaje completo (no probado en el repo).
- **Multi-nivel en DBC:** las `SG_MUL_VAL_` (mux extendido) solo en una fase posterior. En esta , un mensaje con `m1M` sin `SG_MUL_VAL_` para todas las hojas dio "signals overlapping" al cargar: no generar mux extendido sin pruebas de ida y vuelta.

## 6. UX propuesta

Ventana "Mux Detection" (la existente, rediseñada), flujo en tres pasos:
1. **Alcance:** IDs a analizar (todos por defecto, con rango de tiempo compartido), botón *Analizar*; diálogo de espera con % y ETA.
2. **Resultados por ID** (lista izquierda con insignia alta/media/baja y filtro "ocultar sin mux"): selector propuesto como chips de byte clicables `[B1][B2][B3]` (el usuario amplía o reduce y se recalcula en el acto), indicador de contador descartado ("B0 parece contador de bloque"), aviso "DLC variable: 4 valores, 1 con DLC 4" y aviso "estructura jerárquica sospechosa".
3. **Tabla de valores:** valor hex, N tramas, periodo mediano y CV, DLC, mini-resumen de bytes restantes; columnas ordenables; casilla por fila para excluir valores. Pie con confianza, *Aplicar a configuración MUX compartida*, *Abrir en Candidate con este mux*.

En vivo: el mismo panel con estado "recopilando… N tramas/ID", sin aplicar automáticamente; el usuario confirma.

## 7. Riesgos, incógnitas y alcance

**Riesgos / sin verificar**
- Umbrales (`G ≥ 0.5`, `K ≤ 128`, `chg ≥ 0.05`, tolerancia 0.9 y 2×) calibrados sobre los mismos logs; riesgo de sobreajuste. Hay que validar con más IDs y con los logs completos.
- El valor float32 (4 bytes) tiene bytes bajos casi aleatorios; `G` usa la mitad superior de las columnas, pero con sensores con poca variación puede subestimar.
- Los selectores cortos son sustrato de selectores largos (`B1+2` ⊂ `B0+4`); si el usuario espera `B0+4` y obtiene `B1+3`, la UI debe dejar ampliar. No hay criterio objetivo para incluir el byte de tipo (`0x20/0x30`).
- Multi-nivel real (Komatsu `16FF0021`) y transporte/TP/CANopen-SDO (Epiroc `4E0`, Komatsu `16FFxxxx` con DLC 2–8) no se resuelven con una sola capa de selector. Distinguir "mux" de "petición/respuesta con transporte" necesita reglas de secuencia que no validé.
- `Hourmeter` en el `.conf` tiene `mux_value: "13"` (cadena) con `mux_bytes: 4`: posible dato inconsistente en el archivo de campo.
- No se analizó otros logs y archivos de referencia de campo.

**MVP recomendado**
- Selector contiguo de 1–4 bytes, agrupado por ID (LEN como contexto), con extensión de ancho.
- Filtros + `G` + `chg`/`P` + marca `counter_like`.
- Tabla por valor (valor, N, periodo, CV, DLC).
- Batch en QThread con % y ETA; aplicar a configuración MUX compartida.
- Fixtures sintéticos y un script de verificación en carpeta de campo (solo lectura).

**Diferir**
- Selectores de bits/nibbles arbitrarios, multi-nivel, exportación DBC con `SG_MUL_VAL_`, detección en vivo incremental (diseño listo, implementación después), detección de transporte (TP/SDO/BAM).

## 8. Investigación externa

| Fuente | Qué aporta | Cómo informa el diseño |
|---|---|---|
| Buscemi, Engel, Shin, *Reverse Engineering of Multiplexed CAN Frames* (CAN-MXT), VehicleSec 2024, https://www.ndss-symposium.org/wp-content/uploads/vehiclesec2024-11-paper.pdf (texto leído) | Algoritmo que supone tramas **cíclicas**, selector en el **primer byte**, valores binarios consecutivos 0..N−1, N ≤ 256 y round-robin. Busca bits estáticos en la serie de subtramas de cada ciclo (XNOR estilo READ); exige al menos `log2(n)` bits estáticos consecutivos y valores distintos por subtrama; descarta contadores comparando el *bit flip rate* de la serie con el de todo el ID | Confirma: los supuestos de CAN-MXT **no se cumplen** en nuestros logs (selector en byte 1–3, eventos, K no potencia de 2, DLC variable). Se adopta la regla "selector ≠ contador por BFR" y el uso de periodicidad por valor; se descartan los supuestos de primer byte y round-robin |
| Weiß, Pozzobon, Mottok, Matoušek, *Automated Reverse Engineering of CAN Protocols*, Neural Network World 4/2021, https://www.nnw.cz/doi/2021/NNW.2021.31.015.pdf (texto leído) | El *bit-flip* entre tramas consecutivas por posición: campos mux de **2 a 4 bits**, el LSB cambia en cada trama (`y_j ≥ n`, `2 y_j ≈ y_{j−1}`), constantes y mux separan campos de datos | Respalda: la tasa de cambio del selector y la separación por selector; también el límite práctico de ancho bajo (en nuestros logs el ancho real es en bytes, por eso tamaño 1–4 B y ventanas de bits solo exploratorias) |
| Marchetti, Stabili, *READ: Reverse Engineering of Automotive Data Frames* (conocido por resultados de búsqueda y por CAN-MXT, que lo cita; no leído completo) | Tokenización por *bit flip rate*; identifica contadores y checksums | Para separar contador de selector (marca `counter_like`) |
| *ByCAN* (arXiv 2408.09265, https://arxiv.org/pdf/2408.09265; solo resumen de búsqueda) | Añaden tasa de flip, valor medio y *distinct value ratio* a nivel byte y bit | Justifican usar cardinalidad y razón de valores distintos como filtro de admisión (`K` y cobertura) |
| Enfoques de decodificación por etapas | Primero segmentan señales y luego decodifican endianness/signo; algunos clasifican con datos de cabina | Orden del pipeline: primero selector y subtramas, después tokenizar cada subserie (Candidate/Bit Activity por valor) |
| J1939: PropB `0x00FF00–0x00FFFF` (https://csselectronics.com/pages/j1939-pgn-list), CiA 510 (SDO sobre J1939, https://www.can-cia.org/can-knowledge/cia-510-mapping-of-sdo-and-emcy-protocols-to-j1939) | PropB es rango global definible por el fabricante; SDO puede viajar sobre J1939 | Komatsu `16FFxxxx` tiene DLC 2–8 y selector de varios bytes, compatible con SDO/petición-respuesta propietaria sobre PropB; **no encontré documentación pública específica de los fabricantes** |

No encontré material público específico del mux en maquinaria minera.

### 8.1 Guía concreta derivada
- Candidatos de selector: ventanas de byte de 1 a 4 en cualquier posición (obligatorio), ventanas de nibble y de 2–8 bits (opcional, solo si no hay candidato de byte).
- Puntuación: ganancia de información condicional por byte con corrección de sesgo, media de la mitad superior de bytes; más `chg`, `P`, periodicidad por valor.
- Umbrales iniciales: `2 ≤ K ≤ 128`; cobertura `≥ 0.97`; `chg ≥ 0.05`; `G ≥ 0.5`; extensión con tolerancia 0.9 en `G` y 2× en `K`.
- Validación cruzada observada: el ancho inferido coincide con la verdad en Komatsu `24F/26F/20F/221` (1 byte, K8), Jumbo `3E0` (4 bytes, K65 de 70), Epiroc `3F0` (4 bytes, K16), `4EC/4F0` (K3 round-robin con 4º valor en DLC 4); **no** coincide en Komatsu `16FF0021` (multi-nivel) ni en Boltec `3E0` (queda `B1+3` por el byte de comando).
