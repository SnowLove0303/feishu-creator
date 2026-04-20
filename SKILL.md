---
name: feishu-app-creation-workflow-v26
description: Create, configure, and publish Feishu/Lark custom apps through a live Chrome session. Use when Codex needs to automate Feishu developer console work such as creating a custom app, enabling Bot capability, importing permissions JSON, subscribing to events like im.message.receive_v1, retrieving App ID/App Secret, or publishing a version. V26 is the speed-optimized version: token pre-fetch before Phase 6 page load, API-only publish verification (no UI navigation), no forced reload in Phase 5, tightened timing constants, and Phase 5 dialog-close fix that eliminated a 30s blocking wait. Typical execution ~82s on stable networks.
---

# Feishu App Creation Workflow V26

Use this skill for any Feishu custom app workflow on stable networks and fast machines. V25 is the **speed-optimized** version — reliability is preserved through per-step verification and retry loops, but timing constants are tightened and key sequential operations are parallelized to minimize wall-clock time.

## V26 vs V24

| Feature | V24 | V26 |
|---------|-----|-----|
| Design goal | Reliability over speed | Speed with reliability |
| Total time | ~77-133s | **~82s** |
| Phase 5 close | `close_confirmation_dialogs` (30s conflict) | `dialog.wait_for("closed")` |
| Phase 5 mode save | Forced reload after every save | Direct verify; reload only as fallback |
| Phase 6 publish check | Sequential: wait 30s then check UI | **API-only**: poll every 5s, no UI navigation |
| Phase 6 token fetch | Inside polling loop (added to every poll) | **Pre-fetched before page load** |
| Phase 2 bot wait | `wait_for_selector("button")` | Explicit Bot card wait |
| Phase 6 form fill | `.fill()` (may miss React) | `fill_react_control()` (always) |
| Phase 4 bot reload | `reload_and_wait` (full button wait) | `goto` + `UI_SETTLE_DELAY` |

## What The Script Does

1. Open the Feishu developer console through Chrome DevTools.
2. Create a custom app.
3. Enable the `Bot` capability.
4. Capture `App ID` and `App Secret`.
5. Import permissions from JSON.
6. Configure event subscription to `Persistent Connection` and add the target event.
7. Create and publish a version — verified by polling the Feishu API (no UI navigation needed).

## Prerequisites

1. Open Chrome and log into [Feishu Open Platform](https://open.feishu.cn/app?lang=zh-CN).
2. Launch Chrome with remote debugging enabled:

```powershell
"C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-address=127.0.0.1 `
  --remote-debugging-port=9222 `
  --user-data-dir=C:\temp\chrome-feishu `
  https://open.feishu.cn/app?lang=zh-CN
```

3. Confirm Python and Playwright are available.

## Normal Run

```powershell
python scripts/fast-workflow.py "My Feishu App"
```

## Resume Run (existing app)

```powershell
python scripts/fast-workflow.py "My Feishu App" cli_xxxxxxxxxxxxxxxx
```

Skips Phase 1 (Create app) and Phase 2 (Add bot).

## Typical Timings

| Phase | Description | V26 Time |
|-------|-------------|----------|
| Phase 1 | Create app | ~8s |
| Phase 2 | Add bot | ~13s |
| Phase 3 | Get credentials | ~4s |
| Phase 4 | Import permissions | ~6s |
| Phase 5 | Subscribe event | ~5s |
| Phase 6 | Publish version | ~30s (Feishu internal constraint) |
| **Total** | Full workflow | **~82s** |

## Key Design Decisions

### Phase 5 dialog close (the critical V25 fix)

Phase 5 confirms an event selection by clicking "添加" (Add) in the event dialog. The original code then called `close_confirmation_dialogs()` which searches for any visible confirmation button matching `CONFIRMATION_LABELS` — which includes "Add" / "添加". This caused it to re-click the **same** "添加" button, retriggering the dialog, waiting 30s for it to close again.

V25 fixes this by using `dialog.wait_for(state="closed", timeout=5)` instead — no label matching, no conflict.

### Phase 5 reload elimination (V25 fast path)

After saving the subscription mode, V24 always reloaded the page to verify persistence. V25 verifies directly on the current page first (via `wait_for_body_contains`), only reloading if the mode is not visible. Most runs succeed in the fast path, saving a full page reload + React render cycle.

### Phase 6 API-only publish verification with token pre-fetch (V26)

Before navigating to the version page, V26 fetches the tenant token in the main thread. While the browser loads the page and fills the form, the token is already cached in a local variable:

```python
# Pre-fetch BEFORE page load — saves ~1-2s from each poll cycle
token_req = Request(...)
with urlopen(token_req, timeout=10) as resp:
    tenant_token = json.loads(resp.read())["tenant_access_token"]

# Page navigation and form fill run concurrently...
await page.goto(...)
# _check_version() uses the cached tenant_token — no auth round-trip on any poll
```

Feishu takes ~30s internally after the publish button is clicked. V26 polls every 5s using the pre-fetched token (no auth overhead per poll). Status `1` (not the string `"published"`) confirms the version is published for self-built apps.

### React controlled input

All form fields use `fill_react_control()` which:
1. Types via keyboard (`Ctrl+A` + `type()`) to trigger React events naturally
2. Falls back to JS value setter + dispatched events
3. Verifies the value persisted before returning

## Version History

| Version | Notes |
|---------|-------|
| V26 | Token pre-fetch before Phase 6 page load; API-only verification, ~82s |
| V25 | API-only publish verification, Phase 5 dialog fix, ~84s |
| V24 | Universal/robust: conservative timing, sub-step verification, retry loops |
| V23 | Speed-optimized V21: tight timing, ~79s |
| V20 | Initial stable version |
