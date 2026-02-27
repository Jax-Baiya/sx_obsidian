# Profile Workflows

The profile system is designed for power users managing multiple media libraries or distinct data pipelines.

## Typical Workflows

### Scenario A: Individual Vaults

You have a Personal vault on one drive and a Work vault on another.

```env
VAULT_personal=/mnt/f/PersonalVault
VAULT_work=/mnt/g/WorkVault
```

Run personal sync: `./run.sh --profile personal`
Run work sync: `./run.sh --profile work`

### Scenario B: Testing New Schemas

Use a `dev` profile to generate files into a temporary folder before rolling out to your main vault.

```env
# .env
VAULT_dev=/mnt/t/AlexNova
DB_DIR_dev=_db/test_media
```

Run: `./run.sh --profile dev`

## Safety Rules

- **Cleanup is Profile-Aware**: Running `--cleanup soft --profile work` will **only** delete markdown files inside the vault defined for the `work` profile.
- **Independence**: Profiles do not share `csv_row_hash` state unless they point to the exact same files.

## Incident Recovery (single affected profile)

When one profile is contaminated or out-of-sync, use the profile-targeted recovery flow (no cross-profile reset):

- Preview target first: `make recover-profile-dry N=2`
- Execute recovery: `make recover-profile N=2`

Full guide: [`PROFILE_RECOVERY.md`](PROFILE_RECOVERY.md)
