# Contributing

This repo is organized to support a professional workflow (reproducible setup, automation scripts, and clean history).

## Commit message convention

Use short, imperative messages. Prefer Conventional Commits:

- `feat: add SQLite API search endpoint`
- `fix: prevent vault logs from being indexed`
- `docs: add performance playbook`
- `chore: update dev tooling`

## Commit hygiene

- Keep commits small and focused.
- Avoid mixing formatting-only changes with logic changes.
- Run tests before committing:
  - `make -f scripts/Makefile test`
- Run hooks (if installed):
  - `./.venv/bin/pre-commit run --all-files`

## Milestone commit protocol (required for large changes)

For incidents, migrations, or refactors touching many files, use this sequence:

1. **Foundation**: config and safety rails first.
2. **Core behavior**: backend/API or business logic.
3. **UX/runtime**: plugin/UI changes.
4. **Verification**: tests + CI updates.
5. **Docs/migration**: runbooks and operator guidance.

Each milestone commit should include:

- A clear scope in the subject (`feat(api): ...`, `fix(plugin): ...`, etc.).
- A short body listing why the milestone exists.
- Verification notes (which tests/builds were run).

## Never-commit list (local/transient)

- Runtime logs (`_logs/`, `_sxdb*.log`, `.sxctl/`)
- Local screenshot dumps under `assets/`
- Generated export blobs under `exports/`

If you need any of these for investigation, attach them to a ticket instead of committing.
