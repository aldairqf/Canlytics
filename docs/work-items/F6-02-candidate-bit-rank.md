# F6-02 - Ranking de senales candidatas por actividad de bits

- **Estado:** Hecho
- **Fase:** 6 de `docs/plan.md`
- **Rama:** `feature/f6-02-candidate-bit-rank` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** F6-01, F3-02
- **Base commit:** `24df82e`
- **Referencias:** [ADR 001](../architecture/decisions/001-streaming-append-delta.md), [ADR 004](../architecture/decisions/004-analysis-context.md), [CAN-D](https://arxiv.org/abs/2006.05993)

## Problema

Candidate enumera lecturas posibles sin incorporar los limites y las clases de actividad observados en F6-01. Contadores y CRC compiten con senales fisicas en los primeros resultados, y el signo/endian no reciben una preferencia informada.

## Propiedad

- **Puede editar:** `services/candidate_interpretations.py`, `views/candidate_interpretations_window.py`, `config/ui_text.py`, `tests/test_candidate_interpretations.py`, pruebas UI de Candidate, `docs/plan.md`, `docs/testing.md`, `tests/README.md`, `docs/architecture/overview.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `services/bit_activity.py`, logica de Mux Detection, HMI/OCR, otras tarjetas.

## Decisiones cerradas

- Candidate calcula una vez el perfil F6-01 por grupo (CAN ID, LEN y caso MUX), y lo reutiliza para podar lecturas constantes y puntuar el alineamiento con limites/clases.
- La heuristica de signo y endian solo ordena candidatos; no confirma una interpretacion ni elimina la alternativa.
- Categorias contador y CRC siguen disponibles, pero se ocultan inicialmente con un control para mostrarlas.
- Los perfiles respetan longitudes CAN por grupo y las posiciones de bit de cada endianness.

## Trabajo
1. Anadir regresiones de poda segura, puntuacion por actividad/limites, sugerencia de signo y clasificacion/ocultamiento de CRC.
2. Reutilizar `BitActivityAccumulator` por grupo de busqueda para ajustar el ranking sin guardar frames adicionales.
3. Exponer una opcion para mostrar candidatos contador/CRC, oculta por defecto y persistida como preferencia.
4. Actualizar el changelog, el plan, la arquitectura y el mapa de pruebas.

## Pruebas
- Regresion primero (rojo -> verde): la poda solo descarta campos constantes cuando no se incluyen constantes; limites/clases cambian el orden sin descartar alternativas fisicas; signo/endian mantiene ambas interpretaciones.
- Suite completa verde.
- `/verify-ui`: abrir Candidate en Dark y Light, comprobar filtros predeterminados y habilitar la vista de contadores/CRC.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] Fila de `docs/plan.md`
- [x] Suite completa (1209 tests), code-reviewer y qt-mvvm-reviewer
- [x] Capturas Dark/Light revisadas; toggle contador/CRC verificado
