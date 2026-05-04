# Frontend Engine Performance Migration Todo

## Scope

- Move only deterministic, non-secret, non-authoritative checks into the frontend game engine.
- Keep LLM generation, quest progress guards, Patch DSL execution, save authority, dice rolls with consequences, HP mutation, teleport, and game-over decisions on the server.
- Prefer fewer round trips during movement without changing player-visible rules.

## Tasks

### 1. Deterministic Trap Detection

- [x] Add frontend helpers for trap data normalization and passive perception calculation.
- [x] Replace `/api/check-trap` call during movement with local passive detection.
- [x] Keep `/api/trap/trigger` as the authoritative endpoint for save rolls, damage, teleport, and death.
- [x] Preserve existing trap choice dialog flow for detected traps.

### 2. Tile Event Authority Hardening

- [x] Make `/api/llm-event` resolve `tile_event` from server `current_map` by position after merging frontend computational state.
- [x] Treat frontend tile payload as a fallback only when the server tile cannot be found.
- [x] Return whether a pending choice context exists so the frontend can avoid extra polling.

### 3. State Merge Safety

- [x] Reuse the server local-authority merge helper before event handling.
- [x] Keep server/hybrid authority modes from accepting frontend combat/map overrides.
- [x] Repair `character_id` tile index after any local-authority merge.

### 4. Verification

- [x] Add regression coverage for stale client tile snapshots during `/api/llm-event`.
- [x] Run Python syntax checks.
- [x] Run `test_llm_map_full_control.py`.
- [x] Run JavaScript syntax checks for touched frontend files.

## Non-Goals

- Do not move LLM prompts or API keys into frontend code.
- Do not move quest completion policy, progress compensation, or rollback logic into frontend code.
- Do not replace service-side trap trigger resolution with client-side HP mutation.
- Do not change map full rebuild behavior.
