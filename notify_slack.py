"""
Slack Notification Sender for Kedarnath Monitor
Reads the trigger file written by monitor.py and sends a Slack DM.

This runs as a separate Claude Code scheduled check OR can be invoked manually.
The monitor.py writes slack_trigger.json when bookings go live.

For standalone use (with webhook):
  python notify_slack.py --webhook "https://hooks.slack.com/services/XXX/YYY/ZZZ"
  python notify_slack.py --test
"""

import argparse
import json
import urllib.request
from pathlib import Path

TRIGGER_PATH = Path(__file__).parent / "slack_trigger.json"


def send_via_webhook(webhook_url: str, message: str):
    """Send Slack message via incoming webhook."""
    payload = json.dumps({
        "text": message,
        "unfurl_links": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=10)
    print(f"Slack webhook sent: {resp.status}")


def check_and_send(webhook_url: str):
    """Check trigger file and send if unsent."""
    if not TRIGGER_PATH.exists():
        print("No trigger file found.")
        return False

    with open(TRIGGER_PATH) as f:
        trigger = json.load(f)

    if trigger.get("sent"):
        print("Trigger already sent.")
        return False

    send_via_webhook(webhook_url, trigger["message"])

    trigger["sent"] = True
    with open(TRIGGER_PATH, "w") as f:
        json.dump(trigger, f, indent=2)

    print("Slack notification sent!")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook", help="Slack incoming webhook URL")
    parser.add_argument("--test", action="store_true", help="Send a test message")
    args = parser.parse_args()

    if not args.webhook:
        print("No webhook URL provided. Use --webhook URL")
        print("To set up: Slack > Apps > Incoming Webhooks > Add to channel")
        return

    if args.test:
        send_via_webhook(args.webhook, "Test from Kedarnath Monitor — notifications are working!")
    else:
        check_and_send(args.webhook)


if __name__ == "__main__":
    main()
