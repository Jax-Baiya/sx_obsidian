.PHONY: bootstrap api-init api-import api-serve plugin-build plugin-install test recover-profile recover-profile-dry

bootstrap:
	./scripts/bootstrap.sh

api-init:
	bash -lc 'source ./scripts/profile_adapter.sh; sx_profile_apply; sx_profile_print_context "make api-init"; ./.venv/bin/python -m sx_db init'

api-import:
	bash -lc 'source ./scripts/profile_adapter.sh; sx_profile_apply; sx_profile_print_context "make api-import"; ./.venv/bin/python -m sx_db import-csv --source "$$SX_DEFAULT_SOURCE_ID"'

api-serve:
	bash -lc 'source ./scripts/profile_adapter.sh; sx_profile_apply; sx_profile_print_context "make api-serve"; ./.venv/bin/python -m sx_db serve'

plugin-build:
	bash -lc 'source ./scripts/profile_adapter.sh; sx_profile_apply; sx_profile_print_context "make plugin-build"; ./scripts/build_plugin.sh'

plugin-install:
	bash -lc 'source ./scripts/profile_adapter.sh; sx_profile_apply; sx_profile_print_context "make plugin-install"; ./scripts/install_plugin.sh'

test:
	./.venv/bin/python -m pytest -q

recover-profile:
	bash -lc 'if [ -z "$$N" ]; then echo "Usage: make recover-profile N=<profile_index> [ARGS=\"...\"]"; echo "Example: make recover-profile N=2 ARGS=\"--dry-run\""; exit 2; fi; ./.venv/bin/python scripts/recover_profile.py --profile-index "$$N" $$ARGS'

recover-profile-dry:
	bash -lc 'if [ -z "$$N" ]; then echo "Usage: make recover-profile-dry N=<profile_index>"; echo "Example: make recover-profile-dry N=2"; exit 2; fi; ./.venv/bin/python scripts/recover_profile.py --profile-index "$$N" --dry-run'
