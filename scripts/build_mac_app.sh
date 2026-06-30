#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_APP="$ROOT_DIR/node_modules/electron/dist/Electron.app"
APP_DIR="$ROOT_DIR/dist/FluentAI.app"
APP_LOADER_DIR="$APP_DIR/Contents/Resources/app"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "build_mac_app.sh only supports macOS because it packages Electron.app with /usr/bin/ditto." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to build FluentAI.app" >&2
  exit 1
fi

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "Electron is not installed. Run: npm install" >&2
  exit 1
fi

rm -rf "$APP_DIR"
/usr/bin/ditto "$SOURCE_APP" "$APP_DIR"
rm -rf "$APP_LOADER_DIR"
mkdir -p "$APP_LOADER_DIR"

cat > "$APP_LOADER_DIR/package.json" <<'JSON'
{
  "name": "fluentai-launcher",
  "version": "0.1.0",
  "main": "main.js"
}
JSON

python - "$ROOT_DIR" "$APP_LOADER_DIR/main.js" "$APP_DIR/Contents/Info.plist" <<'PY'
import json
import plistlib
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
main_js = Path(sys.argv[2])
plist_path = Path(sys.argv[3])

main_js.write_text(
    "process.env.FLUENTAI_PROJECT_ROOT = "
    + json.dumps(str(root))
    + ";\nrequire("
    + json.dumps(str(root / "desktop" / "electron" / "main.js"))
    + ");\n",
    encoding="utf-8",
)

with plist_path.open("rb") as file:
    plist = plistlib.load(file)

plist.update(
    {
        "CFBundleDisplayName": "FluentAI",
        "CFBundleIdentifier": "local.fluentai.desktop",
        "CFBundleName": "FluentAI",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
    }
)

with plist_path.open("wb") as file:
    plistlib.dump(plist, file)
PY

echo "Built $APP_DIR"
