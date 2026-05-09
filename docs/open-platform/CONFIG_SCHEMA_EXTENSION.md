# Config Schema Extension

## Goal
Extend config safely without breaking EXE, compose, or Studio workbench.

## Rules
- Prefer additive fields
- Keep defaults stable
- Surface user-facing fields in Studio
- Keep secrets explicit
- Update config export and validation together

## Required touchpoints
- `packages.core.config`
- `apps.nova_server.main._settings_to_config_json`
- Studio config form
- docs / templates / acceptance checks
