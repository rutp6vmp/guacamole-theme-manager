#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
python3 scripts/check_acceptance.py
python3 scripts/build.py
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/model.test.cjs
node --check themes/common/dashboard.js
node --check themes/common/settings.js
