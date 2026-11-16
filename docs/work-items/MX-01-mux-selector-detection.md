# MX-01 — Detección de selector MUX (reescritura completa)

- **Estado:** Pendiente
- **Fase:** MX de `docs/plan.md`
- **Rama:** `feature/mx-01-mux-detection` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F3-03 (configuración MUX compartida, hecho), F6-01/F6-02 (consumidores de análisis), F7-01 (se implementa en secuencia después de J1939)
- **Base commit:** `<hash de dev al crear el worktree>`

## Problema
El usuario necesita encontrar el selector y los valores de mux de una máquina desconocida sin escribirlos a mano. En los logs de campo el mux real puede ser distinto al descrito en el manual: Epiroc `3E0/3E1` usa bytes 0–3 con unos 42–70 valores; Komatsu `24F/26F`, byte 1 con 8 valores; Komatsu `16FF0021`, cuatro bytes y 94 valores en dos niveles. El tráfico puede ser dirigido por eventos o round-robin, y tener DLC variable dentro del ciclo. El detector actual (`services/mux_detector.py`) devuelve prefijos de 1–4 bytes sin elegir un selector, toma contadores por selectores, marca falsos positivos en señales directas (Komatsu `14F`) y tarda 14–48 s por ID con 40–55k tramas. El experimento `d17ac10` acierta selectores de un byte, pero no llega a 3–4 bytes. Evidencia y números: [informe del spike](../review/2026-11-mux-spike.md).

## Propiedad
- **Puede editar:** `services/mux_detector.py`; `viewmodels/mux_detection_viewmodel.py`, `viewmodels/mux_detection_worker.py`; toda la ventana y manager de Mux Detection (`views/mux_detection_window*.py` y archivos relacionados); la entrada y cableado de la ribbon; `config/defaults.py`, `config/ui_text.py`; pruebas y fixtures sintéticos de mux; documentación de plan, pruebas, mapa de cobertura y arquitectura; `CHANGELOG.md`; esta tarjeta. Se permite reemplazar por completo detector, ventana, manager, ViewModel, worker y entrada de ribbon.
- **No puede editar:** HMI Video/OCR; servicios de streaming (`can_stream.py`, `realtime_analysis.py`); `models/mux_config.py` y `services/session_state.py` (se consumen); taxonomía Range Diff (F3-05); `services/candidate_interpretations.py` y `services/bit_activity.py` (se consumen); otras tarjetas. Los logs reales de campo son de solo lectura.

## Decisiones cerradas
- **Desbloqueo aprobado:** el usuario autorizó rehacer Mux Detection por completo, incluida su parte visual: «lo del mux puedes rehacerlo todo por si acaso hasta la parte visual; debe ser simple para el usuario y si quieres ponerle un modo avanzado». La aprobación está cerrada; no es una condición pendiente.
- La experiencia tiene dos niveles. El **modo simple** es el predeterminado: botón «Detectar mux» que abre un diálogo de progreso con porcentaje y ETA; lista de CAN IDs con selector propuesto en lenguaje llano (por ejemplo, «bytes 0-3» o «byte 1»), número de valores y confianza alta/media/baja; filtro «solo IDs con mux»; y «Aplicar» a la configuración MUX compartida, con aviso si existe una regla en conflicto. No expone umbrales ni jerga.
- El **modo avanzado** está en sección plegable o toggle, y su estado se recuerda entre sesiones. Incluye chips de bytes para ampliar o reducir el selector con recálculo, tabla de valores (valor, N, periodo mediano, CV, DLC) con exclusión individual por fila, control de sensibilidad y motivos de descarte con contadores para contador, DLC variable y sospecha de jerarquía. Incluye «Abrir en Candidate» con el mux aplicado.
- El detector agrupa por **CAN ID**; LEN es contexto del valor del selector (una trama más corta que el selector pertenece a otro valor), no clave de grupo. El selector es una ventana contigua de 1 a 4 bytes en cualquier posición. Nibbles y ventanas de bits quedan fuera del MVP.
- Filtros iniciales calibrables en `config/defaults.py`: `2 ≤ K ≤ 128` valores, soporte `≥ max(5, 0.1 % de tramas)`, cobertura `≥ 0.97` y tasa de cambio `≥ 0.05`. La puntuación `G` es ganancia de información condicional por byte con corrección de Miller–Madow; aceptación inicial `G ≥ 0.5`. Sin evidencia suficiente, el resultado es «sin mux». Los detalles de puntuación se mantienen internos y se explican solo en modo avanzado cuando sea útil.
- **Contador ≠ selector:** una ventana con ganancia casi nula y sucesor `v+1` determinista se marca como contador y no se recomienda (p. ej., Komatsu `24F` byte 0, Epiroc `3EC` byte 4).
- Parsimonia: entre candidatos con `G ≥ 0.9 × G_max`, se elige el más estrecho y de menor posición; se intenta extender un byte vecino si cobertura `≥ 0.97`, `K ≤ 2×` y `G ≥ 0.9 ×`. Si al extender K crece más de 2×, se avisa de estructura jerárquica sospechosa. El mux multinivel y `SG_MUL_VAL_` quedan fuera.
- Salida: recomendación por ID (selector, cantidad de valores, confianza, marcas de contador, DLC variable y jerarquía) y tabla por valor (valor, N, periodo mediano, CV, DLC dominante). Servicio Qt-free, sin importar `can`/`paramiko`.
- Batch offline en un `QThread` propiedad del ViewModel, progreso con porcentaje y ETA, cancelación y resultados por ID. En vivo queda fuera del MVP; cualquier evolución será incremental desde chunks crudos de `chunk_ready` (ADR 001).
- «Aplicar» escribe `MuxConfigEntry(can_id, length=None, mux_bytes=...)` en el `MuxConfigurationViewModel` compartido (F3-03), avisando si choca con una regla existente. No escribe al Working DBC.
- Constantes en `config/defaults.py`, textos vía `get_text()`.

## Trabajo
1. Reescribir `services/mux_detector.py`: agrupación por ID, búsqueda de ventanas de 1–4 bytes, filtros, puntuación y evidencia temporal, detección de contador, parsimonia/extensión y tabla por valor.
2. Sustituir/adaptar ViewModel y worker: progreso con porcentaje y ETA, cancelación, estado del modo avanzado, recálculo por selector, aplicación a configuración compartida y apertura de Candidate con el mux aplicado.
3. Rehacer la ventana completa con modo simple predeterminado y modo avanzado plegable, usando textos traducibles, tokens del tema y el sistema de iconos.
4. Reemplazar el manager y reactivar/cablear la entrada de la ribbon con ciclo de vida `Qt.WA_DeleteOnClose`.
5. Retirar el comportamiento antiguo de prefijos, `refinement_gain`, `semantic_score` y `strictness`; la sensibilidad avanzada controla la tolerancia del detector.
6. Añadir pruebas sintéticas y actualizar documentación de pruebas, arquitectura, plan y changelog.

## Pruebas
- Regresión primero (rojo → verde), con fixtures sintéticos anonimizados de unas 3–5k tramas y semilla fija: selector de 40 valores en ventana de varios bytes; contador más índice donde se recomienda el índice; round-robin con DLC variable; negativos de señal directa, contador puro, bytes constantes y ruido; señal analógica confundente; y estructura de dos niveles que genera aviso sin inventar un selector de cuatro bytes. Verificar determinismo y que el orden de entrada de IDs no cambie la salida.
- Rendimiento: 100k tramas × 40 IDs en menos de 10 s en el batch de referencia, documentando el tiempo medido; no recorrer el DataFrame acumulado repetidamente.
- Opcional, fuera de la suite y solo lectura: script que procese un log candump/Kvaser pasado por argumento y compare con `.conf`; nunca escribe en la carpeta de campo ni se ejecuta por defecto.
- Suite completa verde.
- `/verify-ui`: usar un log Epiroc y uno Komatsu de la carpeta de campo, siempre en solo lectura. Verificar diálogo con porcentaje y ETA, experiencia simple predeterminada sin umbrales ni jerga, selector en lenguaje llano, valores/confianza, filtro y aplicación con aviso de conflicto. En modo avanzado verificar preferencia recordada, chips con recálculo, exclusión por fila, sensibilidad, motivos de descarte y apertura de Candidate con mux aplicado. Revisar capturas en tema claro y oscuro.

## Cierre
- [ ] CHANGELOG `## Unreleased`
- [ ] fila de `docs/plan.md` cerrada
- [ ] `docs/bugs.md` si aplica
- [ ] `docs/architecture/overview.md` y `docs/testing.md` actualizados
