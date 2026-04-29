# Kedarnath Booking

**Automated helicopter booking monitor and sniper for IRCTC Heli Yatra.**

Helicopter slots for Kedarnath sell out within seconds of going live on IRCTC's portal. This tool monitors the booking page around the clock, alerts you the moment slots open, and automates the booking flow at maximum speed -- giving your family the best shot at securing seats.

Built for a 7-person family pilgrimage trip to Kedarnath.

## Components

### Monitor (`monitor.py`)

Polls the IRCTC helicopter portal at configurable intervals with a smart scheduling system:

- **Relaxed mode** (before target date): checks every 30 minutes
- **Aggressive mode** (near target date): checks every 5 minutes
- **Auto-escalation**: switches to aggressive when "coming soon" text is detected

Notifications fire through 5 redundant channels:

| Channel | Requirement |
|---|---|
| macOS Notification | Built-in (always on) |
| iMessage | Phone number in config |
| ntfy.sh Push | ntfy app installed, subscribed to topic |
| Email | Gmail App Password |
| Slack | Webhook URL (picked up by Claude Code) |

### Sniper (`sniper.py`)

Automates the booking flow once slots go live:

1. Launches a visible browser -- you log in manually (CAPTCHA + OTP)
2. Script takes over: selects route, date, slot, preferred operator
3. Fills all passenger details at maximum speed
4. Submits both bookings (split across max-passenger limits) back-to-back
5. You complete payment manually

### Scheduler

Runs as a macOS launchd service (`com.sarthak.kedarnath-monitor.plist`) for persistent background monitoring.

## Configuration

All settings live in `config.json`:

- **Booking preferences**: route (Phata-Kedarnath), travel date, trip type, preferred time slots, fallback dates and helipads
- **Passengers**: names and registration numbers split across two bookings
- **Notification channels**: phone number, email, ntfy topic, Slack webhook

## Tech Stack

| Component | Technology |
|---|---|
| Browser Automation | Playwright |
| Notifications | macOS native, iMessage, ntfy.sh, Gmail SMTP, Slack |
| Scheduling | macOS launchd |
| Language | Python 3 |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Edit config.json with your passenger details and notification preferences

# Test notifications
python monitor.py --test-notify

# Start monitoring (auto-selects interval based on date)
python monitor.py

# Force aggressive monitoring
python monitor.py --aggressive

# Run the sniper when slots are live
python sniper.py

# Reuse an existing browser session
python sniper.py --skip-login
```

## Scheduling with launchd

```bash
# Install the launch agent
cp com.sarthak.kedarnath-monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.sarthak.kedarnath-monitor.plist

# Check status
launchctl list | grep kedarnath

# View logs
tail -f monitor_log.txt
```

---

Built with [Claude Code](https://claude.ai/code)
