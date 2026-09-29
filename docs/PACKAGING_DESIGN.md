# macOS packaging and key management

## Current package

Electron Builder packages `desktop/electron/**` and the PyInstaller bridge from `dist-py/fluentai-bridge/` using `electron-builder.yml`. Packaged Electron runs `Contents/Resources/bridge/fluentai-bridge/fluentai-bridge`; development runs `python -m fluent_ai.desktop_bridge` from the checkout.

This keeps one Python learning engine across CLI, browser, and desktop while removing a checkout/Python-install dependency from the packaged runtime. A bundled Python distribution remains an alternative if PyInstaller becomes unsuitable; rewriting the bridge in Node would duplicate the learning engine and is not the current design. The Tk launcher is retired.

The PyInstaller spec collects the OpenAI dependency graph, curriculum assets, and certificates. Direct provider HTTPS calls use certifi for certificate verification. Build checks must exercise the binary outside the checkout to catch accidental source/environment dependencies.

## Build and local verification

From the repository root on macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
npm ci
npm run check
npm run build:app
```

`build:app` invokes `package:mac`, which runs `scripts/build_bridge.sh` followed by Electron Builder. The bridge script requires `.venv/bin/python`, installs PyInstaller if missing, and checks standalone status, missing-key behavior, and SDK import using temporary state outside the checkout. No paid API call is needed for these build smokes.

On Apple Silicon the app normally appears at `dist/mac-arm64/FluentAI.app`; other architectures can use `dist/mac/FluentAI.app`. Use the actual output directory reported by Electron Builder. `npm run sign:mac` applies ad-hoc signing to these paths. To check the result:

```bash
codesign --verify --deep --strict dist/mac-arm64/FluentAI.app
open dist/mac-arm64/FluentAI.app
```

Local/ad-hoc signing is not Developer ID signing or notarization. Hardened runtime and Gatekeeper assessment are currently disabled in the builder configuration. Public distribution still needs a deliberate signing/notarization pipeline and clean-account acceptance.

## State location and migration

Development defaults to `data/progress.json`. Packaged Electron uses `app.getPath("userData")/progress.json` (normally `~/Library/Application Support/FluentAI/`). `FLUENTAI_STATE_PATH` overrides the file and `FLUENTAI_USER_DATA_PATH` can isolate a test profile.

First packaged launch copies a legacy profile only when the destination is missing and an explicit `FLUENTAI_LEGACY_STATE_PATH`, or `FLUENTAI_PROJECT_ROOT` containing `data/progress.json`, identifies the source. It does not search arbitrary directories. Corrupt-state backup/recovery is handled by the Python state layer.

## API keys

The Electron main process resolves keys in this order: `OPENAI_API_KEY`, session key, encrypted stored key, then development-only `.env`. Packaged operation must not depend on a repository `.env`.

Keys can be validated through the bridge and persisted using Electron `safeStorage` in `settings.json` under user data. If encrypted storage is unavailable, the app keeps the key for the session. Keys are injected into the bridge environment; packaged subprocesses receive a restricted environment plus `FLUENTAI_*` overrides. Main/bridge errors redact secrets rather than returning raw credentials to the renderer or learner memory.

## Manual acceptance still required

Use a clean macOS account with the repository inaccessible and an isolated profile. Verify double-click launch, first-run key entry, lesson submission and restart/resume, voice-only conversation, camera-denial recovery, navigation/language-change/window-close finalization, and export/delete controls. Mocked tests, bridge smokes, and a successful bundle build do not establish those hardware/window behaviors. Prior acceptance evidence and its limits are recorded in [notes](notes.md).
