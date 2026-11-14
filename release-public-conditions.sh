#!/usr/bin/env bash
# Use the staged Weather Lab release, with all-product checks and rollback.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec bash release-plots.sh
