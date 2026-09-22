"""One run: ingest -> normalize -> dedupe -> attribute -> roll up -> alerts -> checks -> publish.

Exits non-zero on any failed check. Nothing in site/data is touched unless every check passes.
Usage: python -m ftm.run [--offline DIR] [--out site]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from . import core, sources

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
CFG = json.loads((Path(__file__).parent / "config.json").read_text())


class CheckFailed(Exception):
    pass


def log(*a):
    print("[ftm]", *a, flush=True)


# ---------------------------------------------------------------- state helpers

def read_state(name, default):
    p = STATE / name
    if not p.exists():
        return default
    raw = p.read_bytes()
    return json.loads(gzip.decompress(raw) if name.endswith(".gz") else raw)


def write_state(name, obj):
    STATE.mkdir(exist_ok=True)
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    (STATE / name).write_bytes(gzip.compress(raw, mtime=0) if name.endswith(".gz") else raw)


# ---------------------------------------------------------------- API layers (need FEC_API_KEY)

def refresh_cutoffs(api, today):
    st = read_state("election_cutoffs.json", {"fetched": None, "cutoffs": {}})
    if st["fetched"] == today:
        return st["cutoffs"], None
    try:
        rows = list(api.pages("/election-dates/", election_year=CFG["cycle"], office_sought=["H", "S"]))
        st = {"fetched": today, "cutoffs": core.primary_cutoffs(rows)}
        write_state("election_cutoffs.json", st)
        return st["cutoffs"], None
    except Exception as e:  # stale cutoffs are fine; efile rows default to general after cutoff
        return st["cutoffs"], f"election-dates: {e}"


def refresh_efile(api, since):
    rows = list(api.pages("/schedules/schedule_e/efile/", min_filed_date=since, most_recent="true",
                          sort="expenditure_date"))
    return [core.from_efile(r) for r in rows if r.get("committee_id")]


def refresh_processed(api, today):
    """Periodic-report Schedule E (is_notice=false). Backfill resumes across runs; nightly after that."""
    st = read_state("processed_e.json.gz", {"rows": {}, "cursor": None, "resume": None, "complete_on": None})
    if st["complete_on"] == today and not st["resume"]:
        return list(st["rows"].values()), None
    params = {"cycle": CFG["cycle"], "is_notice": "false", "most_recent": "true", "sort": "expenditure_date"}
    if st["cursor"]:
        params["min_filing_date"] = st["cursor"]
    note = None
    try:
        gen = _resume(api, params, st["resume"] or {})
        for raw in gen:
            r = core.from_processed(raw)
            k = f'{r["committee_id"]}|{r["transaction_id"]}'
            old = st["rows"].get(k)
            if not old or int(r["file_num"] or 0) >= int(old["file_num"] or 0):
                st["rows"][k] = r
            st["resume"] = raw.get("_last_indexes")
        st["resume"] = None
        st["complete_on"] = today
        st["cursor"] = (date.fromisoformat(today) - timedelta(days=CFG["api"]["processed_overlap_days"])).isoformat()
    except sources.OutOfBudget as e:
        note = f"processed Schedule E partial (resumes next run): {e}"
    write_state("processed_e.json.gz", st)
    return list(st["rows"].values()), note


def _resume(api, params, last_indexes):
    extra = dict(last_indexes)
    while True:
        d = api.get("/schedules/schedule_e/", per_page=100, **params, **extra)
        li = (d.get("pagination") or {}).get("last_indexes")
        for r in d["results"]:
            r["_last_indexes"] = li
            yield r
        if not d["results"] or not li:
            return
        extra = li


def refresh_sched_f(api, today):
    st = read_state("sched_f.json.gz", {"fetched": None, "rows": []})
    if st["fetched"] == today:
        return st["rows"], None
    try:
        rows = [core.from_sched_f(r) for r in api.pages("/schedules/schedule_f/", cycle=CFG["cycle"])]
        best = {}
        for r in rows:  # latest amendment per transaction
            k = (r["committee_id"], r["transaction_id"])
            if k not in best or int(r["file_num"] or 0) >= int(best[k]["file_num"] or 0):
                best[k] = r
        st = {"fetched": today, "rows": list(best.values())}
        write_state("sched_f.json.gz", st)
        return st["rows"], None
    except Exception as e:
        return st["rows"], f"Schedule F: {e}"


def refresh_candidate_reports(api, today):
    """Raw e-filed House/Senate report summaries (F3), incremental by receipt date. Resumable."""
    st = read_state("efile_f3.json.gz", {"since": CFG["candidate_reports"]["backfill_from"], "rows": []})
    since = (date.fromisoformat(st["since"]) - timedelta(days=2)).isoformat()
    keep = {r["file_number"]: r for r in st["rows"]}
    note = None
    try:
        for x in api.pages("/efile/reports/house-senate/", min_receipt_date=since, sort="receipt_date"):
            keep[x["file_number"]] = {k: x.get(k) for k in ("committee_id", "coverage_end_date", "total_receipts_ytd",
                                                              "cash_on_hand_end_period", "file_number",
                                                              "document_description", "report_type", "receipt_date")}
        st["since"] = today
    except sources.OutOfBudget as e:
        note = f"candidate e-filed reports partial (resumes next run): {e}"
    st["rows"] = list(keep.values())
    write_state("efile_f3.json.gz", st)
    return st["rows"], note


def refresh_f6(api, today, committees):
    """48-hour contribution notices (Form 6) for nominee committees. Each filing's raw .fec file is read once
    and cached; amendments are resolved in core.live_f6."""
    st = read_state("f6.json.gz", {"since": CFG["candidate_reports"]["f6_from"], "filings": {}})
    if today < CFG["candidate_reports"]["f6_from"]:
        return st["filings"], None
    since = (date.fromisoformat(st["since"]) - timedelta(days=1)).isoformat()
    note = None
    try:
        for f in api.pages("/efile/filings/", form_type="F6", min_receipt_date=since, sort="receipt_date"):
            fn, cm = str(f["file_number"]), f.get("committee_id")
            if fn in st["filings"] or cm not in committees:
                continue
            # items come from the raw filing itself (public, no API quota); the API only lists filings
            url = f.get("fec_url") or f"https://docquery.fec.gov/dcdev/posted/{fn}.fec"
            body, _ = sources.fetch(url)
            items = core.parse_f6(body.decode("latin-1"))
            chain = [str(a) for a in (f.get("amendment_chain") or []) if str(a) != fn]
            if f.get("amends_file"):
                chain.append(str(f["amends_file"]))
            st["filings"][fn] = {"committee_id": cm, "amends": chain, "items": items,
                                 "filed": core.parse_date(f.get("receipt_date"))}
        st["since"] = today
    except sources.OutOfBudget as e:
        note = f"48-hour contribution notices partial (resumes next run): {e}"
    write_state("f6.json.gz", st)
    return st["filings"], note


def confirm_big_rows(api, held, today):
    """A held row is released once processed data shows the same committee, candidate and amount."""
    st = read_state("confirmed.json", {"confirmed": [], "checked": {}})
    confirmed = set(st["confirmed"])
    for r in sorted(held, key=lambda x: -x["amount"])[:10]:
        k = r["dedupe_key"]
        if k in confirmed or st["checked"].get(k) == today or not r["candidate_id"]:
            continue
        try:
            d = api.get("/schedules/schedule_e/", committee_id=r["committee_id"], candidate_id=r["candidate_id"],
                        min_amount=r["amount"] - 1, max_amount=r["amount"] + 1, cycle=CFG["cycle"], per_page=5)
        except Exception:
            break
        st["checked"][k] = today
        if d.get("results"):
            confirmed.add(k)
    st["confirmed"] = sorted(confirmed)
    write_state("confirmed.json", st)
    return confirmed


# ---------------------------------------------------------------- main build

def build(now: datetime, offline: Path | None = None):
    today = now.date().isoformat()
    notes = []

    # reference + bulk (no key needed)
    if offline:
        bulk_rows = list(csv.DictReader(io.StringIO((offline / "ie.csv").read_text(encoding="latin-1"))))
        cm_lines = (offline / "cm.txt").read_text(encoding="latin-1").splitlines()
        cn_lines = (offline / "cn.txt").read_text(encoding="latin-1").splitlines()
        legs = json.loads((offline / "leg.json").read_text())
        wb = offline / "weball.txt"
        summary_lines = wb.read_text(encoding="latin-1").splitlines() if wb.exists() else []
        bulk_lm = "offline"
    else:
        S = CFG["sources"]
        bulk_rows, bulk_lm = sources.bulk_ie(S["bulk_ie"])
        cm_lines, _ = sources.bulk_zip_lines(S["bulk_committees"])
        cn_lines, _ = sources.bulk_zip_lines(S["bulk_candidates"])
        summary_lines, _ = sources.bulk_zip_lines(S["bulk_candidate_summary"])
        legs = sources.legislators(S["legislators"])
    if len(bulk_rows) < CFG["fail_if_bulk_rows_under"]:
        raise CheckFailed(f"bulk IE file has {len(bulk_rows)} rows (< {CFG['fail_if_bulk_rows_under']}); refusing to publish")
    candidates = core.load_candidates(cn_lines)
    committees = core.load_committees(cm_lines)
    races = core.build_races(candidates, legs, CFG["cycle"], CFG)
    log(f"bulk rows {len(bulk_rows)}, candidates {len(candidates)}, committees {len(committees)}, races {len(races)}")

    rows = [core.from_bulk(r) for r in bulk_rows]
    for r in rows:
        r["dedupe_key"] = "|".join(str(x) for x in (r["committee_id"], r["file_num"], r["transaction_id"], r["kind"]))

    # API layers
    key = sources.api_key()
    api_status = {"key": bool(key), "efile": None, "processed": None, "sched_f": None, "calls": 0}
    cutoffs, sched_f, confirmed = {}, [], set()
    if key and not offline:
        api = sources.OpenFEC(CFG["sources"]["api_base"], key, CFG["api"]["max_calls_per_run"], CFG["api"]["min_remaining_calls"])
        cutoffs, n = refresh_cutoffs(api, today)
        notes += [n] if n else []
        since = (now.date() - timedelta(days=CFG["api"]["efile_lookback_days"])).isoformat()
        try:
            ef = refresh_efile(api, since)
            rows += ef
            api_status["efile"] = {"rows": len(ef), "filed_since": since}
        except Exception as e:
            notes.append(f"efile: {e}")
        sched_f, n = refresh_sched_f(api, today)
        notes += [n] if n else []
        api_status["sched_f"] = {"rows": len(sched_f)}
        rows += sched_f
        proc, n = refresh_processed(api, today)
        notes += [n] if n else []
        api_status["processed"] = {"rows": len(proc)}
        rows += proc
    else:
        cached_f = read_state("sched_f.json.gz", {"rows": []})["rows"]
        cached_p = read_state("processed_e.json.gz", {"rows": {}})["rows"]
        rows += cached_f + list(cached_p.values())
        sched_f = cached_f
        if not offline:
            notes.append("No FEC_API_KEY: using the daily bulk file of 24/48-hour notices only (no intraday efile, no new periodic or Schedule F data).")

    for r in rows:
        r.setdefault("dedupe_key", "")
    gaps_holder = {}
    rows, dstats = core.dedupe(rows, on_before_notice_match=lambda rs: gaps_holder.setdefault("gaps", core.committee_gaps(rs, CFG)), today=today)
    kept, buckets = core.attribute(rows, candidates, committees, races, CFG, cutoffs=cutoffs,
                                   confirmed=set(read_state("confirmed.json", {"confirmed": []})["confirmed"]))
    if key and not offline and buckets["held"]:
        confirmed = confirm_big_rows(api, buckets["held"], today)
        if confirmed:
            kept, buckets = core.attribute(rows, candidates, committees, races, CFG, cutoffs=cutoffs, confirmed=confirmed)
    if key and not offline:
        api_status["calls"] = api.calls

    # ---- checks
    kept_d = sum(r["amount"] for r in kept)
    unm_d = sum(r["amount"] for r in buckets["unmatched"])
    unmatched_share = unm_d / (kept_d + unm_d) if (kept_d + unm_d) else 0
    if unmatched_share > CFG["fail_if_unmatched_share_over"]:
        raise CheckFailed(f"{unmatched_share:.1%} of general-election dollars have no matching race (limit {CFG['fail_if_unmatched_share_over']:.0%})")
    if not kept:
        raise CheckFailed("no attributable rows")
    for r in kept:
        assert r["race_id"] in races and r["helps"] in core.PARTIES, r

    roll = core.rollup(kept, races, CFG, today)
    if any(r["total"] > 1_000_000_000 for r in roll.values()):
        raise CheckFailed("a race total exceeds $1B — impossible value slipped past the hold")
    summary = core.load_candidate_summary(summary_lines)
    nominees = core.pick_nominees(kept, races, candidates, summary, CFG,
                                  sitting_fec={f for leg in legs for f in leg["id"].get("fec", [])})
    # fresher candidate money: raw e-filed reports and 48-hour notices (API key), else cached
    nominee_cmtes = {c["committee_id"] for rc in nominees.values() for c in rc.values() if c.get("committee_id")}
    if key and not offline:
        f3_rows, n = refresh_candidate_reports(api, today)
        notes += [n] if n else []
        f6_filings, n = refresh_f6(api, today, nominee_cmtes)
        notes += [n] if n else []
        api_status["calls"] = api.calls
    else:
        f3_rows = read_state("efile_f3.json.gz", {"rows": []})["rows"]
        f6_filings = read_state("f6.json.gz", {"filings": {}})["filings"]
    core.apply_fresh_money(nominees, core.latest_reports(f3_rows), core.live_f6(f6_filings))
    for rid, r in roll.items():
        r["cand"] = nominees.get(rid, {})
        r["split_signal"] = core.split_signal(r, r["cand"], CFG["split_signal_min_gap"])
        r["note"] = CFG["race_notes"].get(rid)
    head = core.headline(roll, CFG)
    cand_head = core.cand_headline(roll)
    throughs = sorted(x["through"] for r in roll.values() for x in r["cand"].values() if x.get("through"))
    cand_through = throughs[len(throughs) // 2] if throughs else None  # median nominee report date
    series = core.daily_series(kept, CFG["chart_start"], today)

    coord_party = [r for r in kept if r["kind"] == "coord"]
    coord_through = max((r["dissemination_date"] for r in coord_party if r["dissemination_date"]), default=None)

    return {
        "today": today, "races": races, "roll": roll, "head": head, "series": series, "kept": kept,
        "buckets": buckets, "dstats": dstats, "gaps": gaps_holder.get("gaps", []), "notes": notes,
        "api": api_status, "bulk_last_modified": bulk_lm, "bulk_rows": len(bulk_rows),
        "coord_through": coord_through, "unmatched_share": unmatched_share,
        "cand_head": cand_head, "cand_through": cand_through, "summary_rows": len(summary),
    }


# ---------------------------------------------------------------- publish

EXP_FIELDS = ["dedupe_key", "source", "kind", "is_notice", "committee_id", "committee_name", "committee_class",
              "candidate_id", "candidate_name", "candidate_party", "race_id", "support_oppose", "helps", "amount",
              "dissemination_date", "filed_at", "file_num", "transaction_id", "image_number", "election_type",
              "payee", "purpose"]


def to_csv(rows, fields):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def race_csv_rows(roll):
    for r in sorted(roll.values(), key=lambda x: -x["total"]):
        row = {k: r[k] for k in ("race_id", "office", "state", "district", "holder_party", "holder_uncertain", "open_seat", "total", "last_7d")}
        for p in core.PARTIES:
            for k in ("party_ie", "party_coord", "outside", "super_pac", "total", "last_7d", "first_party_dollar", "side"):
                row[f"{p.lower()}_{k}"] = r[p][k]
            c = r["cand"].get(p) or {}
            for k in ("candidate_id", "name", "basis", "receipts", "coh", "late_48h", "from_party", "through"):
                row[f"{p.lower()}_nominee_{k}"] = c.get(k)
        row["split_signal"] = bool(r["split_signal"])
        row["note"] = r.get("note") or ""
        yield row


def rss(alerts, now_iso):
    items = []
    names = {"first_100k": "crossed $100K", "first_1m": "crossed $1M", "first_party_dollar": "first party-committee dollar"}
    for a in [a for a in alerts if not a.get("retracted")][:50]:
        if a["type"] == "split_signal":
            title = f'{a["race_id"]}: split signal: outside money favors {a["outside_leader"]}, candidate fundraising favors {a["party"]}'
            desc = f'Flagged {a["crossed_on"]}. Compares general-election outside spending with nominees\' cycle-to-date receipts.'
        else:
            title = f'{a["race_id"]}: pro-{a["party"]} spending {names[a["type"]]}'
            desc = f'Crossed on {a["crossed_on"]} (dissemination date). Triggering filer: {a.get("by") or "n/a"}.'
        guid = f'{a["race_id"]}-{a["party"]}-{a["type"]}'
        pub = datetime.fromisoformat(a["detected_at"].replace("Z", "+00:00")).strftime("%a, %d %b %Y %H:%M:%S +0000")
        items.append(f"<item><title>{escape(title)}</title><description>{escape(desc)}</description>"
                     f"<guid isPermaLink=\"false\">{guid}</guid><pubDate>{pub}</pubDate></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            "<title>Follow the Money: new races</title><link>./</link>"
            "<description>Races that just crossed a 2026 outside-spending threshold, from FEC filings.</description>"
            f"<lastBuildDate>{escape(now_iso)}</lastBuildDate>" + "".join(items) + "</channel></rss>\n")


def write_sqlite(path, b, alerts):
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute(f"create table expenditures ({', '.join(EXP_FIELDS)})")
    con.executemany(f"insert into expenditures values ({','.join('?' * len(EXP_FIELDS))})",
                    [[str(r.get(f)) if isinstance(r.get(f), (list, dict)) else r.get(f) for f in EXP_FIELDS] for r in b["kept"]])
    con.execute("create table races (race_id primary key, holder_party, holder_uncertain, open_seat, candidate_ids)")
    con.executemany("insert into races values (?,?,?,?,?)", [(r["race_id"], r["holder_party"], r["holder_uncertain"], r["open_seat"], ",".join(r["candidate_ids"])) for r in b["races"].values()])
    con.execute("create table race_rollup (race_id primary key, json)")
    con.executemany("insert into race_rollup values (?,?)", [(k, json.dumps(v)) for k, v in b["roll"].items()])
    con.execute("create table alerts (race_id, party, type, threshold, crossed_on, detected_at)")
    con.executemany("insert into alerts values (?,?,?,?,?,?)", [(a["race_id"], a["party"], a["type"], a["threshold"], a["crossed_on"], a["detected_at"]) for a in alerts])
    con.commit()
    con.close()


def publish(b, out: Path, now: datetime):
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = out / "data"
    prev_alerts_path = data / "alerts.json"
    prev = json.loads(prev_alerts_path.read_text())["alerts"] if prev_alerts_path.exists() else []
    current = core.crossings(b["kept"], CFG) + [
        {"race_id": r["race_id"], "party": r["split_signal"]["candidate_leader"], "type": "split_signal", "threshold": None,
         "crossed_on": b["today"], "by": None, "outside_leader": r["split_signal"]["outside_leader"]}
        for r in b["roll"].values() if r["split_signal"]]
    alerts = core.merge_alerts(prev, current, now_iso, first_run=not prev_alerts_path.exists())

    races_out = sorted(b["roll"].values(), key=lambda r: -r["total"])
    files = {
        "races.json": json.dumps({"races": races_out}, separators=(",", ":")),
        "alerts.json": json.dumps({"alerts": alerts}, separators=(",", ":")),
        "series.json": json.dumps({"series": b["series"]}, separators=(",", ":")),
        "races.csv": to_csv(list(race_csv_rows(b["roll"])), list(next(race_csv_rows(b["roll"])).keys())),
        "expenditures.csv": to_csv(sorted(b["kept"], key=lambda r: (r["race_id"], r["dissemination_date"] or "")), EXP_FIELDS),
        "excluded.csv": to_csv([{**r, "bucket": k} for k in ("unmatched", "held") for r in b["buckets"][k]], ["bucket"] + EXP_FIELDS),
    }
    digest = hashlib.sha256("".join(files[k] for k in sorted(files)).encode()).hexdigest()[:16]
    old_meta = json.loads((data / "meta.json").read_text()) if (data / "meta.json").exists() else {}
    changed = old_meta.get("data_hash") != digest

    meta = {
        "generated_at": now_iso if changed else old_meta.get("generated_at", now_iso),
        "data_hash": digest,
        "as_of": b["today"],
        "bulk_last_modified": b["bulk_last_modified"],
        "coord_through": b["coord_through"],
        "coord_banner": CFG["text"]["coord_banner"].format(date=b["coord_through"] or "—"),
        "caveat": CFG["text"]["caveat"],
        "headline": b["head"],
        "cand_headline": b["cand_head"],
        "cand_through": b["cand_through"],
        "cand_banner": CFG["text"]["cand_banner"].format(date=b["cand_through"] or "—"),
        "thresholds": CFG["thresholds"],
        "api": b["api"],
        "counts": {
            "bulk_rows": b["bulk_rows"], "expenditures": len(b["kept"]), "races": len(b["roll"]),
            **{f"excluded_{k}": len(v) for k, v in b["buckets"].items()},
            **{f"excluded_{k}_dollars": round(sum(r["amount"] for r in v), 2) for k, v in b["buckets"].items()},
            **{f"dedupe_{k}": v for k, v in b["dstats"].items()},
        },
        "unmatched_share": round(b["unmatched_share"], 4),
        "committee_gaps": b["gaps"][:25],
        "notes": b["notes"],
    }
    files["meta.json"] = json.dumps(meta, indent=1)

    # stage then swap, so a crash mid-write never leaves a half-published set
    stage = out / ".stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    for name, body in files.items():
        (stage / name).write_text(body)
    (stage / "rss.xml").write_text(rss(alerts, now_iso))
    data.mkdir(parents=True, exist_ok=True)
    if changed:
        for name in files:
            os.replace(stage / name, data / name)
        os.replace(stage / "rss.xml", out / "rss.xml")
    hb = data / "heartbeat.txt"
    if now.hour >= CFG["schedule"]["heartbeat_hour_utc"] and (not hb.exists() or hb.read_text().strip() != b["today"]):
        hb.write_text(b["today"] + "\n")
    shutil.rmtree(stage, ignore_errors=True)
    (ROOT / "build").mkdir(exist_ok=True)
    write_sqlite(ROOT / "build" / "ftm.sqlite", b, alerts)
    return changed, meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", type=Path, help="dir with ie.csv, cm.txt, cn.txt, leg.json")
    ap.add_argument("--out", type=Path, default=ROOT / "site")
    ap.add_argument("--now", help="override clock (ISO)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=timezone.utc) if a.now else datetime.now(timezone.utc)
    try:
        b = build(now, a.offline)
    except CheckFailed as e:
        log("CHECK FAILED —", e, "— last good data left in place")
        return 2
    changed, meta = publish(b, a.out, now)
    h = meta["headline"]
    log(f"changed={changed} races={meta['counts']['races']} rows={meta['counts']['expenditures']} "
        f"unmatched={meta['unmatched_share']:.2%} held={meta['counts']['excluded_held']}")
    for k in ("H_DEM", "H_REP", "S_DEM", "S_REP"):
        log(k, h[k])
    for n in b["notes"]:
        log("note:", n)
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
