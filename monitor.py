"""
Kedarnath Helicopter Booking Monitor
Polls the IRCTC helicopter portal and alerts via ALL channels when bookings go live.

Notification channels:
  1. macOS notification + sound (always on)
  2. iMessage via Messages.app (free — needs phone number in config)
  3. ntfy.sh push notification (free — install ntfy app on phone, subscribe to topic)
  4. Email via Gmail SMTP (free — needs App Password)
  5. Slack DM via webhook (written to trigger file, picked up by Claude Code)

Smart interval:
  - Before April 10: relaxed (30 min) — just watching
  - April 10 onwards: aggressive (5 min) — bookings could drop any time
  - On "coming soon" detection: auto-switches to aggressive

Usage:
  python monitor.py                # Auto-selects interval based on date
  python monitor.py --aggressive   # Force 5-min checks immediately
  python monitor.py --interval 60  # Custom interval in seconds
  python monitor.py --test-notify  # Test all notification channels
"""

import argparse
import json
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "monitor_log.txt"
STATE_PATH = BASE_DIR / "monitor_state.json"
SLACK_TRIGGER_PATH = BASE_DIR / "slack_trigger.json"

AGGRESSIVE_DATE = date(2026, 3, 26)
RELAXED_INTERVAL = 1800   # 30 minutes
AGGRESSIVE_INTERVAL = 300  # 5 minutes


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    with open(LOG_PATH, "a") as f:
        f.write(line)
    print(f"  {message}")


def get_interval(force_aggressive: bool, custom_interval: int | None) -> int:
    if custom_interval:
        return custom_interval
    if force_aggressive or date.today() >= AGGRESSIVE_DATE:
        return AGGRESSIVE_INTERVAL
    return RELAXED_INTERVAL


def load_state() -> dict:
    """Load persisted state (survives restarts)."""
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"last_status": None, "notified_coming_soon": False, "notified_live": False}


def save_state(state: dict):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)


# ════════════════════════════════════════════════════════════
# NOTIFICATION CHANNELS
# ════════════════════════════════════════════════════════════

def notify_macos(title: str, message: str):
    """macOS notification center + sound."""
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "{title}" sound name "Glass"'
        ], check=False, timeout=5)
        print("\a" * 3)
        log("Notified: macOS")
    except Exception as e:
        log(f"macOS notification failed: {e}")


def notify_imessage(phone: str, message: str):
    """Send iMessage via Messages.app (free, macOS only)."""
    if not phone or phone == "YOUR_PHONE_NUMBER":
        return

    applescript = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{phone}" of targetService
        send "{message}" to targetBuddy
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", applescript], check=True, timeout=10)
        log(f"Notified: iMessage to {phone}")
    except Exception as e:
        log(f"iMessage failed: {e}")


def notify_ntfy(topic: str, title: str, message: str):
    """Push notification via ntfy.sh (free, no signup)."""
    if not topic:
        return

    try:
        # Sanitize to ASCII-safe text (ntfy headers must be latin-1 compatible)
        safe_title = title.encode("ascii", "replace").decode("ascii")
        data = message.encode("utf-8")
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=data,
            headers={
                "Title": safe_title,
                "Priority": "urgent",
                "Tags": "helicopter",
            },
            method="POST",
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        urllib.request.urlopen(req, timeout=10, context=ctx)
        log(f"Notified: ntfy.sh/{topic}")
    except Exception as e:
        log(f"ntfy.sh failed: {e}")


def notify_email(to_email: str, subject: str, body: str, config: dict):
    """Send email via Gmail SMTP (free, needs App Password)."""
    gmail_user = config.get("notifications", {}).get("gmail_sender", to_email)
    gmail_app_password = config.get("notifications", {}).get("gmail_app_password", "")

    if not gmail_app_password or gmail_app_password == "YOUR_APP_PASSWORD":
        log("Email skipped: no Gmail App Password configured")
        return

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, to_email, msg.as_string())
        log(f"Notified: Email to {to_email}")
    except Exception as e:
        log(f"Email failed: {e}")


def notify_slack_trigger(user_id: str, message: str):
    """Write a trigger file for Claude Code to pick up and send Slack DM."""
    if not user_id:
        return

    trigger = {
        "timestamp": datetime.now().isoformat(),
        "channel": user_id,
        "message": message,
        "sent": False,
    }
    try:
        with open(SLACK_TRIGGER_PATH, "w") as f:
            json.dump(trigger, f, indent=2)
        log(f"Notified: Slack trigger written for {user_id}")
    except Exception as e:
        log(f"Slack trigger failed: {e}")


def send_all_notifications(title: str, message: str, config: dict):
    """Fire ALL notification channels."""
    notif = config.get("notifications", {})

    email_body = f"""
    <h2>{title}</h2>
    <p>{message}</p>
    <p><strong>Portal:</strong> <a href="{config['portal']['url']}">{config['portal']['url']}</a></p>
    <p><strong>Route:</strong> {config['booking']['route']}</p>
    <p><strong>Date:</strong> {config['booking']['travel_date']}</p>
    <p><br>Run <code>cd personal/kedarnath-booking && .venv/bin/python sniper.py</code> to start the booking bot!</p>
    <p>Har Har Mahadev!</p>
    """

    full_msg = f"{message}\n\nPortal: {config['portal']['url']}\nRoute: {config['booking']['route']}\nDate: {config['booking']['travel_date']}\n\nRun sniper.py NOW!"

    # Fire all channels (don't let one failure block others)
    notify_macos(title, message)
    notify_imessage(notif.get("imessage_phone", ""), full_msg)
    notify_ntfy(notif.get("ntfy_topic", ""), title, full_msg)
    notify_email(notif.get("email", ""), f"KEDARNATH BOOKING: {title}", email_body, config)
    notify_slack_trigger(notif.get("slack_user_id", ""), full_msg)


# ════════════════════════════════════════════════════════════
# PORTAL CHECKER
# ════════════════════════════════════════════════════════════

def check_single_url(url: str, p) -> tuple[str, str]:
    """
    Check a single URL and return (status, page_text).
    Status: "live", "coming_soon", "down", "unknown", "error"
    """
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        page_text = page.inner_text("body").lower()
        page_html = page.content().lower()

        booking_live_indicators = [
            "select date", "available seats", "phata",
            "select route", "check availability",
            "passenger details", "choose helipad",
            "select helipad", "proceed to book",
            "available slots", "booking open",
        ]

        coming_soon_indicators = [
            "booking is currently closed", "booking will start soon",
            "coming soon", "will be available", "booking not started",
            "opening soon", "will be notified",
            "you will be notified as soon as it reopens",
        ]

        maintenance_indicators = [
            "under maintenance", "temporarily unavailable",
            "server error", "502 bad gateway", "503 service",
            "404 not found",
        ]

        # Save screenshot (use URL-based filename)
        safe_name = url.replace("https://", "").replace("/", "_").rstrip("_")
        screenshot_path = BASE_DIR / f"check_{safe_name}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)

        is_live = any(ind in page_text for ind in booking_live_indicators)
        is_coming_soon = any(ind in page_text for ind in coming_soon_indicators)
        is_maintenance = any(ind in page_text or ind in page_html for ind in maintenance_indicators)

        if is_maintenance:
            return "down", page_text[:3000]
        elif is_live and not is_coming_soon:
            return "live", page_text[:3000]
        elif is_coming_soon:
            return "coming_soon", page_text[:3000]
        else:
            return "unknown", page_text[:3000]

    except PlaywrightTimeout:
        return "down", ""
    except Exception as e:
        return "error", str(e)
    finally:
        browser.close()


# URLs to monitor (IRCTC official + Uttarakhand govt portal)
PORTAL_URLS = [
    "https://www.heliyatra.irctc.co.in",
    "https://heliservices.uk.gov.in",
]


def check_availability(config: dict) -> str:
    """
    Checks BOTH the IRCTC and Uttarakhand govt helicopter portals.
    Returns best status: "live" > "coming_soon" > "unknown" > "down" > "error"
    """
    target_date = config["booking"]["travel_date"]
    primary_url = config["portal"]["url"]

    # Always check primary URL first, then secondary portals
    urls_to_check = [primary_url] + [u for u in PORTAL_URLS if u != primary_url]

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking {len(urls_to_check)} portal(s)...")

    best_status = "error"
    status_priority = {"live": 5, "coming_soon": 4, "unknown": 3, "down": 2, "error": 1}
    all_text = []

    with sync_playwright() as p:
        for url in urls_to_check:
            print(f"  Checking {url}...")
            status, page_text = check_single_url(url, p)
            log(f"  {url} → {status.upper()}")
            all_text.append(f"=== {url} ===\n{page_text}")

            if status_priority.get(status, 0) > status_priority.get(best_status, 0):
                best_status = status

    # Save combined debug text
    debug_path = BASE_DIR / "latest_page_text.txt"
    with open(debug_path, "w") as f:
        f.write(f"Date: {datetime.now().isoformat()}\n\n")
        f.write("\n\n".join(all_text))

    log(f"Overall status: {best_status.upper()}")
    return best_status


# ════════════════════════════════════════════════════════════
# MAIN LOOP
# ════════════════════════════════════════════════════════════

def test_notifications(config: dict):
    """Test all notification channels."""
    print("\nTesting all notification channels...\n")
    send_all_notifications(
        "TEST - Kedarnath Monitor",
        "This is a test notification. All channels are working!",
        config,
    )
    print("\nDone! Check your phone, email, and Slack.\n")


def main():
    parser = argparse.ArgumentParser(description="Kedarnath Helicopter Booking Monitor")
    parser.add_argument("--aggressive", action="store_true",
                        help="Force 5-min checks regardless of date")
    parser.add_argument("--interval", type=int, default=None,
                        help="Custom check interval in seconds")
    parser.add_argument("--test-notify", action="store_true",
                        help="Test all notification channels and exit")
    args = parser.parse_args()

    config = load_config()

    if args.test_notify:
        test_notifications(config)
        return

    target = config["booking"]["travel_date"]
    route = config["booking"]["route"]
    interval = get_interval(args.aggressive, args.interval)
    mode = "AGGRESSIVE" if interval <= AGGRESSIVE_INTERVAL else "RELAXED"

    print(f"{'='*60}")
    print(f"  KEDARNATH HELICOPTER BOOKING MONITOR")
    print(f"  Route: {route} | Date: {target} (return)")
    print(f"  Mode: {mode} — checking every {interval // 60}m {interval % 60}s")
    if not args.aggressive and not args.interval:
        print(f"  Auto-aggressive after: {AGGRESSIVE_DATE}")
    print(f"  Notifications: macOS, iMessage, ntfy.sh, Email, Slack")
    print(f"  Log: {LOG_PATH}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*60}\n")

    log(f"Monitor STARTED | Route: {route} | Date: {target} | Interval: {interval}s")

    state = load_state()
    check_count = 0
    last_status = state.get("last_status")
    consecutive_errors = 0

    if last_status:
        log(f"Resumed with last known status: {last_status}")

    while True:
        interval = get_interval(args.aggressive, args.interval)
        check_count += 1
        print(f"--- Check #{check_count} ({datetime.now().strftime('%b %d, %H:%M')}) ---")

        try:
            status = check_availability(config)
            consecutive_errors = 0

            if status == "live" and not state.get("notified_live"):
                send_all_notifications(
                    "BOOKINGS ARE LIVE!",
                    "Kedarnath helicopter bookings are OPEN! Run sniper.py IMMEDIATELY!",
                    config,
                )
                state["notified_live"] = True
                save_state(state)
                # Keep hammering notifications every 2 min until stopped
                while True:
                    time.sleep(120)
                    send_all_notifications(
                        "STILL LIVE - BOOK NOW!",
                        "Kedarnath bookings still open. GO GO GO!",
                        config,
                    )

            elif status == "coming_soon" and not state.get("notified_coming_soon"):
                send_all_notifications(
                    "Portal is UP - Bookings Imminent!",
                    "IRCTC helicopter portal is live but bookings not open yet. Could drop any day. Stay ready!",
                    config,
                )
                state["notified_coming_soon"] = True
                interval = AGGRESSIVE_INTERVAL
                log(f"Auto-switched to AGGRESSIVE ({interval}s)")

            elif status == "unknown" and last_status != "unknown":
                send_all_notifications(
                    "Portal State Changed",
                    "IRCTC helicopter portal is in an unknown state. Check the screenshot manually.",
                    config,
                )

            last_status = status
            state["last_status"] = status
            save_state(state)

        except KeyboardInterrupt:
            log("Monitor STOPPED by user")
            print("\nMonitor stopped. Har Har Mahadev!")
            sys.exit(0)
        except Exception as e:
            consecutive_errors += 1
            log(f"Loop error #{consecutive_errors}: {e}")
            if consecutive_errors >= 5:
                send_all_notifications(
                    "Monitor Error - Check It!",
                    f"Kedarnath monitor has failed {consecutive_errors} times in a row. Last error: {e}",
                    config,
                )
                consecutive_errors = 0

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log("Monitor STOPPED by user")
            print("\nMonitor stopped. Har Har Mahadev!")
            sys.exit(0)


if __name__ == "__main__":
    main()
