# bash からこのファイルを source して、補助コマンドを使えるようにします。
#
# 使い方:
#   source scripts/commands.sh
#   prows bundle main.py
#   prows run main.py

__lib_repo_root() {
  local src="${BASH_SOURCE[0]}"
  cd "$(dirname "$src")/.." >/dev/null 2>&1 && pwd
}

__lib_python() {
  local repo_root
  repo_root="$(__lib_repo_root)" || return 1

  if [[ -x "$repo_root/.venv/bin/python" ]]; then
    echo "$repo_root/.venv/bin/python"
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    echo python
  else
    echo python3
  fi
}

__lib_copy_to_clipboard() {
  # 標準入力を読み取り、クリップボードにコピーします（成功時は 0 を返します）。
  if command -v wl-copy >/dev/null 2>&1; then
    wl-copy
    return $?
  fi
  if command -v xclip >/dev/null 2>&1; then
    xclip -selection clipboard
    return $?
  fi
  if command -v xsel >/dev/null 2>&1; then
    xsel --clipboard --input
    return $?
  fi
  if command -v pbcopy >/dev/null 2>&1; then
    pbcopy
    return $?
  fi
  return 127
}

__require_black_isort() {
  local py="$1"
  if ! "$py" -m black --version >/dev/null 2>&1; then
    echo "missing: black" >&2
    return 1
  fi
  if ! "$py" -m isort --version-number >/dev/null 2>&1; then
    echo "missing: isort" >&2
    return 1
  fi
  return 0
}

__prows_bundle() {
  local entry="${1:-main.py}"
  local repo_root
  repo_root="$(__lib_repo_root)" || return 1

  local entry_path="$entry"
  if [[ "$entry_path" != /* ]]; then
    entry_path="$repo_root/$entry_path"
  fi

  local out_dir="$repo_root/logs"
  mkdir -p "$out_dir"
  local ts
  ts="$(date +%Y%m%d%H%M%S)"
  local out="$out_dir/bundled_${ts}.py"
  local py
  py="$(__lib_python)" || return 1

  PYTHONPATH="$repo_root" "$py" -m lib.bundle "$entry_path" -o "$out" || return $?

  if ! __require_black_isort "$py"; then
    echo "" >&2
    echo "To enable formatting, run:" >&2
    echo "  ./scripts/setup_venv.sh" >&2
    echo "then re-run:" >&2
    echo "  prows bundle $entry" >&2
    return 1
  fi

  "$py" -m isort --profile black "$out" || return $?
  "$py" -m black "$out" || return $?

  if __lib_copy_to_clipboard < "$out"; then
    echo "generated: $out (formatted, copied to clipboard)" >&2
    return 0
  fi

  echo "generated: $out (formatted)" >&2
  echo "clipboard copy skipped (install wl-copy/xclip/xsel/pbcopy to enable)" >&2
  return 0
}

__prows_run() {
  local entry="${1:-main.py}"
  local repo_root
  repo_root="$(__lib_repo_root)" || return 1

  local entry_path="$entry"
  if [[ "$entry_path" != /* ]]; then
    entry_path="$repo_root/$entry_path"
  fi

  local in_path="$repo_root/io/input.txt"
  local out_path="$repo_root/io/output.txt"

  mkdir -p "$repo_root/io"
  if [[ ! -f "$in_path" ]]; then
    echo "missing input: $in_path" >&2
    return 1
  fi

  local py
  py="$(__lib_python)" || return 1

  ( set -o pipefail
    PYTHONPATH="$repo_root" "$py" "$entry_path" < "$in_path" | tee "$out_path"
  )
}

prows() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    bundle)
      __prows_bundle "$@"
      ;;
    run)
      __prows_run "$@"
      ;;
    exec)
      __prows_run "$@"
      ;;
    *)
      echo "usage: prows {bundle|run} [main.py]" >&2
      return 2
      ;;
  esac
}
