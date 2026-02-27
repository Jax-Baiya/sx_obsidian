# Change Risk and Rollback Strategy

Owner: @devops

## Risk list

1. **Terminal keybinding variance**: Some terminals may not emit `Delete` consistently.
   - Mitigation: fallback keys (`Backspace`, `d`) and checkbox fallback path.
2. **Interactive UI regressions** in TUI prompts.
   - Mitigation: focused regression tests and conservative fallback UX.
3. **Menu extraction regressions** in database management screen.
   - Mitigation: unchanged action IDs; only moved configuration data.
4. **Media resolution path mismatches across Linux/WSL/Windows**.
   - Mitigation: deterministic fallback candidate order, path-style normalization, structured diagnostics (`sx_db.media`).
5. **Profiles tab source scoping confusion**.
   - Mitigation: explicit active-source/filter status line + `Show all profiles` troubleshooting override.

## Rollback strategy

### Fast rollback

- Revert the current patch set for:
   - `sx_db/api.py`
   - `obsidian-plugin/src/settings.ts`
   - `tests/test_api_media_roots.py`
   - `tests/test_sources_api.py`
   - `docs/runbooks/TROUBLESHOOTING.md`

Operational emergency fallback (no code rollback):

- In plugin settings, enable **Show all profiles** in Profiles tab if source mapping appears missing.
- Keep API running; use `sx_db.media` logs to confirm candidate path checks before deciding on full rollback.

### Verification after rollback

1. Launch TUI and validate Build/Install vault selection.
2. Validate database management action menus open and execute.
3. Run focused TUI test subset.
4. Validate media endpoints for a known existing item:
   - `/items/{id}/links`
   - `/media/cover/{id}`
   - `/media/video/{id}`
5. Validate Profiles tab behavior:
   - default active-source scope
   - show-all override
   - non-breaking fallback when mapping is missing

## Forward-fix strategy

If fallback path is frequently used in a given terminal, keep fallback active and document terminal-specific key mapping in `docs/TROUBLESHOOTING.md`.
