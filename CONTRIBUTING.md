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
  - `make test`
- Run hooks (if installed):
  - `./.venv/bin/pre-commit run --all-files`
