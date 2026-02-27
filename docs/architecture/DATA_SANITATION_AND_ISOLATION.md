# Data sanitation & isolation policy (schema + vault)

This document defines strict controls to prevent cross-contamination between source profiles (e.g. `assets_1`, `assets_2`) across DB schemas and vault media roots.

## High-risk contamination vectors

1. **Implicit default source fallback**
   - Requests without explicit `source_id` can silently hit the default profile.

2. **Profile/source mismatch at request layer**
   - Header profile index and source suffix (e.g. `assets_2`) can disagree.

3. **Wrong CSV import source binding**
   - Importing `assets_1` CSV into `assets_2` schema (or vice versa) duplicates IDs.

4. **Cached notes with stale local links**
   - Existing cached markdown can preserve old `sxopen/sxreveal` roots.

5. **Source-agnostic vault/media root resolution**
   - Using only `VAULT_default` generates wrong local paths for non-default profiles.

## Enforced controls (implemented)

1. **API requires explicit source**
   - `SX_API_REQUIRE_EXPLICIT_SOURCE=true`
   - Rejects requests missing query/header source id.

2. **API enforces profile/source suffix match**
   - `SX_API_ENFORCE_PROFILE_SOURCE_MATCH=true`
   - Rejects requests where `X-SX-Profile-Index` conflicts with `source_id` suffix.

3. **Schema index guard**
   - `SX_SCHEMA_INDEX_GUARD=true`
   - Prevents profile/schema mismatch in repository routing.

4. **Source-aware vault/media resolution**
   - Note/link/media paths are resolved by effective source profile (`assets_N`) instead of default vault only.

5. **Library sync regeneration**
   - Sync uses `force=true` to regenerate notes and avoid stale path leakage.

## Operational sanitation runbook

1. **Audit overlap**
   - Use `/admin/audit/source-overlap?source_a=assets_1&source_b=assets_2`
   - Confirm `overlap_ids`, `only_a_ids`, `only_b_ids`.

2. **Reset contaminated target schema**
   - Truncate target profile tables in one transaction:
     - `videos`, `user_meta`, `video_notes`
     - raw tables: `csv_*_raw`

3. **Reimport target profile only**
   - Use explicit source and explicit CSV paths for that profile.

4. **Re-audit overlap**
   - Ensure overlap reflects expected business reality, not full duplication.

5. **Vault validation**
   - In Library debug line, verify:
     - `effective_source`
     - `schema`
     - `vault_root`

## Recommended invariants for CI/ops

- For each profile `N`, any import job must include both:
  - `source_id=assets_N`
  - CSV paths from `assets_N` directory only

- API requests must include:
  - `X-SX-Source-ID`
  - `X-SX-Profile-Index`

- Reject startup/requests when profile mapping is ambiguous.
