#!/usr/bin/env python3
"""Send StroyLink funnel events to PostHog.

Usage:
  export POSTHOG_PROJECT_KEY=phc_...        # project (public) key, from PostHog project settings
  python3 posthog_log.py event outreach_sent --who "Компания А" --date 2026-11-23 --prop channel=instagram
  python3 posthog_log.py csv ../04-tracker.csv
Add --dry-run (before the sub-command) to print what would be sent without sending anything.

Re-running the same csv is safe: each event gets a deterministic id, so PostHog de-duplicates it.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid

HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com").rstrip("/")

EVENTS = {
    "outreach_sent", "outreach_replied", "meeting_held", "pilot_agreed",
    "homeowner_dm_received", "lead_qualified", "lead_delivered",
    "contract_signed", "commission_received",
}
COMPANY_EVENTS = {"outreach_sent", "outreach_replied", "meeting_held", "pilot_agreed"}

# tracker column -> event
CSV_MAP = [
    ("Дата 1-го сообщения", "outreach_sent"),
    ("Дата ответа", "outreach_replied"),
    ("Дата встречи", "meeting_held"),
    ("Дата согласия на пилот", "pilot_agreed"),
]


def slug(text):
    return re.sub(r"[\W_]+", "-", text.strip().lower()).strip("-")


def parse_date(text):
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return dt.datetime.strptime(text, fmt).replace(hour=9, tzinfo=dt.timezone.utc)
        except ValueError:
            pass
    raise ValueError(f"unknown date format: {text!r} (use YYYY-MM-DD or DD.MM.YYYY)")


def make_event(name, who, when, props):
    if name not in EVENTS:
        raise ValueError(f"unknown event {name!r}; allowed: {', '.join(sorted(EVENTS))}")
    prefix = "company:" if name in COMPANY_EVENTS else "lead:"
    distinct_id = prefix + slug(who)
    ts = when.isoformat()
    return {
        "event": name,
        "distinct_id": distinct_id,
        "timestamp": ts,
        "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{distinct_id}|{name}|{ts}")),
        "properties": {"name": who, **props},
    }


def send(events, dry_run):
    if dry_run:
        print(json.dumps(events, ensure_ascii=False, indent=2))
        print(f"[dry-run] {len(events)} event(s) NOT sent", file=sys.stderr)
        return
    key = os.environ.get("POSTHOG_PROJECT_KEY")
    if not key:
        sys.exit("Set POSTHOG_PROJECT_KEY first (PostHog project key, starts with phc_).")
    body = json.dumps({"api_key": key, "batch": events}).encode("utf-8")
    req = urllib.request.Request(HOST + "/batch/", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"sent {len(events)} event(s): HTTP {resp.status}")
    except urllib.error.HTTPError as err:
        sys.exit(f"PostHog rejected the request: HTTP {err.code} {err.read()[:200]!r}")


def cmd_event(args):
    props = {}
    for item in args.prop or []:
        k, _, v = item.partition("=")
        props[k] = float(v) if re.fullmatch(r"-?\d+(\.\d+)?", v) else v
    when = parse_date(args.date) if args.date else dt.datetime.now(dt.timezone.utc)
    send([make_event(args.name, args.who, when, props)], args.dry_run)


def cmd_csv(args):
    events = []
    with open(args.path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            company = (row.get("Компания") or "").strip()
            if not company:
                continue
            props = {}
            segment = (row.get("Сегмент (ремонт квартир/дома)") or "").strip()
            if segment:
                props["segment"] = segment
            for column, event in CSV_MAP:
                value = (row.get(column) or "").strip()
                if value:
                    events.append(make_event(event, company, parse_date(value), props))
    if not events:
        sys.exit("No dated rows found in the csv: nothing to send.")
    send(events, args.dry_run)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print events, send nothing")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_event = sub.add_parser("event", help="send one event")
    p_event.add_argument("name")
    p_event.add_argument("--who", required=True, help="company or lead name")
    p_event.add_argument("--date", help="YYYY-MM-DD or DD.MM.YYYY (default: now)")
    p_event.add_argument("--prop", action="append", help="extra property, key=value (repeatable)")
    p_event.set_defaults(func=cmd_event)
    p_csv = sub.add_parser("csv", help="send events from the tracker csv")
    p_csv.add_argument("path")
    p_csv.set_defaults(func=cmd_csv)
    args = parser.parse_args()
    try:
        args.func(args)
    except ValueError as err:
        sys.exit(str(err))


if __name__ == "__main__":
    main()
