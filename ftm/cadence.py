"""Decide whether this workflow firing should do work. Workflow fires at :07 and :37 each hour.

hourly (default) -> :07 firings only
Oct 15 - Nov 3   -> both firings (every 30 min)
after Nov 3      -> the :07 firing at daily_hour_utc only
after freeze     -> nothing (tracker stands as a record)
Manual runs (workflow_dispatch) always run.
Prints run=true/false to $GITHUB_OUTPUT.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SLOT_HALF = "37 * * * *"


def should_run(now: datetime, schedule_expr: str | None, sch: dict) -> bool:
    if not schedule_expr:  # manual or push
        return True
    d = now.date().isoformat()
    half = schedule_expr.strip() == SLOT_HALF
    if d > sch["freeze_after"]:
        return False
    if d >= sch["daily_from"]:
        return not half and now.hour == sch["daily_hour_utc"]
    if sch["half_hourly_from"] <= d <= sch["half_hourly_until"]:
        return True
    return not half


if __name__ == "__main__":
    sch = json.loads((Path(__file__).parent / "config.json").read_text())["schedule"]
    run = should_run(datetime.now(timezone.utc), os.environ.get("SCHEDULE") or None, sch)
    print(f"run={'true' if run else 'false'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"run={'true' if run else 'false'}\n")
    sys.exit(0)
