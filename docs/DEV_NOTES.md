# DEVELOPER NOTES

## Architecture
The system consists of a Python package (`sx/`) with an entrypoint at `sx/__main__.py` (run via `python -m sx` or `./run.sh`).

At a high level it performs an ETL (Extract, Transform, Load) pipeline:
1.  **Extract**: Reads CSVs and scans the file system.
2.  **Transform**: Joins datasets using Pandas-like logic (dictionary lookups) and calculates a row hash for change detection.
3.  **Load**: Uses recursive directory creation and atomic-like writes to generate Markdown files.

## Extending the Schema
To add new metadata fields:
1.  Add the CSV column name mapping to `schema.yaml`.
2.  Update the frontmatter rendering logic in `sx/render/render.py` to include the new field.

## Idempotency Logic
We use a MurmurHash-like approach (MD5 of stable key-value pairs) stored in the `source.csv_row_hash` field. If the newly calculated hash matches the one in the existing file, the file is skipped. This drastically improves performance for large vaults (thousands of files).

## Media Discovery
The recursive scan is depth-first. It extracts all numbers from a filename to find the ID. While simple, it is robust against suffixes and varying folder structures.

## Windows/WSL Metadata Cleanup
The `deploy.sh` script automatically removes Windows `:Zone.Identifier` files which can sometimes cause permission or path processing issues in WSL. This is a standard cleanup step for cross-filesystem environments.
