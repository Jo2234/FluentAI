# Project decisions and historical evidence

Current behavior is documented in [architecture](docs/GAP_AND_DESIGN.md), [curriculum](docs/CURRICULUM_DESIGN.md), [privacy](docs/ONBOARDING_HOME_DESIGN.md), and [packaging](docs/PACKAGING_DESIGN.md). Pending work lives in the [roadmap](docs/FLUENTAI_LIMITLESS_IDEAL.md).

## Durable decisions

- The project began with a CLI demo and evolved into a shared Electron/browser tutor. The early deterministic user-facing fallback was removed on 2026-06-30; real lesson/conversation runs require OpenAI, while tests mock providers.
- The user selected the red Duolingo-inspired Demo Studio direction in May, followed by an aurora UI overhaul in July. Retain the original mockups and screenshots in `mockups/duolingo-inspired/` as design provenance; they are not all screenshots of today's UI.
- Per-language schema v2 replaced flat memory; lesson and conversation mistakes share review scheduling. Avoid reintroducing compatibility mirrors or overwriting one language during another's session.
- Keep demo learner data intact during development. Use temporary files/profiles for tests and paid API experiments.

## Historical validation, not a fresh acceptance claim

- July 2026 packaging acceptance was attempted with isolated user data and fake media. Host GUI capture/control failed, so full screenshot-based clean-account acceptance was incomplete. Bridge checks exercised onboarding, placement, home, lesson adaptation, checkpoint resume, and secret-safe state. Certificate verification and structured conversation mistake recording defects found in that run were fixed.
- The 2026-09-06 audit recorded 131 Python tests, 11 renderer VM scenarios, JS checks, Ruff, and mocked smoke passing. A wheel installed outside the checkout loaded all three curricula and passed transactional status smoke. No paid API calls were used for that audit. Physical camera and packaged-window lifecycle acceptance remained manual.
- The September audit added transactional writes, reset generations, complete managed-memory deletion, duplicate-submission protection, retryable call finalization, and camera inference filtering. Tests and code are the current authority; old test counts are historical snapshots.

## Cleanup validation (2026-09-10)

- After retiring the Tk launcher and condensing these documents, `npm run check` passed 133 Python tests without skips, 11 renderer scenarios, JS syntax/redaction checks, and mocked smoke. Ruff and relative documentation links passed.
- The PyInstaller bridge passed its outside-checkout status/missing-key/SDK-import smokes. Electron packaging succeeded using the installed lockfile-matching Electron distribution; ad-hoc signing and strict deep signature verification passed. The host required Command Line Tools via a per-command `DEVELOPER_DIR` because its selected Xcode loader was broken. The default Electron download was blocked by sandbox DNS; no source/build-config workaround was committed.
- No paid API calls or physical-camera/clean-account GUI acceptance were performed.

## Provenance

The full construction log and original five design proposals remain available in [the pre-cleanup Git snapshot](https://github.com/Jo2234/FluentAI/tree/d923a6a49243ed19cbad3c3470e165157f2c34b0). In that snapshot, `notes.md` records dated work and validation, and `docs/` contains the original north-star, schema, onboarding, curriculum, and packaging proposals. Their work-package assignments, future-tense descriptions, and old source line numbers are historical, not current implementation instructions. Git history retains authorship and the evolution of those decisions.
