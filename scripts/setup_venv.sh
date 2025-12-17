#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

py="python3"
if command -v python >/dev/null 2>&1; then
  py="python"
fi

"$py" -m venv .venv

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt

echo "ok: installed dev tools into $repo_root/.venv" >&2
