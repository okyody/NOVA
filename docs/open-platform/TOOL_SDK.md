# Tool SDK

## Goal
Expose tools that can be toggled through NOVA control and AI routing configuration.

## Expectations
- Tools should be side-effect aware.
- Tools should return structured JSON-like payloads.
- Tools should be safe to disable without breaking core runtime.

## Recommended shape
- `name`
- `description`
- `args_schema`
- `run()`

## Verification
- Register tool
- Confirm it appears in tool registry
- Toggle tool enablement in config
- Validate via AI routing preview and eval flow
