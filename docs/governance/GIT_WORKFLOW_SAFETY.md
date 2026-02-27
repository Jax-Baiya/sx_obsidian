# Git Workflow Safety

Purpose: prevent accidental loss and reduce risky "mega commits" during active development.

## Baseline policy

- Commit at milestone boundaries, not only at end-of-day.
- Keep each commit reviewable in under ~15 minutes.
- Prefer explicit scopes (`api`, `plugin`, `tui`, `docs`, `ci`, `web`).

## Safe commit checklist

Before each milestone commit:

1. Confirm staged files are intentional: `git status --short`
2. Verify no logs/exports/screenshots are staged
3. Run target validations (build/tests) for changed subsystem
4. Write a commit message with:
   - What changed
   - Why this milestone exists
   - How it was verified

## Recovery protocol

When recovering from accidental edits:

1. Snapshot current state (`git status`, optional branch backup)
2. Restore compile/runtime blockers first
3. Run focused tests for the affected surface
4. Commit recovery in isolated milestone commits
5. Follow with a governance commit that improves safety rails

## Suggested commit rhythm

- Foundation/safety
- Backend/core behavior
- Plugin/UI behavior
- Tests/CI verification
- Docs/runbooks

This sequence creates a readable timeline and makes rollback lower risk.
