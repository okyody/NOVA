# Adapter SDK

## Goal
Build a new upstream platform adapter without changing downstream runtime code.

## Contract
- Extend `packages.platform.adapters.BaseAdapter`
- Implement:
  - `_connect()`
  - `_disconnect()`
  - `_parse_raw()`
- Normalize upstream payloads into `NovaEvent`

## Required outputs
- `platform`
- `event_type`
- `viewer_id`
- `username`

## Integration steps
1. Add a `Platform` enum value.
2. Implement adapter subclass.
3. Wire it into `create_adapter()`.
4. Add catalog/template metadata.
5. Validate with Platforms workbench.
