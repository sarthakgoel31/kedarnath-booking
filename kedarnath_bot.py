"""
Kedarnath Helicopter Booking Bot — Browser Daemon
A long-running browser controller that Claude drives via command/status files.

Architecture:
  - Runs in background with a visible Chromium browser
  - Watches command.json for instructions from Claude
  - Writes status.json after each action
  - Takes screenshots at every step

Commands (written to command.json):
  hammer       — Hit the site every 5-10s until it loads
  fill_login   — Fill login credentials (email + password)
  screenshot   — Take a screenshot of current page
  book         — Run booking flow for a passenger group (params: group=1|2)
  navigate     — Go to a URL (params: url=...)
  page_info    — Dump current page text and URL
  stop         — Close browser and exit

Usage:
  python kedarnath_bot.py          # Launch browser daemon
"""

import json
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
SESSION_DIR = BASE_DIR / "browser_session"
COMMAND_PATH = BASE_DIR / "command.json"
STATUS_PATH = BASE_DIR / "status.json"
LOG_PATH = BASE_DIR / "bot_log.txt"
SCREENSHOT_PATH = BASE_DIR / "bot_screenshot.png"

HAMMER_INTERVAL = 7  # seconds between attempts


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")
    print(line)


def alert(message: str):
    """macOS notification + sound."""
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "Kedarnath Bot" sound name "Glass"'
        ], check=False, timeout=5)
    except Exception:
        pass
    print(f"\a")


def write_status(phase: str, message: str, **extra):
    """Write current status for Claude to read."""
    status = {
        "phase": phase,
        "message": message,
        "timestamp": datetime.now().isoformat(),
        **extra,
    }
    with open(STATUS_PATH, "w") as f:
        json.dump(status, f, indent=2)


def read_command() -> dict | None:
    """Read and consume a command from Claude."""
    if not COMMAND_PATH.exists():
        return None
    try:
        with open(COMMAND_PATH) as f:
            content = f.read().strip()
            if not content:
                return None
            cmd = json.loads(content)
        # Consume: clear the file
        COMMAND_PATH.write_text("")
        return cmd
    except (json.JSONDecodeError, Exception):
        return None


def take_screenshot(page: Page, name: str = "bot_screenshot") -> str:
    """Take screenshot and return the path."""
    path = BASE_DIR / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception as e:
        log(f"Screenshot failed: {e}")
        return ""


def get_page_text(page: Page) -> str:
    """Get page body text safely."""
    try:
        return page.inner_text("body")
    except Exception:
        return ""


# ════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ════════════════════════════════════════════════════════════

def handle_hammer(page: Page, config: dict):
    """Hammer the portal every 5-10s until it loads."""
    url = config["portal"]["url"]
    attempt = 0

    log(f"HAMMER: Starting — hitting {url} every {HAMMER_INTERVAL}s")
    write_status("hammering", f"Hitting {url} every {HAMMER_INTERVAL}s...", attempt=0)

    while True:
        # Check for interrupt command
        cmd = read_command()
        if cmd and cmd.get("action") == "stop":
            write_status("stopped", "Hammer stopped by command")
            return "stopped"

        attempt += 1
        try:
            log(f"HAMMER: Attempt #{attempt}")
            write_status("hammering", f"Attempt #{attempt}...", attempt=attempt)

            page.goto(url, timeout=15000)
            page.wait_for_load_state("domcontentloaded", timeout=10000)

            page_text = page.inner_text("body").lower()

            # Check for error pages
            error_indicators = [
                "this site can't be reached", "err_connection",
                "502 bad gateway", "503 service", "504 gateway",
                "server error", "connection refused", "timed out",
                "took too long to respond",
            ]

            if any(err in page_text for err in error_indicators):
                log(f"HAMMER: Attempt #{attempt} — site error")
                write_status("hammering", f"Attempt #{attempt}: site error, retrying...", attempt=attempt)
                time.sleep(HAMMER_INTERVAL)
                continue

            if len(page_text.strip()) < 50:
                log(f"HAMMER: Attempt #{attempt} — empty page")
                write_status("hammering", f"Attempt #{attempt}: empty page, retrying...", attempt=attempt)
                time.sleep(HAMMER_INTERVAL)
                continue

            # Page loaded!
            screenshot = take_screenshot(page)
            log(f"HAMMER: Portal LOADED on attempt #{attempt}!")
            alert("Portal loaded!")
            write_status("loaded", f"Portal loaded on attempt #{attempt}!",
                        attempt=attempt, screenshot=screenshot,
                        page_url=page.url,
                        page_text_preview=page_text[:500])
            return "loaded"

        except PlaywrightTimeout:
            log(f"HAMMER: Attempt #{attempt} — timeout")
            write_status("hammering", f"Attempt #{attempt}: timeout, retrying...", attempt=attempt)
            time.sleep(HAMMER_INTERVAL)
        except Exception as e:
            log(f"HAMMER: Attempt #{attempt} — error: {e}")
            write_status("hammering", f"Attempt #{attempt}: {str(e)[:80]}, retrying...", attempt=attempt)
            # If page was closed, get a fresh one
            if "closed" in str(e).lower():
                try:
                    page = page.context.new_page()
                except Exception:
                    pass
            time.sleep(HAMMER_INTERVAL)


def handle_fill_login(page: Page, config: dict):
    """Fill login credentials on the current page."""
    mobile = config["portal"]["login_mobile"]
    email = config["portal"]["login_email"]
    password = config["portal"]["login_password"]

    log(f"FILL_LOGIN: Filling credentials...")
    write_status("filling_login", "Looking for login form...")

    try:
        page_text = page.inner_text("body").lower()
        page_html = page.content().lower()

        # Try to find and fill mobile/email field
        login_filled = False

        # Strategy 1: Mobile number field
        mobile_selectors = [
            'input[name*="mobile" i]', 'input[name*="phone" i]',
            'input[type="tel"]', 'input[placeholder*="mobile" i]',
            'input[placeholder*="phone" i]', 'input[id*="mobile" i]',
            'input[id*="phone" i]',
        ]
        for sel in mobile_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(mobile)
                    log(f"FILL_LOGIN: Filled mobile in {sel}")
                    login_filled = True
                    break
            except Exception:
                continue

        # Strategy 2: Email field
        email_selectors = [
            'input[name*="email" i]', 'input[type="email"]',
            'input[placeholder*="email" i]', 'input[id*="email" i]',
            'input[name*="user" i]', 'input[placeholder*="user" i]',
        ]
        for sel in email_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(email)
                    log(f"FILL_LOGIN: Filled email in {sel}")
                    login_filled = True
                    break
            except Exception:
                continue

        # Strategy 3: Generic text input (first visible one)
        if not login_filled:
            inputs = page.query_selector_all('input[type="text"], input:not([type])')
            for inp in inputs:
                try:
                    if inp.is_visible():
                        inp.fill(mobile)
                        log("FILL_LOGIN: Filled mobile in generic text input")
                        login_filled = True
                        break
                except Exception:
                    continue

        # Fill password
        password_filled = False
        password_selectors = [
            'input[type="password"]', 'input[name*="password" i]',
            'input[name*="pass" i]', 'input[placeholder*="password" i]',
        ]
        for sel in password_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(password)
                    log(f"FILL_LOGIN: Filled password in {sel}")
                    password_filled = True
                    break
            except Exception:
                continue

        screenshot = take_screenshot(page)

        if login_filled and password_filled:
            write_status("login_filled", "Login + password filled! Solve CAPTCHA and click Login.",
                        screenshot=screenshot, login_filled=True, password_filled=True)
            alert("Credentials filled! Solve CAPTCHA now!")
        elif login_filled:
            write_status("login_partial", "Login filled but could not find password field.",
                        screenshot=screenshot, login_filled=True, password_filled=False)
            alert("Login filled! Enter password + CAPTCHA manually.")
        else:
            # Dump all visible inputs for debugging
            inputs_info = []
            all_inputs = page.query_selector_all("input")
            for inp in all_inputs[:20]:
                try:
                    inputs_info.append({
                        "type": inp.get_attribute("type"),
                        "name": inp.get_attribute("name"),
                        "id": inp.get_attribute("id"),
                        "placeholder": inp.get_attribute("placeholder"),
                        "visible": inp.is_visible(),
                    })
                except Exception:
                    pass
            write_status("login_failed", "Could not find login form fields.",
                        screenshot=screenshot, inputs_found=inputs_info,
                        page_text_preview=page_text[:500])

    except Exception as e:
        log(f"FILL_LOGIN: Error — {e}")
        write_status("login_error", f"Error: {e}")


def handle_book(page: Page, config: dict, group: int):
    """Run the full booking flow for a passenger group."""
    booking_key = f"booking_{group}"
    passengers = config["passengers"][booking_key]
    route = config["booking"]["route"]
    target_date = config["booking"]["travel_date"]
    preferred_slots = config["booking"]["preferred_slots"]
    url = config["portal"]["url"]

    log(f"BOOK: Starting {booking_key} — {len(passengers)} passengers")
    write_status("booking", f"Starting {booking_key}: {len(passengers)} passengers",
                group=group)

    # Import sniper functions
    from sniper import (select_route_and_date, fill_passengers, submit_booking)

    try:
        # If this is group 2, navigate back to booking page first
        if group == 2:
            log("BOOK: Navigating back to portal for group 2...")
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(1)

        # Select route, date, slot
        log("BOOK: Selecting route, date, slot...")
        write_status("booking", "Selecting route, date, and time slot...", group=group)
        select_route_and_date(page, config)
        take_screenshot(page, "bot_route_selected")

        # Fill passengers
        log(f"BOOK: Filling {len(passengers)} passengers...")
        write_status("booking", f"Filling {len(passengers)} passenger details...", group=group)
        fill_passengers(page, passengers)
        take_screenshot(page, "bot_passengers_filled")

        # Submit
        log("BOOK: Submitting booking...")
        write_status("booking", "Submitting booking form...", group=group)
        submit_booking(page)

        screenshot = take_screenshot(page, "bot_submitted")
        log(f"BOOK: {booking_key} submitted!")
        alert(f"Booking {group} submitted! PAY NOW!")
        write_status("payment_ready", f"Booking {group} submitted! Complete payment in browser.",
                    group=group, screenshot=screenshot)

    except Exception as e:
        screenshot = take_screenshot(page, f"bot_book_error_{group}")
        log(f"BOOK: Error — {e}")
        log(traceback.format_exc())
        write_status("booking_error", f"Booking error: {e}",
                    group=group, screenshot=screenshot,
                    page_text=get_page_text(page)[:1000])


def handle_page_info(page: Page):
    """Dump current page state for Claude to analyze."""
    try:
        url = page.url
        title = page.title()
        text = get_page_text(page)
        screenshot = take_screenshot(page)

        # Get all links
        links = []
        all_links = page.query_selector_all("a")
        for link in all_links[:30]:
            try:
                links.append({
                    "text": (link.inner_text() or "").strip()[:80],
                    "href": link.get_attribute("href"),
                })
            except Exception:
                pass

        # Get all buttons
        buttons = []
        all_buttons = page.query_selector_all("button, input[type='submit'], input[type='button']")
        for btn in all_buttons[:20]:
            try:
                buttons.append({
                    "text": (btn.inner_text() or btn.get_attribute("value") or "").strip()[:80],
                    "type": btn.get_attribute("type"),
                })
            except Exception:
                pass

        write_status("page_info", "Page info captured",
                    url=url, title=title,
                    page_text=text[:2000],
                    links=links, buttons=buttons,
                    screenshot=screenshot)
    except Exception as e:
        write_status("page_info_error", f"Error: {e}")


def handle_navigate(page: Page, url: str):
    """Navigate to a URL."""
    try:
        log(f"NAVIGATE: Going to {url}")
        write_status("navigating", f"Going to {url}...")
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        screenshot = take_screenshot(page)
        write_status("navigated", f"Loaded {url}",
                    url=page.url, screenshot=screenshot,
                    page_text_preview=get_page_text(page)[:500])
    except Exception as e:
        write_status("navigate_error", f"Error navigating: {e}")


def handle_click(page: Page, selector: str):
    """Click an element by selector or text."""
    try:
        log(f"CLICK: {selector}")
        page.click(selector, timeout=5000)
        time.sleep(1)
        screenshot = take_screenshot(page)
        write_status("clicked", f"Clicked: {selector}",
                    screenshot=screenshot,
                    page_url=page.url,
                    page_text_preview=get_page_text(page)[:500])
    except Exception as e:
        write_status("click_error", f"Could not click '{selector}': {e}")


def handle_fill(page: Page, selector: str, value: str):
    """Fill a form field."""
    try:
        log(f"FILL: {selector} = {value}")
        el = page.query_selector(selector)
        if el:
            el.fill(value)
            screenshot = take_screenshot(page)
            write_status("filled", f"Filled {selector}",
                        screenshot=screenshot)
        else:
            write_status("fill_error", f"Element not found: {selector}")
    except Exception as e:
        write_status("fill_error", f"Error filling: {e}")


# ════════════════════════════════════════════════════════════
# MAIN DAEMON LOOP
# ════════════════════════════════════════════════════════════

def main():
    config = load_config()
    url = config["portal"]["url"]

    # Clear old command/status
    COMMAND_PATH.write_text("")

    log("BOT STARTED — launching browser...")
    print(f"\n{'='*60}")
    print(f"  KEDARNATH BOOKING BOT")
    print(f"  Portal: {url}")
    print(f"  Route: {config['booking']['route']}")
    print(f"  Date: {config['booking']['travel_date']}")
    print(f"  Passengers: 4 + 3 = 7")
    print(f"  Waiting for commands via command.json...")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            slow_mo=50,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Reuse existing page if persistent session has one, else create new
        pages = context.pages
        if pages:
            page = pages[0]
        else:
            page = context.new_page()

        def get_page():
            """Get a working page — reuse existing or create new."""
            nonlocal page
            try:
                # Test if page is still alive
                page.url
                return page
            except Exception:
                pass
            # Page was closed — get another
            pages = context.pages
            if pages:
                page = pages[0]
            else:
                page = context.new_page()
            return page

        write_status("ready", "Browser launched. Waiting for commands.")
        log("Browser ready — waiting for commands")
        alert("Kedarnath Bot ready!")

        running = True
        while running:
            try:
                cmd = read_command()
                if not cmd:
                    time.sleep(0.5)
                    continue

                action = cmd.get("action", "")
                log(f"COMMAND: {action} {json.dumps({k:v for k,v in cmd.items() if k != 'action'})}")

                # Always get a live page before any command
                p = get_page()

                if action == "hammer":
                    result = handle_hammer(p, config)

                elif action == "fill_login":
                    handle_fill_login(p, config)

                elif action == "screenshot":
                    screenshot = take_screenshot(p)
                    write_status("screenshot", "Screenshot taken",
                                screenshot=screenshot, url=p.url)

                elif action == "book":
                    group = cmd.get("group", 1)
                    handle_book(p, config, group)

                elif action == "page_info":
                    handle_page_info(p)

                elif action == "navigate":
                    handle_navigate(p, cmd.get("url", url))

                elif action == "click":
                    handle_click(p, cmd.get("selector", ""))

                elif action == "fill":
                    handle_fill(p, cmd.get("selector", ""), cmd.get("value", ""))

                elif action == "reload":
                    p.reload(timeout=15000)
                    screenshot = take_screenshot(p)
                    write_status("reloaded", "Page reloaded",
                                screenshot=screenshot, url=p.url,
                                page_text_preview=get_page_text(p)[:500])

                elif action == "stop":
                    log("BOT STOPPED by command")
                    write_status("stopped", "Bot stopped.")
                    running = False

                else:
                    write_status("unknown_command", f"Unknown action: {action}")

            except KeyboardInterrupt:
                log("BOT STOPPED by Ctrl+C")
                write_status("stopped", "Bot stopped by user.")
                break
            except Exception as e:
                log(f"BOT ERROR: {e}")
                log(traceback.format_exc())
                write_status("error", f"Bot error: {e}")
                time.sleep(1)

        context.close()
        log("Browser closed. Har Har Mahadev!")


if __name__ == "__main__":
    main()
