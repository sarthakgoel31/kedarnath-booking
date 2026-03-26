"""
Kedarnath Helicopter Booking Sniper
Automates the booking flow on IRCTC's helicopter portal using Playwright.

Strategy:
  1. Launch visible browser — you log in manually (solve CAPTCHA + OTP)
  2. Script takes over: selects route, date, slot, fills passengers at max speed
  3. Submits both bookings (4+3 split) back-to-back
  4. You complete payment manually

Usage:
  python sniper.py              # Full flow: login → book
  python sniper.py --skip-login # Reuse existing session (if already logged in)

IMPORTANT: Fill in config.json with all 7 passengers' real details before running.
"""

import argparse
import json
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout


CONFIG_PATH = Path(__file__).parent / "config.json"
SESSION_DIR = Path(__file__).parent / "browser_session"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    # Validate passengers are filled in
    for booking_key in ["booking_1", "booking_2"]:
        for i, p in enumerate(config["passengers"][booking_key]):
            if p["name"] == "FULL NAME AS ON AADHAAR" or p["age"] == 0:
                print(f"❌ ERROR: Passenger {i+1} in {booking_key} not filled in config.json")
                print("   Fill in ALL passenger details before running the sniper.")
                sys.exit(1)

    return config


def alert(message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"\n  🔔 [{timestamp}] {message}")
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "Kedarnath Sniper" sound name "Glass"'
        ], check=False)
    except Exception:
        pass
    print("\a")


def wait_for_manual_login(page: Page):
    """Wait for user to complete manual login (CAPTCHA + OTP)."""
    print("\n" + "=" * 60)
    print("  MANUAL STEP: Please log in to the portal")
    print("  1. Enter your email/mobile and password")
    print("  2. Solve the CAPTCHA")
    print("  3. Enter the OTP sent to your phone")
    print("  4. Once you see the dashboard/booking page, come back here")
    print("=" * 60)

    alert("Login required — switch to browser window")

    # Wait until URL changes away from login page, or dashboard elements appear
    while True:
        try:
            current_url = page.url.lower()
            page_text = page.inner_text("body").lower()

            # Check for post-login indicators
            logged_in_indicators = [
                "welcome",
                "dashboard",
                "book helicopter",
                "my booking",
                "select route",
                "logout",
                "log out",
            ]

            if any(ind in page_text for ind in logged_in_indicators):
                print("\n  ✅ Login detected! Taking over...\n")
                alert("Login successful — bot taking over!")
                time.sleep(1)
                return

            # Also check if URL changed to a dashboard/booking page
            if "login" not in current_url and "register" not in current_url:
                if any(ind in page_text for ind in logged_in_indicators):
                    print("\n  ✅ Login detected via URL change! Taking over...\n")
                    return

        except Exception:
            pass

        time.sleep(2)


def select_route_and_date(page: Page, config: dict):
    """Navigate to booking page and select route + date + slot."""
    route = config["booking"]["route"]
    target_date = config["booking"]["travel_date"]
    preferred_slots = config["booking"]["preferred_slots"]

    print(f"  Selecting route: {route}")
    print(f"  Target date: {target_date}")
    print(f"  Preferred slots: {', '.join(preferred_slots)}")

    # Strategy: Try to find and interact with route/date selectors
    # The exact selectors depend on the portal's current HTML structure.
    # We use multiple strategies to be resilient to minor UI changes.

    # --- ROUTE SELECTION ---
    route_strategies = [
        # Strategy 1: Dropdown/select with route names
        lambda: try_select_by_text(page, "select", route),
        # Strategy 2: Radio button or clickable card
        lambda: try_click_by_text(page, route.split("-")[0]),  # "Phata"
        # Strategy 3: Any link/button containing route text
        lambda: page.click(f"text=/{route.split('-')[0]}/i", timeout=5000),
    ]

    route_selected = False
    for i, strategy in enumerate(route_strategies):
        try:
            strategy()
            print(f"  ✅ Route selected (strategy {i+1})")
            route_selected = True
            break
        except Exception:
            continue

    if not route_selected:
        print("  ⚠️  Could not auto-select route. Please select manually in the browser.")
        alert("Select route manually, then press Enter here")
        input("  Press Enter after selecting route...")

    time.sleep(1)

    # --- DATE SELECTION ---
    # Parse target date
    year, month, day = target_date.split("-")
    day_int = int(day)  # 12

    date_strategies = [
        # Strategy 1: Date input field
        lambda: fill_date_input(page, target_date),
        # Strategy 2: Calendar picker — click the day number
        lambda: click_calendar_date(page, day_int, int(month), int(year)),
        # Strategy 3: Direct text click
        lambda: page.click(f"text=/^{day_int}$/", timeout=5000),
    ]

    date_selected = False
    for i, strategy in enumerate(date_strategies):
        try:
            strategy()
            print(f"  ✅ Date selected: May {day_int} (strategy {i+1})")
            date_selected = True
            break
        except Exception:
            continue

    if not date_selected:
        print("  ⚠️  Could not auto-select date. Please select manually.")
        alert("Select date May 12 manually, then press Enter here")
        input("  Press Enter after selecting date...")

    time.sleep(1)

    # --- SLOT SELECTION ---
    # Try preferred slots in order
    slot_selected = False
    for slot_time in preferred_slots:
        try:
            page.click(f"text=/{slot_time}/", timeout=3000)
            print(f"  ✅ Slot selected: {slot_time}")
            slot_selected = True
            break
        except Exception:
            continue

    if not slot_selected:
        # Click any available slot
        try:
            page.click("text=/available/i", timeout=3000)
            print("  ✅ Selected first available slot")
            slot_selected = True
        except Exception:
            print("  ⚠️  Could not auto-select slot. Please select manually.")
            alert("Select a time slot manually, then press Enter here")
            input("  Press Enter after selecting slot...")


def try_select_by_text(page: Page, selector_type: str, text: str):
    """Try to select an option in a <select> dropdown by visible text."""
    selects = page.query_selector_all(selector_type)
    for select in selects:
        options = select.query_selector_all("option")
        for option in options:
            if text.lower() in (option.inner_text() or "").lower():
                select.select_option(label=option.inner_text())
                return
    raise Exception("No matching select option found")


def try_click_by_text(page: Page, text: str):
    """Click first element containing the text."""
    page.click(f"text=/{text}/i", timeout=5000)


def fill_date_input(page: Page, date_str: str):
    """Fill a date input field."""
    date_inputs = page.query_selector_all('input[type="date"]')
    if date_inputs:
        date_inputs[0].fill(date_str)
        return
    # Try text inputs that might accept dates
    inputs = page.query_selector_all('input[placeholder*="date" i], input[name*="date" i]')
    if inputs:
        inputs[0].fill(date_str)
        return
    raise Exception("No date input found")


def click_calendar_date(page: Page, day: int, month: int, year: int):
    """Navigate a calendar widget to the right month and click the day."""
    # Try to navigate to the correct month first
    month_names = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    target_month = month_names[month]

    # Click next arrows until we reach the target month
    for _ in range(12):
        try:
            cal_header = page.inner_text(".calendar-header, .datepicker-header, .ui-datepicker-title")
            if target_month.lower() in cal_header.lower() and str(year) in cal_header:
                break
        except Exception:
            break
        try:
            page.click(".next, .datepicker-next, .ui-datepicker-next", timeout=2000)
            time.sleep(0.3)
        except Exception:
            break

    # Click the day
    # Look for day cells that exactly match our target day
    day_cells = page.query_selector_all("td a, td span, .day, .datepicker-day")
    for cell in day_cells:
        text = (cell.inner_text() or "").strip()
        if text == str(day):
            cell.click()
            return

    raise Exception(f"Could not find day {day} in calendar")


def fill_passengers(page: Page, passengers: list[dict]):
    """Fill in passenger details as fast as possible."""
    print(f"\n  Filling {len(passengers)} passenger(s)...")

    for i, pax in enumerate(passengers):
        print(f"    Passenger {i+1}: {pax['name']} ({pax['age']}y, {pax['weight_kg']}kg)")

        # Find input fields for this passenger
        # Common patterns: indexed fields (name_1, name_2) or repeated form groups
        strategies = [
            lambda p=pax, idx=i: fill_passenger_indexed(page, p, idx),
            lambda p=pax, idx=i: fill_passenger_nth_group(page, p, idx),
        ]

        filled = False
        for strategy in strategies:
            try:
                strategy()
                filled = True
                break
            except Exception:
                continue

        if not filled:
            print(f"    ⚠️  Could not auto-fill passenger {i+1}. Fill manually.")
            alert(f"Fill passenger {i+1} ({pax['name']}) manually")
            input(f"    Press Enter after filling passenger {i+1}...")

    print(f"  ✅ All {len(passengers)} passengers filled!")


def fill_passenger_indexed(page: Page, pax: dict, index: int):
    """Fill passenger details using indexed field names (name_0, age_0, etc.)."""
    idx = index
    suffixes = [str(idx), str(idx + 1), f"_{idx}", f"_{idx+1}", f"[{idx}]", f"[{idx+1}]"]

    name_filled = False
    for suffix in suffixes:
        # Try name fields
        name_selectors = [
            f'input[name*="name{suffix}"]',
            f'input[name*="Name{suffix}"]',
            f'input[name*="passenger{suffix}"]',
            f'input[id*="name{suffix}"]',
        ]
        for sel in name_selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    el.fill(pax["name"])
                    name_filled = True
                    break
            except Exception:
                continue
        if name_filled:
            break

    if not name_filled:
        raise Exception("Could not find name field")

    # Fill age
    for suffix in suffixes:
        age_selectors = [f'input[name*="age{suffix}"]', f'input[id*="age{suffix}"]']
        for sel in age_selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    el.fill(str(pax["age"]))
                    break
            except Exception:
                continue

    # Fill weight
    for suffix in suffixes:
        weight_selectors = [f'input[name*="weight{suffix}"]', f'input[id*="weight{suffix}"]']
        for sel in weight_selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    el.fill(str(pax["weight_kg"]))
                    break
            except Exception:
                continue

    # Fill gender
    for suffix in suffixes:
        try:
            gender_selectors = [f'select[name*="gender{suffix}"]', f'select[id*="gender{suffix}"]']
            for sel in gender_selectors:
                el = page.query_selector(sel)
                if el:
                    el.select_option(label=pax["gender"])
                    break
        except Exception:
            continue

    # Fill ID number
    for suffix in suffixes:
        id_selectors = [
            f'input[name*="id{suffix}"]', f'input[name*="aadhaar{suffix}"]',
            f'input[name*="aadhar{suffix}"]', f'input[name*="document{suffix}"]',
            f'input[id*="id{suffix}"]',
        ]
        for sel in id_selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    el.fill(pax["id_number"].replace(" ", ""))
                    break
            except Exception:
                continue


def fill_passenger_nth_group(page: Page, pax: dict, index: int):
    """Fill passenger using nth form group (repeated fieldsets)."""
    # Find all passenger form groups
    groups = page.query_selector_all(
        ".passenger-form, .passenger-group, .pax-form, "
        "fieldset, .form-group-passenger, [class*='passenger']"
    )

    if index >= len(groups):
        raise Exception(f"Only {len(groups)} form groups found, need index {index}")

    group = groups[index]

    # Fill fields within this group
    name_input = group.query_selector('input[name*="name" i], input[placeholder*="name" i]')
    if name_input:
        name_input.fill(pax["name"])
    else:
        raise Exception("No name input in group")

    age_input = group.query_selector('input[name*="age" i], input[placeholder*="age" i]')
    if age_input:
        age_input.fill(str(pax["age"]))

    weight_input = group.query_selector('input[name*="weight" i], input[placeholder*="weight" i]')
    if weight_input:
        weight_input.fill(str(pax["weight_kg"]))

    gender_select = group.query_selector('select[name*="gender" i]')
    if gender_select:
        gender_select.select_option(label=pax["gender"])

    id_input = group.query_selector('input[name*="id" i], input[name*="aadhaar" i], input[name*="document" i]')
    if id_input:
        id_input.fill(pax["id_number"].replace(" ", ""))


def submit_booking(page: Page) -> bool:
    """Find and click the submit/book button."""
    submit_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Book")',
        'button:has-text("Submit")',
        'button:has-text("Proceed")',
        'button:has-text("Confirm")',
        'a:has-text("Book Now")',
        'a:has-text("Proceed")',
    ]

    for sel in submit_selectors:
        try:
            page.click(sel, timeout=3000)
            print("  ✅ Booking submitted!")
            return True
        except Exception:
            continue

    print("  ⚠️  Could not find submit button. Click it manually!")
    alert("Click the SUBMIT / BOOK button manually!")
    input("  Press Enter after submitting...")
    return True


def book_one_group(page: Page, config: dict, booking_key: str):
    """Execute one complete booking for a group of passengers."""
    passengers = config["passengers"][booking_key]
    print(f"\n{'='*60}")
    print(f"  BOOKING: {booking_key.upper()} — {len(passengers)} passengers")
    print(f"{'='*60}")

    # Select route, date, slot
    select_route_and_date(page, config)

    # Fill passenger details
    fill_passengers(page, passengers)

    # Submit
    submit_booking(page)

    # Wait for payment page or confirmation
    print("\n  ⏳ Waiting for payment page...")
    alert(f"{booking_key} submitted! Complete payment NOW!")
    print("  💳 COMPLETE PAYMENT IN THE BROWSER")
    input("  Press Enter after payment is done (or if it failed)...")


def run_sniper(skip_login: bool = False):
    config = load_config()

    print("=" * 60)
    print("  KEDARNATH HELICOPTER BOOKING SNIPER")
    print(f"  Route: {config['booking']['route']}")
    print(f"  Date: {config['booking']['travel_date']} (return)")
    print(f"  Passengers: 4 + 3 = 7")
    print("=" * 60)

    with sync_playwright() as p:
        # Use persistent context to maintain session across bookings
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,  # Must be visible for manual CAPTCHA/OTP/payment
            slow_mo=50,  # Slight delay to avoid detection
            viewport={"width": 1280, "height": 800},
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )

        page = context.new_page()

        # Navigate to portal
        url = config["portal"]["url"]
        print(f"\n  Opening {url}...")
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        if not skip_login:
            wait_for_manual_login(page)
        else:
            print("  Skipping login — using existing session")

        # ═══════════════════════════════════════
        # BOOKING 1: 4 passengers
        # ═══════════════════════════════════════
        book_one_group(page, config, "booking_1")

        print("\n  ⏳ Booking 1 done. Moving to Booking 2...")
        time.sleep(2)

        # Navigate back to booking page for second group
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # ═══════════════════════════════════════
        # BOOKING 2: 3 passengers
        # ═══════════════════════════════════════
        book_one_group(page, config, "booking_2")

        # ═══════════════════════════════════════
        # DONE
        # ═══════════════════════════════════════
        print("\n" + "=" * 60)
        print("  🎉 BOTH BOOKINGS COMPLETE!")
        print(f"  {config['booking']['route']} — {config['booking']['travel_date']}")
        print("  Check your email for confirmation tickets.")
        print("=" * 60)

        alert("BOTH BOOKINGS COMPLETE! Har Har Mahadev! 🙏")

        input("\n  Press Enter to close the browser...")
        context.close()


def main():
    parser = argparse.ArgumentParser(description="Kedarnath Helicopter Booking Sniper")
    parser.add_argument("--skip-login", action="store_true",
                        help="Skip login (reuse existing browser session)")
    args = parser.parse_args()

    run_sniper(skip_login=args.skip_login)


if __name__ == "__main__":
    main()
