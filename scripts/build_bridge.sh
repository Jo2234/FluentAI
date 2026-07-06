#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"
SPEC="$ROOT_DIR/packaging/fluentai_bridge.spec"
DIST_DIR="$ROOT_DIR/dist-py"
BRIDGE="$DIST_DIR/fluentai-bridge/fluentai-bridge"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing repo virtualenv Python at $PYTHON" >&2
  echo "Create .venv before packaging the bridge." >&2
  exit 1
fi

if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
  "$PYTHON" -m pip install pyinstaller
fi

"$PYTHON" -m PyInstaller "$SPEC" --noconfirm --clean --distpath "$DIST_DIR" --workpath "$ROOT_DIR/build"

if [[ ! -x "$BRIDGE" ]]; then
  echo "Expected bridge artifact was not created at $BRIDGE" >&2
  exit 1
fi

SMOKE_ROOT="$(mktemp -d)"
trap 'rm -rf "$SMOKE_ROOT"' EXIT
SMOKE_CWD="$SMOKE_ROOT/outside-repo"
STATE_DIR="$SMOKE_ROOT/state"
mkdir -p "$SMOKE_CWD" "$STATE_DIR"

PAYLOAD="{\"state_path\":\"$STATE_DIR/progress.json\"}"

run_status_smoke() {
  local label="$1"
  local output_file="$SMOKE_ROOT/$label.json"

  if [[ "$label" == "missing-key" ]]; then
    (
      cd "$SMOKE_CWD"
      printf '%s\n' "$PAYLOAD" | env -u PYTHONPATH -u PYTHONHOME OPENAI_API_KEY= "$BRIDGE" status >"$output_file"
    )
  elif [[ "$label" == "sdk-import" ]]; then
    (
      cd "$SMOKE_CWD"
      printf '%s\n' "$PAYLOAD" | env -u PYTHONPATH -u PYTHONHOME OPENAI_API_KEY=dummy "$BRIDGE" status >"$output_file"
    )
  else
    (
      cd "$SMOKE_CWD"
      printf '%s\n' "$PAYLOAD" | env -u PYTHONPATH -u PYTHONHOME -u OPENAI_API_KEY "$BRIDGE" status >"$output_file"
    )
  fi

  "$PYTHON" - "$output_file" "$label" <<'PY'
import json
import sys
from pathlib import Path

output_path = Path(sys.argv[1])
label = sys.argv[2]
data = json.loads(output_path.read_text(encoding="utf-8"))
profile = data.get("profile")
if data.get("ok") is not True:
    raise SystemExit(f"{label} smoke failed: ok was not true")
if not isinstance(profile, dict):
    raise SystemExit(f"{label} smoke failed: profile is missing")
status = profile.get("openai_status")
if not isinstance(status, str) or not status:
    raise SystemExit(f"{label} smoke failed: profile.openai_status is missing")
if label == "missing-key" and "OPENAI_API_KEY is not set" not in status:
    raise SystemExit(f"{label} smoke failed: missing-key status was not reported")
if label == "sdk-import" and "OpenAI enabled:" not in status:
    raise SystemExit(f"{label} smoke failed: OpenAI SDK did not initialize")
print(json.dumps({"label": label, "ok": data["ok"], "openai_status": status}, ensure_ascii=True))
PY
}

run_status_smoke "self-contained"
run_status_smoke "missing-key"
run_status_smoke "sdk-import"

du -sh "$DIST_DIR/fluentai-bridge"
