# U-04 — CAN Send ergonomics

- **Estado:** Hecho
- **Fase:** U
- **Rama:** `feat/u-04-can-send-ergonomics` (sale de `dev`)
- **Implementa:** Codex
- **Depende de:** nada
- **Base commit:** 2339d4c

## Problema
La ventana CAN Send necesita acciones de toolbar legibles con texto e ícono y una guía visible
para agregar el primer frame cuando la lista está vacía.

## Propiedad
- **Puede editar:** `views/can_send_window.py`, `config/ui_text.py`, `docs/plan.md`, `CHANGELOG.md`, esta tarjeta.
- **No puede editar:** `viewmodels/`, `services/`, Mux Detection, HMI/OCR.

## Decisiones cerradas
- Las acciones de la toolbar muestran texto junto al ícono.
- La lista vacía muestra un botón centrado “Add a frame with +” que abre el diálogo de alta existente.
- La tabla vuelve a mostrarse al crear el primer frame.

## Trabajo
1. Mostrar texto junto a los íconos de las acciones CAN Send.
2. Agregar el estado vacío con acceso directo para crear el primer frame.

## Pruebas
- Suite completa en verde.
- `/verify-ui`: comprobar texto e íconos de toolbar; estado vacío y transición a la tabla tras agregar un frame.

## Cierre
- [x] CHANGELOG `## Unreleased`
- [x] fila de `docs/plan.md` cerrada
- [x] suite completa: 1021 tests
- [x] UI verificada: toolbar, botón vacío y transición a tabla
