#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feishu custom app creation workflow - V25 Fast

A speed-optimized version for stable networks and fast machines.
Reliability is preserved through per-step verification and retry loops,
but timing constants are tightened to minimize wall-clock time.

Typical execution: ~78s (code only; Python module loading adds ~40s on first run).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen, Request

_t0 = None
_t = None

# ─────────────── Timing constants (speed-optimized) ────────────────────────
# These are the minimum viable values for stable networks and fast machines.
# For unreliable environments, increase UI_SETTLE_DELAY and SAVE_SETTLE_DELAY.

SHORT_DELAY = 0.15        # Keyboard/click action spacing
UI_SETTLE_DELAY = 0.5      # React UI settle after page action
SAVE_SETTLE_DELAY = 0.75    # Feishu API round-trip after save
RELOAD_SETTLE_DELAY = 0.75 # Page reload + React render
POLL_INTERVAL = 0.2        # Async poll interval
CONFIRM_ROUND_DELAY = 0.4  # Dialog button click spacing
MAX_URL_WAIT = 20.0        # URL pattern match timeout
ENABLE_TIMEOUT = 10.0       # Button enable timeout
BODY_CHECK_TIMEOUT = 10.0   # wait_for_body_contains timeout

# ──────────────────────────── Label sets ─────────────────────────────────────

LOGIN_LABELS = ["Login", "Log in", "Sign in", "登录"]
CREATE_APP_ENTRY_LABELS = ["Create App", "创建应用"]
CREATE_CUSTOM_APP_LABELS = ["Create Custom App", "创建企业自建应用"]
CREATE_LABELS = ["Create", "创建"]
ADD_FEATURES_LABELS = ["Add Features", "添加应用能力"]
ADD_LABELS = ["Add", "添加"]
SAVE_LABELS = ["Save", "保存"]
ENABLE_LABELS = ["Enable", "启用"]
NEXT_LABELS = ["Next", "下一步", "下一步，确认新增权限"]
BATCH_IMPORT_LABELS = ["Batch import/Export Permissions", "批量导入/导出权限", "批量导入"]
PUBLISH_LABELS = ["Publish", "确认发布"]
CREATE_VERSION_LABELS = ["Create Version", "创建版本"]
PERSISTENT_CONNECTION_LABELS = ["Persistent Connection", "长连接"]
SUBSCRIPTION_MODE_LABELS = ["Subscription mode", "订阅方式"]
EVENTS_PAGE_LABELS = ["Events and callbacks", "事件与回调"]
ADD_EVENTS_LABELS = ["Add Events", "添加事件"]
BOT_LABELS = ["Bot", "机器人"]
RELEASED_LABELS = ["Released", "已发布"]
CONFIRMATION_LABELS = [
    "Confirm", "OK", "Done", "Open", "Enable", "Save", "Add",
    "确认", "确定", "完成", "开启", "启用", "保存", "添加",
]


# ──────────────────────────── Helpers ───────────────────────────────────────

def _tick(msg: str):
    global _t
    now = time.time()
    elapsed = now - (_t or _t0 or now)
    print(f"  [{elapsed:>6.2f}s] V25: {msg}")
    _t = now
    return now


def text_regex(labels: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(label) for label in labels), re.IGNORECASE)


def console_url(path: str = "/app") -> str:
    if path == "/app":
        return "https://open.feishu.cn/app?lang=zh-CN"
    sep = "&" if "?" in path else "?"
    return f"https://open.feishu.cn{path}{sep}lang=zh-CN"


def load_permissions_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Permissions file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    return match.group(1).strip() if match else raw.strip()


def extract_app_id(url: str) -> str:
    m = re.search(r"/app/(cli_[^/]+)", url or "")
    return m.group(1) if m else ""


def mask_secret(secret: str) -> str:
    if len(secret) <= 10:
        return secret
    return f"{secret[:10]}..."


# ──────────────────────────── CDP connect ──────────────────────────────────

async def get_cdp_page(cdp_url: str):
    with urlopen(f"{cdp_url}/json/version", timeout=15) as resp:
        ws_url = json.loads(resp.read().decode("utf-8"))["webSocketDebuggerUrl"]

    from playwright.async_api import async_playwright
    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(ws_url)
    context = browser.contexts[0] if browser.contexts else await browser.new_context()

    page = None
    for candidate in context.pages:
        try:
            if "feishu" in (candidate.url or "") or "lark" in (candidate.url or ""):
                page = candidate
                break
        except Exception:
            continue
    if page is None:
        page = context.pages[0] if context.pages else await context.new_page()

    return playwright, browser, page


# ──────────────────────────── Clipboard ───────────────────────────────────

async def read_system_clipboard() -> str:
    if os.name == "nt":
        cmd = ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"]
    else:
        cmd = ["pbpaste"]
    try:
        result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=15)
        return (result.stdout or "").strip()
    except Exception:
        return ""


# (capture_clipboard_via_js removed — logic inlined in phase3_get_credentials)


# ──────────────────────────── Core utilities ────────────────────────────────

async def click_first_visible(locator):
    count = await locator.count()
    for i in range(count):
        c = locator.nth(i)
        try:
            if not await c.is_visible():
                continue
            if await c.is_enabled():
                await c.click()
                return True
        except Exception:
            continue
    return False


async def click_by_labels(page_or_locator, labels: list[str], selectors: str = "button",
                          timeout: float = 10, poll: float = POLL_INTERVAL) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    pattern = text_regex(labels)
    while asyncio.get_running_loop().time() < deadline:
        loc = page_or_locator.locator(selectors).filter(has_text=pattern)
        if await click_first_visible(loc):
            return True
        await asyncio.sleep(poll)
    return False


async def wait_for_dialog(page, timeout_ms: int = 10000):
    dialog = page.locator('[role="dialog"]').filter(
        has=page.locator("button, textarea, input")
    ).first
    await dialog.wait_for(state="visible", timeout=timeout_ms)
    return dialog


# ── Non-blocking body text checks ──────────────────────────────────────────

async def body_text(page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""


async def body_contains(page, labels: list[str]) -> bool:
    text = await body_text(page)
    return any(label in text for label in labels)


async def wait_for_body_contains(page, labels: list[str], timeout: float = BODY_CHECK_TIMEOUT,
                                  interval: float = POLL_INTERVAL) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            if await body_contains(page, labels):
                return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


async def wait_until_enabled(locator, timeout: float = ENABLE_TIMEOUT,
                              interval: float = POLL_INTERVAL) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            if await locator.count() and await locator.first.is_visible() and not await locator.first.is_disabled():
                return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


# ──────────────────────────── Reload ────────────────────────────────────────

async def reload_and_wait(page, url: str | None = None):
    if url:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    else:
        await page.reload(wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector("button", state="visible", timeout=15000)
    await asyncio.sleep(RELOAD_SETTLE_DELAY)


# ──────────────────────────── Login check ───────────────────────────────────

async def login_required(page) -> bool:
    loc = page.locator("button, a, [role='button']").filter(has_text=text_regex(LOGIN_LABELS))
    return await loc.count() > 0


async def ensure_logged_in(page):
    if await login_required(page):
        raise RuntimeError(
            "Login required: sign in to Feishu Open Platform in the attached Chrome session, then rerun."
        )


# ──────────────────────────── URL wait ──────────────────────────────────────

async def wait_for_url_match(page, pattern: str, timeout: float = MAX_URL_WAIT) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if re.search(pattern, page.url or ""):
            return True
        await asyncio.sleep(POLL_INTERVAL)
    return False


# ──────────────────────────── App finder ───────────────────────────────────

async def find_app_and_open(page, app_name: str) -> bool:
    rows = page.locator("tr").filter(has_text=text_regex([app_name]))
    if await rows.count() == 0:
        return False
    row = rows.first
    cells = row.locator("td")
    if await cells.count():
        await cells.first.click()
        await asyncio.sleep(UI_SETTLE_DELAY)
        return True
    await row.click()
    await asyncio.sleep(UI_SETTLE_DELAY)
    return True


# ──────────────────────────── React input fill ─────────────────────────────

async def fill_react_control(page, locator, value: str):
    """
    Fill a React controlled input field reliably.
    Strategy 1: keyboard Ctrl+A → type (simulates real user)
    Strategy 2: JS value setter + events (direct DOM manipulation)
    Verifies the value persisted before returning.
    """
    await locator.wait_for(state="visible", timeout=10000)
    await locator.click()
    try:
        await locator.fill("")
    except Exception:
        pass

    try:
        await page.keyboard.press("Control+a")
        await page.keyboard.type(value, delay=20)
    except Exception:
        pass

    try:
        current = await locator.input_value()
    except Exception:
        current = ""

    if current != value:
        try:
            current = await locator.evaluate(
                """(el, nextValue) => {
                    const proto = el.tagName === "TEXTAREA"
                        ? HTMLTextAreaElement.prototype
                        : HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
                    setter.call(el, nextValue);
                    if (el._valueTracker) el._valueTracker.setValue("");
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                    el.dispatchEvent(new Event("blur", { bubbles: true }));
                    return el.value || "";
                }""",
                value,
            )
        except Exception:
            pass

    try:
        await locator.press("Tab")
    except Exception:
        pass
    await asyncio.sleep(SHORT_DELAY)

    if current != value:
        raise RuntimeError(
            f"Field value did not persist. Expected '{value}', got '{current}'."
        )


# ──────────────────────────── Monaco paste ──────────────────────────────────

async def monaco_paste(page, text: str):
    """
    Paste text into the Monaco editor (used for batch permission import).
    Monaco does not respond to standard Playwright paste — we must:
      1. Write text to navigator.clipboard via JS
      2. Focus the Monaco textarea
      3. Ctrl+A → Delete → Ctrl+V
    """
    await page.evaluate("(v) => navigator.clipboard.writeText(v)", text)
    await asyncio.sleep(SHORT_DELAY)

    ta = page.locator(".monaco-editor textarea").first
    await ta.wait_for(state="visible", timeout=10000)
    await ta.focus()
    await asyncio.sleep(SHORT_DELAY)

    await page.keyboard.press("Control+a")
    await asyncio.sleep(SHORT_DELAY)
    await page.keyboard.press("Delete")
    await asyncio.sleep(SHORT_DELAY)
    await page.keyboard.press("Control+v")
    await asyncio.sleep(UI_SETTLE_DELAY)


# ──────────────────────────── Confirmation dialogs ─────────────────────────

async def close_confirmation_dialogs(page, max_rounds: int = 4):
    for _ in range(max_rounds):
        dialogs = page.locator('[role="dialog"]')
        if await dialogs.count() == 0:
            return
        dialog = dialogs.first
        buttons = dialog.locator("button").filter(has_text=text_regex(CONFIRMATION_LABELS))
        if not await click_first_visible(buttons):
            return
        await asyncio.sleep(CONFIRM_ROUND_DELAY)


# ──────────────────────────── PHASE 1: Create App ──────────────────────────

async def open_create_app_dialog(page):
    if await click_by_labels(page, CREATE_CUSTOM_APP_LABELS, "button, a, [role='button']",
                              timeout=6, poll=POLL_INTERVAL):
        await wait_for_dialog(page)
        _tick("Create dialog opened (strategy 1)")
        return

    if await click_by_labels(page, CREATE_APP_ENTRY_LABELS, "button, a, [role='button']",
                              timeout=6, poll=POLL_INTERVAL):
        await asyncio.sleep(UI_SETTLE_DELAY)
        if await page.locator('[role="dialog"]').count():
            await wait_for_dialog(page)
            _tick("Create dialog opened (strategy 2)")
            return
        if await click_by_labels(page, CREATE_CUSTOM_APP_LABELS, "button, a, [role='button']",
                                  timeout=8, poll=POLL_INTERVAL):
            await wait_for_dialog(page)
            _tick("Create dialog opened (strategy 2b)")
            return

    create_btn = page.locator(".data-test__create-app-button").first
    if await create_btn.count():
        await create_btn.click()
        await wait_for_dialog(page)
        _tick("Create dialog opened (strategy 3)")
        return

    raise RuntimeError("Failed to open the create-app dialog.")


async def fill_create_dialog(page, app_name: str, description: str):
    dialog = await wait_for_dialog(page)
    name_input = dialog.locator('input:not([type="file"])').first
    desc_input = dialog.locator("textarea").first

    await fill_react_control(page, name_input, app_name)
    await fill_react_control(page, desc_input, description)

    name_value = await name_input.evaluate("el => el.value || ''")
    desc_value = await desc_input.evaluate("el => el.value || ''")
    if name_value != app_name or desc_value != description:
        raise RuntimeError(
            f"Create dialog values changed before submission. "
            f"name='{name_value}' desc='{desc_value}'"
        )

    if not await click_by_labels(dialog, CREATE_LABELS, "button", timeout=8):
        raise RuntimeError("Failed to click Create in the dialog.")
    _tick("Create button clicked, waiting for navigation...")


async def phase1_create_app(page, config) -> str:
    _tick("[Phase 1] Create app starts")

    await page.goto("https://open.feishu.cn/app?lang=zh-CN",
                    wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector("button", state="visible", timeout=15000)
    await asyncio.sleep(UI_SETTLE_DELAY)
    await ensure_logged_in(page)

    await open_create_app_dialog(page)
    await fill_create_dialog(page, config.app_name, config.app_description)

    if await wait_for_url_match(page, r"/app/cli_", timeout=25):
        app_id = extract_app_id(page.url)
        _tick(f"[Phase 1] App created, app_id={app_id}")
        return app_id

    _tick("[Phase 1] URL did not change to /app/cli_, searching app list...")
    await page.goto("https://open.feishu.cn/app?lang=zh-CN",
                    wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector("button", state="visible", timeout=15000)
    await asyncio.sleep(UI_SETTLE_DELAY)

    for attempt in range(25):
        if await find_app_and_open(page, config.app_name):
            _tick(f"[Phase 1] App found in list at attempt {attempt + 1}")
            await asyncio.sleep(UI_SETTLE_DELAY)
            app_id = extract_app_id(page.url)
            if app_id:
                return app_id
        if attempt in {8, 16}:
            await reload_and_wait(page)
        else:
            await asyncio.sleep(POLL_INTERVAL)

    text = await body_text(page)
    if "undefined" in text:
        raise RuntimeError(
            "App list shows 'undefined' — the create dialog fields did not persist. "
            "Check fill_react_control() and retry."
        )
    raise RuntimeError("App was created but the workflow could not enter the app detail page.")


# ──────────────────────────── PHASE 2: Add Bot ────────────────────────────

async def phase2_add_bot(page, config) -> None:
    _tick("[Phase 2] Add bot starts")

    if "/app/cli_" not in (page.url or ""):
        await page.goto("https://open.feishu.cn/app?lang=zh-CN",
                        wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("button", state="visible", timeout=15000)
        await asyncio.sleep(UI_SETTLE_DELAY)
        for _ in range(12):
            if await find_app_and_open(page, config.app_name):
                break
            await asyncio.sleep(POLL_INTERVAL)
        await asyncio.sleep(UI_SETTLE_DELAY)

    app_id = extract_app_id(page.url)
    if not app_id:
        raise RuntimeError("Could not extract app_id from current URL.")

    cap_url = console_url(f"/app/{app_id}/capability")
    await page.goto(cap_url, wait_until="domcontentloaded", timeout=30000)
    # Wait for Bot card to be visible before JS injection
    bot_card = page.locator("*").filter(has_text=text_regex(BOT_LABELS)).first
    try:
        await bot_card.wait_for(state="visible", timeout=10000)
    except Exception:
        pass
    await asyncio.sleep(SAVE_SETTLE_DELAY)

    result = await page.evaluate(
        """() => {
            const visible = (el) => {
                const s = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.visibility !== "hidden" && s.display !== "none" && r.width > 0 && r.height > 0;
            };
            const isBotText = (t) => /(^|\\s)(Bot|机器人)(\\s|$)/i.test((t || "").trim());
            const isAddLike = (t) => /(Add|Enable|添加|启用)/i.test((t || "").trim());
            const all = Array.from(document.querySelectorAll("*")).filter(visible);
            for (const node of all) {
                if (!isBotText(node.textContent || "")) continue;
                let scope = node;
                for (let d = 0; d < 10 && scope; d += 1, scope = scope.parentElement) {
                    const btn = Array.from(scope.querySelectorAll("button")).find(
                        (b) => visible(b) && !b.disabled && isAddLike(b.textContent || "")
                    );
                    if (btn) { btn.click(); return true; }
                }
            }
            return false;
        }"""
    )
    if not result:
        raise RuntimeError("Failed to locate the Add Bot button on the capability page.")

    _tick("[Phase 2] Bot button clicked, waiting for confirm dialog...")
    await asyncio.sleep(SHORT_DELAY)

    await click_by_labels(page.locator('[role="dialog"]').first, ENABLE_LABELS, "button", timeout=8)
    _tick("[Phase 2] Confirm dialog button clicked, waiting for bot activation...")

    # Navigate to base info and verify Bot label is present
    await page.goto(console_url(f"/app/{app_id}/baseinfo"),
                    wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector("button", state="visible", timeout=15000)
    await asyncio.sleep(UI_SETTLE_DELAY)

    if not await wait_for_body_contains(page, BOT_LABELS, timeout=10):
        raise RuntimeError("Bot capability does not appear to be enabled after Phase 2.")

    _tick("[Phase 2] Bot capability confirmed.")


# ──────────────────────────── PHASE 3: Get Credentials ─────────────────────

async def phase3_get_credentials(page, config, app_id: str | None = None) -> tuple[str, str]:
    _tick("[Phase 3] Get credentials starts")

    current_app_id = app_id or extract_app_id(page.url)
    if not current_app_id:
        raise RuntimeError("Could not resolve App ID from the current URL.")

    await page.goto(console_url(f"/app/{current_app_id}/baseinfo"),
                    wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector("button", state="visible", timeout=15000)
    await asyncio.sleep(UI_SETTLE_DELAY)

    actual_app_id = extract_app_id(page.url)
    if not actual_app_id:
        raise RuntimeError("Could not resolve App ID from current URL after navigation.")

    primary_loc = page.locator(".secret-code__btn")
    try:
        await primary_loc.first.wait_for(state="visible", timeout=8000)
    except Exception:
        pass
    secret_buttons = page.locator(".secret-code__btn")
    if await secret_buttons.count() < 2:
        fallback_loc = page.locator("button").filter(has_text=text_regex(["Secret", "密钥", "App Secret"]))
        if await fallback_loc.count() >= 1:
            _tick("[Phase 3] Using fallback secret button selector")
            secret_buttons = fallback_loc
        else:
            raise RuntimeError("App Secret controls not found on the page.")

    # Set up JS clipboard interceptor BEFORE clicking. Feishu calls writeText() synchronously
    # via Clipboard API, so we wrap it to capture the value before passing through.
    await page.evaluate("() => { window._clipCapture = null; }")
    await page.evaluate("""
        () => {
            const _orig = navigator.clipboard.writeText.bind(navigator.clipboard);
            navigator.clipboard.writeText = function(text) {
                window._clipCapture = text;
                return _orig(text);
            };
        }
    """)

    await secret_buttons.nth(1).click()
    _tick("[Phase 3] Secret reveal button clicked")
    await asyncio.sleep(UI_SETTLE_DELAY)

    # Primary: read from JS-intercepted clipboard value
    js_captured = await page.evaluate("() => window._clipCapture")
    if js_captured and re.fullmatch(r"[A-Za-z0-9]{32,64}", js_captured):
        app_secret = js_captured
    else:
        # Fallback: OS clipboard (PowerShell Get-Clipboard)
        raw_clip = await read_system_clipboard()
        if raw_clip and re.fullmatch(r"[A-Za-z0-9]{32,64}", raw_clip):
            app_secret = raw_clip
        else:
            # Last resort: extract from page body text
            text = await body_text(page)
            candidates = re.findall(r"\b[A-Za-z0-9]{32,64}\b", text)
            app_secret = candidates[-1] if candidates else ""

    if not re.fullmatch(r"[A-Za-z0-9]{32,64}", app_secret or ""):
        raise RuntimeError("App Secret was not captured correctly (not 32-64 char alphanumeric).")

    _tick(f"[Phase 3] App ID: {actual_app_id}, Secret: {mask_secret(app_secret)}")
    return actual_app_id, app_secret


# ──────────────────────────── PHASE 4: Import Permissions ───────────────────

async def phase4_import_permissions(page, config, app_id: str, permissions_json: str) -> None:
    _tick("[Phase 4] Import permissions starts")

    auth_url = console_url(f"/app/{app_id}/auth")
    await page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector("button", state="visible", timeout=15000)
    await asyncio.sleep(UI_SETTLE_DELAY)

    next_button = None
    for attempt in range(2):
        if not await click_by_labels(page, BATCH_IMPORT_LABELS, "button, a, [role='button']",
                                      timeout=10, poll=POLL_INTERVAL):
            if attempt == 0:
                _tick("[Phase 4] Batch import button not found, reloading and retrying...")
                await reload_and_wait(page, auth_url)
                continue
            raise RuntimeError("Failed to open the permissions batch-import dialog.")

        await asyncio.sleep(UI_SETTLE_DELAY)
        await wait_for_dialog(page)
        _tick("[Phase 4] Monaco dialog opened, pasting JSON...")
        await monaco_paste(page, permissions_json)

        next_button = page.locator("button").filter(has_text=text_regex(NEXT_LABELS)).first
        await next_button.wait_for(state="visible", timeout=8000)

        if not await next_button.is_disabled():
            _tick("[Phase 4] Next button is enabled (Monaco paste succeeded)")
            break

        if attempt == 0:
            _tick("[Phase 4] Next still disabled, retrying paste...")
            await page.keyboard.press("Control+v")
            await asyncio.sleep(UI_SETTLE_DELAY)
            if not await next_button.is_disabled():
                _tick("[Phase 4] Next enabled on second paste attempt")
                break
            await page.keyboard.press("Escape")
            await asyncio.sleep(SHORT_DELAY)
            await reload_and_wait(page, auth_url)
            continue

        raise RuntimeError("Permissions paste did not unlock the Next button.")

    print("  [OK] Next button is enabled after Monaco paste")
    await next_button.click()
    await asyncio.sleep(SAVE_SETTLE_DELAY)

    initial_confirm_labels = ["Add", "添加", "申请开通", "确认新增权限"]
    clicked = False
    if await page.locator('[role="dialog"]').count():
        dialog = await wait_for_dialog(page, timeout_ms=8000)
        clicked = await click_by_labels(dialog, initial_confirm_labels, "button", timeout=8)
    if not clicked:
        clicked = await click_by_labels(page, initial_confirm_labels, "button", timeout=8)
    if not clicked:
        raise RuntimeError("Failed to confirm imported permissions (first dialog).")
    await asyncio.sleep(SAVE_SETTLE_DELAY)

    for _ in range(6):
        if await page.locator('[role="dialog"]').count() == 0:
            _tick("[Phase 4] All dialogs closed, permissions imported.")
            return
        dialog = page.locator('[role="dialog"]').first
        dialog_text = await dialog.inner_text()

        if any(b in dialog_text for b in BOT_LABELS) and ("permission" in dialog_text.lower() or "权限" in dialog_text):
            _tick("[Phase 4] Bot permission confirmation dialog detected, reloading...")
            await page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(UI_SETTLE_DELAY)
            return

        followup_labels = ["Confirm", "确认", "Open", "开启", "Save", "保存",
                          "OK", "Done", "申请开通"]
        if not await click_by_labels(dialog, followup_labels, "button", timeout=5):
            break
        await asyncio.sleep(UI_SETTLE_DELAY)

    _tick("[Phase 4] Permissions import complete.")


# ──────────────────────────── PHASE 5: Event Subscription ─────────────────

async def configure_subscription_mode(page) -> None:
    edit_result = await page.evaluate(
        """() => {
            const visible = (el) => {
                const s = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.visibility !== "hidden" && s.display !== "none" && r.width > 0 && r.height > 0;
            };
            const label = Array.from(document.querySelectorAll("span"))
                .find((el) => visible(el) && /Subscription mode|订阅方式/i.test((el.textContent || "").trim()));
            if (!label) return "label-not-found";
            const direct = label.parentElement?.querySelector("button");
            if (direct && visible(direct)) { direct.click(); return "direct-button"; }
            const fallback = label.closest("div, span, label")?.querySelector("button");
            if (fallback && visible(fallback)) { fallback.click(); return "fallback-button"; }
            return "not-found";
        }"""
    )
    if edit_result == "not-found":
        raise RuntimeError("Failed to find the subscription mode editor.")
    _tick(f"[Phase 5] Subscription mode editor opened: {edit_result}")
    await asyncio.sleep(UI_SETTLE_DELAY)

    selected_mode = False
    for label in PERSISTENT_CONNECTION_LABELS:
        text_match = page.get_by_text(label, exact=False).first
        try:
            if not await text_match.count() or not await text_match.is_visible():
                continue
        except Exception:
            continue

        for candidate in [
            text_match.locator("xpath=ancestor::label[1]").first,
            text_match.locator("xpath=ancestor::*[@role='radio'][1]").first,
            text_match,
        ]:
            try:
                if await candidate.count() and await candidate.is_visible():
                    await candidate.click()
                    selected_mode = True
                    break
            except Exception:
                continue
        if selected_mode:
            break

    if not selected_mode:
        raise RuntimeError("Failed to select the Persistent Connection mode.")
    _tick("[Phase 5] Persistent Connection selected")
    await asyncio.sleep(UI_SETTLE_DELAY)

    if not await body_contains(page, PERSISTENT_CONNECTION_LABELS):
        raise RuntimeError("Persistent Connection mode did not appear after selection.")

    if not await click_by_labels(page, SAVE_LABELS, "button", timeout=8):
        raise RuntimeError("Failed to save the subscription mode.")
    _tick("[Phase 5] Subscription mode saved")
    await asyncio.sleep(SAVE_SETTLE_DELAY)


async def phase5_event_subscription(page, config, app_id: str) -> None:
    """
    Phase 5: Configure event subscription.

    Key optimization (V25): No forced reload after subscription mode save.
    Instead, verify directly on the current page — fast path when it works,
    reload only as fallback when the current page state is stale.
    """
    _tick("[Phase 5] Subscribe event starts")

    await page.goto(console_url(f"/app/{app_id}/event"),
                    wait_until="domcontentloaded", timeout=30000)
    if not await wait_for_body_contains(page, EVENTS_PAGE_LABELS, timeout=15):
        raise RuntimeError("Failed to open the Events & Callbacks page.")
    _tick("[Phase 5] Events page loaded")

    add_events_button = None
    for attempt in range(2):
        if attempt == 0 or not await body_contains(page, PERSISTENT_CONNECTION_LABELS):
            await configure_subscription_mode(page)

        add_events_button = page.get_by_role("button", name=text_regex(ADD_EVENTS_LABELS)).first

        # Fast path: verify directly on current page (no reload)
        mode_ok = await wait_for_body_contains(page, PERSISTENT_CONNECTION_LABELS, timeout=5)
        btn_ok = await wait_until_enabled(add_events_button, timeout=ENABLE_TIMEOUT)
        if mode_ok and btn_ok:
            _tick("[Phase 5] Subscription mode persistent, Add Events button enabled")
            break

        if attempt == 0:
            # Reload as fallback
            _tick("[Phase 5] Mode not visible, reloading to verify...")
            await reload_and_wait(page)
            _tick("[Phase 5] Reload complete, attempt 2")
            mode_ok = await wait_for_body_contains(page, PERSISTENT_CONNECTION_LABELS, timeout=5)
            btn_ok = await wait_until_enabled(add_events_button, timeout=ENABLE_TIMEOUT)
            if mode_ok and btn_ok:
                _tick("[Phase 5] Subscription mode persistent after reload")
                break

        raise RuntimeError(
            "Add Events is still disabled after saving the subscription mode. "
            "The mode may not have been saved correctly."
        )

    await add_events_button.click()
    _tick("[Phase 5] Add Events dialog opened")
    await asyncio.sleep(SAVE_SETTLE_DELAY)

    dialog = await wait_for_dialog(page)
    search_input = dialog.locator("input").filter(has_not=dialog.locator('[type="hidden"]')).first
    await search_input.fill(config.event_name)
    _tick(f"[Phase 5] Search input filled: {config.event_name}")
    await asyncio.sleep(UI_SETTLE_DELAY)

    checkbox_result = await dialog.evaluate(
        """(eventName) => {
            const visible = (el) => {
                const s = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.visibility !== "hidden" && s.display !== "none" && r.width > 0 && r.height > 0;
            };
            const rows = Array.from(document.querySelectorAll(
                '[role="dialog"] tr, [role="dialog"] li, [role="dialog"] [role="row"]'
            ));
            for (const row of rows) {
                if (!row.textContent.includes(eventName)) continue;
                const cb = row.querySelector('[role="checkbox"], input[type="checkbox"]');
                if (cb && visible(cb)) { cb.click(); return true; }
            }
            const fallback = Array.from(document.querySelectorAll('[role="dialog"] [role="checkbox"]')).find(visible);
            if (fallback) { fallback.click(); return true; }
            return false;
        }""",
        config.event_name,
    )
    if not checkbox_result:
        raise RuntimeError(f"Failed to select the event '{config.event_name}' in the dialog.")
    _tick(f"[Phase 5] Event checkbox selected: {config.event_name}")

    if not await click_by_labels(dialog, ADD_LABELS, "button", timeout=8):
        raise RuntimeError("Failed to confirm the event selection.")
    _tick("[Phase 5] Event confirmed, waiting for dialog to close...")

    # Wait for dialog to close via Feishu's natural transition.
    # Do NOT call close_confirmation_dialogs here — its ADD_LABELS overlap
    # with this dialog's "添加" button and causes a 30s wait.
    try:
        await dialog.wait_for(state="closed", timeout=5)
    except Exception:
        pass
    await asyncio.sleep(UI_SETTLE_DELAY)

    # Verify the event actually appears before exiting Phase 5.
    # Catches silent dialog-confirm failures before Phase 6 starts.
    event_in_page = await body_contains(page, [config.event_name])
    if not event_in_page:
        _tick("[Phase 5] Event not yet in page body, reloading to verify...")
        await reload_and_wait(page)
        event_in_page = await wait_for_body_contains(page, [config.event_name], timeout=8)
    if not event_in_page:
        raise RuntimeError(
            f"Event '{config.event_name}' was confirmed in the dialog but does not "
            f"appear in the subscription list. The subscription may not have persisted."
        )
    _tick(f"[Phase 5] Event '{config.event_name}' confirmed in subscription list")


# ──────────────────────────── PHASE 6: Publish Version ─────────────────────

async def phase6_publish_version(page, config, app_id: str, app_secret: str) -> None:
    """
    Phase 6: Create and publish a version.

    Key optimization (V25): API-only publish verification.
    No UI navigation needed — the Feishu API is authoritative for version status.
    Runs tenant token + version query in a background thread via asyncio.to_thread,
    polling every 5s until "published" is seen or 60s timeout.
    """
    _tick("[Phase 6] Publish version starts")

    await page.goto(console_url(f"/app/{app_id}/version"),
                    wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector("button", state="visible", timeout=15000)
    await asyncio.sleep(UI_SETTLE_DELAY)

    if not await click_by_labels(page, CREATE_VERSION_LABELS, "button, a, [role='button']",
                                  timeout=10, poll=POLL_INTERVAL):
        raise RuntimeError("Failed to open the version creation form.")
    _tick("[Phase 6] Version creation form opened")
    await asyncio.sleep(UI_SETTLE_DELAY)

    # React controlled — must use fill_react_control
    version_input = page.locator('input[placeholder*="version"], input[placeholder*="版本"]').first
    await version_input.wait_for(state="visible", timeout=8000)
    await fill_react_control(page, version_input, config.version)
    _tick(f"[Phase 6] Version filled: {config.version}")

    notes_area = page.locator("textarea").first
    await notes_area.wait_for(state="visible", timeout=8000)
    await fill_react_control(page, notes_area, config.version_notes)
    _tick("[Phase 6] Release notes filled")

    if not await click_by_labels(page, SAVE_LABELS, "button", timeout=8):
        raise RuntimeError("Failed to save the version draft.")
    _tick("[Phase 6] Version draft saved")
    await asyncio.sleep(SAVE_SETTLE_DELAY)

    if not await click_by_labels(page, PUBLISH_LABELS, "button", timeout=10):
        dialog = page.locator('[role="dialog"]').first
        if not await click_by_labels(dialog, PUBLISH_LABELS, "button", timeout=5):
            raise RuntimeError("Failed to trigger the publish action.")
    _tick("[Phase 6] Publish button clicked")
    await asyncio.sleep(SAVE_SETTLE_DELAY)

    # Close any confirmation dialogs that appear after publish
    await close_confirmation_dialogs(page, max_rounds=4)

    # ── API-first verification (V25 API-only, no UI navigation) ──
    # Feishu takes ~30s internally after publish is clicked before the API reflects
    # "published" status. The Feishu API is authoritative — UI state always lags.
    # We run the check in a background thread so the asyncio event loop is not blocked.

    def _sync_check_api() -> bool:
        """Run auth + version query synchronously in a background thread."""
        try:
            token_req = Request(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urlopen(token_req, timeout=10) as resp:
                token_data = json.loads(resp.read())
            tenant_token = token_data.get("tenant_access_token")
            if not tenant_token:
                _tick("[Phase 6] API: failed to get tenant token")
                return False
            version_req = Request(
                f"https://open.feishu.cn/open-apis/application/v6/applications/{app_id}/app_versions?lang=zh_cn&page_size=5",
                headers={"Authorization": f"Bearer {tenant_token}"},
                method="GET"
            )
            with urlopen(version_req, timeout=10) as resp:
                version_data = json.loads(resp.read())
            items = (version_data.get("data") or {}).get("items") or []
            for item in items:
                # Feishu status: 0=draft, 1=published (for self-built apps, publish is instant).
                status = item.get("status")
                version_str = item.get("version", "?")
                if status == 1 or status == "published" or item.get("publish_time"):
                    _tick(f"[Phase 6] API confirmed: version '{version_str}' is published (status={status})")
                    return True
            return False
        except HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            _tick(f"[Phase 6] API HTTP error {e.code}: {body}")
            return False
        except Exception as e:
            _tick(f"[Phase 6] API check failed: {e}")
            return False

    _tick("[Phase 6] Waiting for Feishu to process publish (API polling)...")
    # Poll until confirmed or timeout. asyncio.to_thread avoids blocking the event loop.
    deadline = asyncio.get_running_loop().time() + 60
    while asyncio.get_running_loop().time() < deadline:
        result = await asyncio.to_thread(_sync_check_api)
        if result:
            _tick("[Phase 6] Version published — confirmed via API")
            return
        await asyncio.sleep(5)  # Feishu takes ~30s; check every 5s

    raise RuntimeError(
        "API could not confirm the version was published within 60s. "
        "The publish may have failed. Check the Feishu console manually."
    )


# ──────────────────────────── Workflow orchestration ───────────────────────

async def run_workflow(config) -> dict:
    permissions_json = load_permissions_text(config.permissions_file)
    playwright, browser, page = await get_cdp_page(config.cdp_url)

    result = {
        "app_name": config.app_name,
        "app_id": config.resume_app_id or "",
        "app_secret": "",
        "success": False,
    }

    try:
        if config.resume_app_id:
            app_id = config.resume_app_id
        else:
            app_id = await phase1_create_app(page, config)
            result["app_id"] = app_id
            await phase2_add_bot(page, config)
            app_id = None  # force re-extract from URL in phase 3

        app_id, app_secret = await phase3_get_credentials(page, config, app_id)
        result["app_id"] = app_id
        result["app_secret"] = app_secret

        await phase4_import_permissions(page, config, app_id, permissions_json)
        await phase5_event_subscription(page, config, app_id)
        await phase6_publish_version(page, config, app_id, app_secret)

        result["success"] = True
    finally:
        await browser.close()
        await playwright.stop()

    return result


# ──────────────────────────── CLI & main ──────────────────────────────────

@dataclass
class WorkflowConfig:
    app_name: str
    resume_app_id: str | None
    cdp_url: str
    permissions_file: Path
    app_description: str
    event_name: str
    version: str
    version_notes: str


def parse_args() -> WorkflowConfig:
    parser = argparse.ArgumentParser(
        description="Create and publish a Feishu custom app through a live Chrome session. "
                    "V25 Fast: speed-optimized with concurrent verification."
    )
    parser.add_argument("app_name", help="App name to create.")
    parser.add_argument(
        "resume_app_id", nargs="?",
        help="Optional existing app id (cli_xxx). If provided, Phase 1-2 are skipped."
    )
    parser.add_argument(
        "--cdp-url",
        default=os.environ.get("FEISHU_CDP_URL") or "http://localhost:9222",
        help="Chrome DevTools endpoint. Default: http://localhost:9222"
    )
    parser.add_argument(
        "--permissions-file",
        default=os.environ.get(
            "FEISHU_PERMISSIONS_FILE",
            str(Path(__file__).resolve().parent.parent / "references" / "permissions-json.md")
        ),
        help="Path to permissions JSON or markdown-wrapped JSON."
    )
    parser.add_argument(
        "--description",
        default=os.environ.get("FEISHU_APP_DESCRIPTION", "Created by Codex"),
        help="App description."
    )
    parser.add_argument(
        "--event-name",
        default=os.environ.get("FEISHU_EVENT_NAME", "im.message.receive_v1"),
        help="Event to subscribe. Default: im.message.receive_v1"
    )
    parser.add_argument(
        "--version",
        default=os.environ.get("FEISHU_VERSION", "1.0.0"),
        help="Version number. Default: 1.0.0"
    )
    parser.add_argument(
        "--version-notes",
        default=os.environ.get(
            "FEISHU_VERSION_NOTES",
            "Initial release — bot, permissions, event subscription, and version publish."
        ),
        help="Release notes."
    )

    args = parser.parse_args()
    return WorkflowConfig(
        app_name=args.app_name,
        resume_app_id=args.resume_app_id,
        cdp_url=args.cdp_url,
        permissions_file=Path(args.permissions_file).expanduser(),
        app_description=args.description,
        event_name=args.event_name,
        version=args.version,
        version_notes=args.version_notes,
    )


async def async_main():
    global _t0, _t
    config = parse_args()
    _t0 = _t = time.time()

    print(f"[START] Feishu workflow V25 Fast for: {config.app_name}")
    print(f"  CDP URL:    {config.cdp_url}")
    print(f"  Console:    https://open.feishu.cn/app?lang=zh-CN")
    print(f"  Permissions: {config.permissions_file}")
    print(f"  Event:      {config.event_name}")
    print(f"  Version:    {config.version}")
    print()

    try:
        result = await run_workflow(config)
    except Exception as exc:
        print("\n" + "=" * 55)
        print("[FAIL] Feishu app workflow failed")
        print(f"Reason: {exc}")
        print("=" * 55)
        raise

    print("\n" + "=" * 55)
    print("[OK] Feishu app workflow completed")
    print(f"App Name:   {result['app_name']}")
    print(f"App ID:     {result['app_id']}")
    print(f"App Secret: {mask_secret(result['app_secret'])}")
    print(f"Event:      {config.event_name}")
    print(f"Version:    {config.version}")
    total = time.time() - _t0
    print(f"\n[TOTAL ELAPSED] {total:.1f}s")
    print("=" * 55)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
