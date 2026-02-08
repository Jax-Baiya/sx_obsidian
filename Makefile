.PHONY: bootstrap api-init api-import api-serve plugin-build plugin-install test

bootstrap:
	./scripts/bootstrap.sh

api-init:
	./.venv/bin/python -m sx_db init

api-import:
	./.venv/bin/python -m sx_db import-csv

api-serve:
	./.venv/bin/python -m sx_db serve

plugin-build:
	./scripts/build_plugin.sh

plugin-install:
	./scripts/install_plugin.sh

test:
	./.venv/bin/python -m pytest -q
