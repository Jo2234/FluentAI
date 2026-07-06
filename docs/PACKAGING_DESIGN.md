# FluentAI Mac Packaging Design

## Scope

Target: a double-clickable consumer `FluentAI.app` that works without Terminal, a repo checkout, `node_modules`, `.venv`, or system Python. It remains API-key-first, local-first, and keeps the Python agent core.

Audited files: `scripts/build_mac_app.sh`, `desktop/electron/main.js`, `preload.js`, `renderer.html`, `fluent_ai/desktop_bridge.py`, `openai_provider.py`, `state.py`, `config.py`, `package.json`, and `docs/FLUENTAI_LIMITLESS_IDEAL.md`.

## Current Packaging Audit

### Actual output

`scripts/build_mac_app.sh` creates `dist/FluentAI.app` by copying the dev Electron app and installing a repo-pinned launcher:

- Computes `ROOT_DIR` from the repo (`scripts/build_mac_app.sh:4`).
- Copies `node_modules/electron/dist/Electron.app` to `dist/FluentAI.app` (`:5-6`, `:25`).
- Replaces `Contents/Resources/app` with a tiny `package.json` and generated `main.js` (`:26-35`, `:47-54`).
- The generated launcher sets `FLUENTAI_PROJECT_ROOT` to the absolute repo path and `require()`s the repo's `desktop/electron/main.js` (`:47-54`).
- Edits bundle display name/id/version in `Info.plist` (`:56-70`).

### Build dependencies

- macOS and `/usr/bin/ditto` (`scripts/build_mac_app.sh:9-10`, `:25`).
- `node_modules/electron/dist/Electron.app`; user must run `npm install` first (`:19-22`).
- `python3` is checked (`:14-17`), but the script actually invokes `python` for generation (`:37`). That mismatch can fail on modern macOS.
- Writable `dist/`.

### Runtime dependencies

The produced `.app` is not standalone:

- It requires the original repo at the exact build-time path because the app launcher imports repo `main.js` (`scripts/build_mac_app.sh:47-54`).
- `main.js` loads repo `preload.js` and `renderer.html` using `__dirname` (`desktop/electron/main.js:82-83`, `:106`).
- `runBridge()` spawns `python -m fluent_ai.desktop_bridge` with `cwd: projectRoot` and `PYTHONPATH: projectRoot` (`desktop/electron/main.js:37-45`).
- Python resolution is `PYTHON_EXECUTABLE`, then repo `.venv/bin/python`, then system `python3` (`desktop/electron/main.js:10-23`).
- The chosen Python must have `openai>=1.0.0` importable (`pyproject.toml:9-10`; `fluent_ai/openai_provider.py:294-301`).
- `OPENAI_API_KEY` is read from env or repo-root `.env` because the bridge cwd is `projectRoot` and `OpenAIProvider.__init__()` calls `load_env_file()` (`fluent_ai/openai_provider.py:24-31`; `fluent_ai/config.py:7-20`).
- State defaults to repo `data/progress.json` (`fluent_ai/desktop_bridge.py:33`, `:384-385`).

### Consumer readiness

Current `dist/FluentAI.app` is a local demo launcher, not a consumer app. Moving the repo breaks it; clean Macs lack the repo files, Python environment, dependencies, key path, and repo `data/` state. It also lacks camera/mic usage strings, signing, notarization, and app-support persistence.

## Recommended Packaging Architecture

### Option A: `electron-builder` + PyInstaller bridge binary

Package Electron with `electron-builder`; package `fluent_ai.desktop_bridge` as a standalone PyInstaller executable. In packaged mode, `main.js` launches `process.resourcesPath/bridge/fluentai-bridge`; in dev mode, keep today's `python -m fluent_ai.desktop_bridge`.

Layout:

```text
FluentAI.app/Contents/Resources/
  app.asar
  bridge/fluentai-bridge
```

Pros:

- Keeps Python lesson, state, provider, and conversation logic intact.
- Removes system Python, `.venv`, repo, and `node_modules` runtime dependencies.
- Preserves the JSON stdin/stdout bridge and visible agent logs.
- Lets existing Python tests keep covering the product core.
- Uses mainstream Electron signing/resource packaging.

Cons:

- PyInstaller may need hidden imports/data for `openai`, `httpx`, `pydantic`, certs, and metadata.
- One-file mode can add cold-start latency; one-dir mode may be faster but has more files to sign.
- Universal macOS builds need per-arch bridge builds or a merged universal binary.

Test impact:

- Existing `python -m unittest discover -s tests -q` remains the main agent/state test suite.
- Add a bridge-binary smoke test: run `dist-py/fluentai-bridge status` with temp `state_path`.
- Add main-process tests/smoke checks for packaged bridge and state path resolution.

Recommendation: choose Option A.

### Option B: `electron-builder` + bundled Python runtime

Ship `python-build-standalone`, installed `site-packages`, and run bundled `python -m fluent_ai.desktop_bridge`.

Pros: closest to dev mode, easier Python debugging, fewer PyInstaller import surprises.

Cons: larger app, many files/dylibs to sign, more path/cert setup, more risk of writing into read-only app resources.

Test impact: existing Python tests remain, plus integration tests for bundled runtime importability and cert behavior.

Use only if PyInstaller cannot package the dependency graph reliably.

### Option C: rewrite bridge in Node

Port bridge, state migration, lesson/quiz logic, conversation scoring, and provider code to Node.

Pros: one runtime, no child Python process, potentially smaller.

Cons: rewrites working core logic, duplicates/invalidates tests, high regression risk, delays packaging. Do not choose for the next standalone app.

## API Key UX Design

### First-run screen

Before auto-starting Lesson Mode, Electron checks key availability. If missing, show a setup panel with:

- Password input for OpenAI API key.
- `Validate Key` action.
- `Use Dev .env` only when `!app.isPackaged`.
- `Replace key` and `Remove key` in settings after setup.

States:

- Missing: "Add your OpenAI API key to start FluentAI."
- Validating: disable actions, run validation ping.
- Invalid: "That key did not validate. Check it and try again."
- Valid: store securely, continue to `status`, then lesson/conversation.

### Storage and precedence

Store the key with Electron `safeStorage`: encrypt the plaintext key, persist only a base64 encrypted blob in:

```text
~/Library/Application Support/FluentAI/settings.json
```

Shape:

```json
{
  "openai_api_key_encrypted": "base64-safeStorage-ciphertext",
  "created_at": "iso-time",
  "last_validated_at": "iso-time"
}
```

If `safeStorage.isEncryptionAvailable()` is false, allow session-only use and do not persist. Do not put plaintext keys in logs, renderer storage, `progress.json`, crash reports, or normal bridge payloads.

Key precedence:

1. `OPENAI_API_KEY` already in Electron process env, for CI/demo explicit launches.
2. Packaged secure storage.
3. Dev-only repo `.env` fallback when `!app.isPackaged` or `FLUENTAI_DEV_ENV_FALLBACK=1`.

Consumer packaged builds must not depend on repo `.env`.

### Validation and bridge injection

Add IPC handlers:

- `key:status`
- `key:validate`
- `key:save`
- `key:delete`

`key:validate` spawns the bridge with `OPENAI_API_KEY=<candidate>` and a `validate_key` command that calls `OpenAIProvider.health_check()` (`fluent_ai/openai_provider.py:186-190`) or a cheaper ping. Store only after success.

For normal commands, main injects the resolved key into the child process env:

```js
env: {
  ...allowlistedEnv,
  OPENAI_API_KEY: resolvedKey,
  FLUENTAI_STATE_PATH: statePath
}
```

Rules:

- Do not send the key through renderer-visible payloads.
- Redact `sk-...` patterns from bridge `raw` output before returning to renderer.
- Avoid forwarding all `process.env` in packaged mode.

## State Location

### Current behavior

`desktop_bridge.DEFAULT_PROGRESS_PATH` is `data/progress.json` (`fluent_ai/desktop_bridge.py:33`). `_path()` uses payload `state_path` or that default (`:384-385`). `load_state()` creates missing files and migrates valid JSON (`fluent_ai/state.py:77-140`); `save_state()` writes JSON (`:158-163`).

### Packaged behavior

Consumer state path:

```text
~/Library/Application Support/FluentAI/progress.json
```

Resolution:

- If `FLUENTAI_STATE_PATH` is set, use it for tests/demos.
- Else if `app.isPackaged`, use `path.join(app.getPath("userData"), "progress.json")`.
- Else use repo `data/progress.json`.

Main should inject `state_path` into every bridge payload or set `FLUENTAI_STATE_PATH`; renderer should not know filesystem paths.

### Migration

On first packaged launch:

1. If app-support `progress.json` exists, use it.
2. Else, if `FLUENTAI_PROJECT_ROOT/data/progress.json` or explicit `FLUENTAI_LEGACY_STATE_PATH` exists, copy it.
3. Log only `[Memory Agent] Migrated learner profile to Application Support.`
4. If no legacy state exists, let `load_state()` create default state.

Do not scan the filesystem. If JSON is invalid, move it to `progress.corrupt.<timestamp>.json`, start a fresh profile, and tell the user a backup was saved.

## Reliability Matrix

| Failure | Current behavior | Designed behavior |
| --- | --- | --- |
| Missing key | `OpenAIProvider.status()` reports unset key (`fluent_ai/openai_provider.py:38-43`). Lesson/conversation return `_openai_required()` (`fluent_ai/desktop_bridge.py:105-111`, `:169-176`, `:388-394`). Renderer shows generic lesson/text errors or realtime secret failure (`desktop/electron/renderer.html:2406-2418`, `:2675-2678`, `:1992-2001`). | First-run key gate. Message: "Add your OpenAI API key to start FluentAI." Recovery: validate and store key; dev may use `.env`. |
| Expired realtime session | Client secret is requested for 600s (`fluent_ai/openai_provider.py:66-68`). Renderer does not track expiry (`desktop/electron/renderer.html:1992-2058`). | Track `expires_at`; refresh at T-60s. Message: "Voice session is refreshing." Recovery: reconnect or continue in text with transcript preserved. |
| Microphone blocked | Main checks/asks macOS media access and returns blocked error (`desktop/electron/main.js:158-186`). Renderer maps permission errors (`desktop/electron/renderer.html:1964-2075`). | Keep detection; add "Open System Settings"; disable voice until fixed; offer text mode. |
| Camera blocked | Main returns combined mic/camera error (`desktop/electron/main.js:158-186`). Camera toggle shows raw error message (`desktop/electron/renderer.html:2316-2340`). | Split camera from mic. Message: "Camera is blocked. Continue voice-only or allow camera." Recovery: switch video off, keep call active. |
| Weak network | Provider timeouts: realtime 20s, vision 12s, SDK 30s (`fluent_ai/openai_provider.py:92-99`, `:158-165`, `:303-327`). Realtime `fetch()` has no explicit timeout (`desktop/electron/renderer.html:2032-2044`). | Add `AbortController`, retry once, and offline/weak-network banner. Preserve lesson draft/call transcript. |
| Model timeout | `_text_response()` catches SDK errors, stores safe error, returns empty (`fluent_ai/openai_provider.py:321-327`, `:389-393`). Bridge often reports generation failure (`fluent_ai/desktop_bridge.py:105-111`, `:173-176`). | Distinguish timeout from missing key. Message: "The model timed out. Your progress is safe." Recovery: retry same request, optional lower-latency model. |
| Malformed model output | Lesson JSON parse failure returns base lesson, then bridge rejects missing `source=openai` (`fluent_ai/openai_provider.py:224-238`; `fluent_ai/desktop_bridge.py:108-111`). Vision has a generic fallback (`fluent_ai/openai_provider.py:167-184`). | Schema-validate, retry once with repair prompt, then show malformed-response message and leave state unchanged. |
| Empty tutor response | Empty conversation text returns `None` (`fluent_ai/openai_provider.py:288-292`). Start errors (`fluent_ai/desktop_bridge.py:173-176`). Reply currently can save progress and return `tutor_message: null` because it does not guard after `_tutor_reply()` (`:238-253`). | Never render/persist empty tutor output. Retry once; if still empty, use a short recovery prompt and log the recovery. |
| Invalid progress file | `json.load()` has no corruption handling (`fluent_ai/state.py:77-86`). Bridge catches and returns `JSONDecodeError` (`fluent_ai/desktop_bridge.py:421-426`). | Backup corrupt file, create fresh state, show "Your progress file was damaged; a backup was saved." |
| Interrupted lesson | Generated lesson/quiz are in renderer memory only (`desktop/electron/renderer.html:2406-2424`). State saves only on quiz submit (`fluent_ai/desktop_bridge.py:130-161`). | Save `sessions/current_lesson.json` after generation and during answers. Resume/discard on next launch. |
| Interrupted call | `beforeunload` ends the call (`desktop/electron/renderer.html:2811-2813`). `endRealtimeCall()` clears in-memory call state (`:2230-2255`). Voice transcripts are not saved to progress; text saves after reply (`fluent_ai/desktop_bridge.py:242-257`). | Checkpoint transcript/metadata every turn. On drop, offer reconnect or text. Summarize checkpoint through bridge to update memory. |
| Restart mid-session | Renderer state is in memory (`desktop/electron/renderer.html:1693-1714`); persisted state changes only after quiz submit/text reply. | Read session checkpoint files on startup and show Resume/Discard before auto-starting a new lesson. Avoid duplicate progress updates. |

## Build Pipeline

### Commands and scripts

Install build tools:

```bash
npm install --save-dev electron-builder
python -m pip install pyinstaller
```

New npm scripts:

```json
{
  "package:bridge": "python -m PyInstaller packaging/fluentai_bridge.spec --noconfirm --clean",
  "package:mac": "npm run package:bridge && electron-builder --mac dir",
  "dist:mac": "npm run package:bridge && electron-builder --mac dmg"
}
```

Bridge build command shape:

```bash
python -m PyInstaller \
  --name fluentai-bridge \
  --onefile \
  --collect-all openai \
  --collect-all httpx \
  --collect-all pydantic \
  packaging/bridge_entry.py
```

`packaging/bridge_entry.py` should only call `fluent_ai.desktop_bridge.main()`. Prefer a `.spec` file once hidden imports/certs are known.

### Electron builder config

Add config in `package.json` or `electron-builder.yml`:

```yaml
appId: local.fluentai.desktop
productName: FluentAI
files:
  - desktop/electron/**
  - package.json
extraResources:
  - from: dist-py/fluentai-bridge
    to: bridge/fluentai-bridge
mac:
  target: [dir, dmg]
  category: public.app-category.education
  hardenedRuntime: false
  gatekeeperAssess: false
  extendInfo:
    NSMicrophoneUsageDescription: FluentAI uses the microphone for live language tutoring calls.
    NSCameraUsageDescription: FluentAI uses the camera only when you enable video context for tutoring.
```

### Signing and notarization

No paid Apple Developer ID for now:

```bash
npm run package:mac
codesign --force --deep --sign - "dist/mac/FluentAI.app"
open "dist/mac/FluentAI.app"
```

Ad-hoc signing helps local launch but is not notarization. Downloaded/shared builds may still hit Gatekeeper quarantine; personal users may need right-click Open or `xattr -dr com.apple.quarantine FluentAI.app`. Public distribution later needs Developer ID signing, hardened runtime, `xcrun notarytool`, and stapling.

Size expectations:

- Option A: about 230-350 MB compressed DMG.
- Option B: about 300-450 MB.
- Option C: closer to Electron-only size, but too risky now.

## Sequenced Implementation Plan

### 1. Packaging path abstraction

Files: `desktop/electron/main.js`, `fluent_ai/desktop_bridge.py`, tests.

Work: add dev/package bridge resolution, app-support state resolution, and main-side `state_path` injection.

Tests: dev path uses repo `data/progress.json`; packaged-like env uses temp app-support path.

Acceptance: `npm run check` green; memory logs still show load/save.

### 2. State migration and corruption recovery

Files: `desktop/electron/main.js`, `fluent_ai/state.py`, `fluent_ai/desktop_bridge.py`, tests.

Work: copy legacy `data/progress.json` once, backup corrupt JSON, return recovery metadata.

Tests: missing state creates default; legacy copies once; invalid JSON backs up and recovers.

Acceptance: packaged state writes to `~/Library/Application Support/FluentAI/`; dev/tests keep repo or temp paths.

### 3. API key manager

Files: `desktop/electron/main.js`, `preload.js`, `renderer.html`, `fluent_ai/desktop_bridge.py`, `openai_provider.py`, tests.

Work: add safeStorage key IPC, first-run UI, `validate_key`, env injection, and raw-output redaction.

Tests: mocked validation, no secret in logs/raw/progress, dev `.env` fallback only in dev.

Acceptance: no-key app shows setup; valid key enables lesson/call; no secret is printed.

### 4. PyInstaller bridge build

Files: `packaging/bridge_entry.py`, `packaging/fluentai_bridge.spec`, `package.json`.

Work: build `dist-py/fluentai-bridge` with OpenAI dependency graph and certs.

Tests: binary `status` with temp `state_path`; binary missing-key response is clean.

Acceptance: bridge runs without `.venv`; `npm run check` green.

### 5. Electron Builder packaging

Files: `package.json` or `electron-builder.yml`, optional `build/entitlements.mac.plist`, `desktop/electron/main.js`.

Work: include bridge in `extraResources`, add usage descriptions, add ad-hoc signing flow.

Tests: `npm run package:mac`; `codesign --verify --deep --strict dist/mac/FluentAI.app`.

Acceptance: `open dist/mac/FluentAI.app` launches.

### 6. Reliability pass

Files: Electron files, `desktop_bridge.py`, `openai_provider.py`, `state.py`, tests.

Work: add fetch/bridge timeouts, retry paths, lesson/call checkpoints, empty-response recovery, malformed-output repair, and camera voice-only fallback.

Tests: missing key, invalid progress, empty tutor, timeout, malformed output, interrupted lesson, call disconnect.

Acceptance: every Reliability Ideal row has a message and recovery path; no learner state loss in simulations.

### 7. Clean-account acceptance

Commands:

```bash
npm run check
npm run package:mac
codesign --force --deep --sign - "dist/mac/FluentAI.app"
open "dist/mac/FluentAI.app"
```

Manual checks:

- Clean macOS user account.
- Repo moved aside or inaccessible.
- Double-click launches app.
- First-run key entry validates and stores key.
- Lesson starts, quiz submit updates app-support `progress.json`.
- Conversation starts voice-only.
- Camera denial falls back to voice-only.
- Quit mid-lesson shows resume on next launch.

Final acceptance:

- `npm run check` stays green.
- `open dist/FluentAI.app` launches on a clean user account without the repo.
- Consumer mode requires no `.env`, repo path, terminal, or printed secret value.
