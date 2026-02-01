# Developer Notes

## Project Structure
- `views/`: Qt widgets, dialogs, windows, and UI models tied directly to Qt widgets.
- `viewmodels/`: viewmodels and UI state/commands. Pure orchestration; no Qt widgets.
- `services/`: I/O and integrations (DBC manager, log loading, remote connections, decoders).
- `models/`: domain data structures (no Qt dependencies).
- `utils/`: stateless helpers and formatting.
- `config/`: application configuration and defaults.

## Naming Conventions
- Files and directories use `snake_case`.
- Classes use `PascalCase`.
- Functions, methods, and variables use `snake_case`.

## Configuration
- Default UI text and options live in `config/ui_text.py` and `config/defaults.py`.
- Environment configuration is centralized in `config/env.py`.
- To override UI strings/options at runtime, set `CANANALYZE_CONFIG` to a JSON file with
  `strings` and/or `options` sections.
