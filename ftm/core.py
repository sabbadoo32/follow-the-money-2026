"""Pure logic: normalize, attribute, dedupe, roll up, alert. No network, no disk.

Every function here takes plain dicts/lists so it can be unit-tested with fixtures.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta

DEM, REP = "DEM", "REP"
PARTIES = (DEM, REP)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


# ---------------------------------------------------------------- parsing

def parse_date(s) -> str | None:
    """Accepts '16-MAY-26', '2026-05-16', '2026-05-16T00:00:00', '05/16/2026'. Returns ISO date or None."""
    if not s:
        return None
    s = str(s).strip()
    m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})", s)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return date(y, MONTHS[m.group(2).upper()], int(m.group(1))).isoformat()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    return None


def money(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def norm_payee(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def norm_district(d) -> str:
    d = re.sub(r"\D", "", str(d or ""))
    return d.zfill(2)[-2:] if d else "00"


def race_id(office: str, state: str, district: str | None) -> str | None:
    if office == "H" and state:
        return f"H-{state}-{norm_district(district)}"
    if office == "S" and state:
        return f"S-{state}"
    return None


# ---------------------------------------------------------------- reference data

def load_candidates(lines):
    """cn.txt pipe-delimited lines -> {cand_id: {...}}."""
    out = {}
    for line in lines:
        f = line.rstrip("\n").split("|")
        if len(f) < 9:
            continue
        out[f[0]] = {
            "candidate_id": f[0], "name": f[1], "party": f[2], "election_yr": f[3],
            "state": f[4], "office": f[5], "district": norm_district(f[6]), "ici": f[7], "status": f[8],
        }
    return out


def load_committees(lines):
    """cm.txt pipe-delimited lines -> {cmte_id: {...}}."""
    out = {}
    for line in lines:
        f = line.rstrip("\n").split("|")
        if len(f) < 11:
            continue
        out[f[0]] = {"committee_id": f[0], "name": f[1], "type": f[9], "party": f[10]}
    return out


def committee_class(cmte_type: str, cfg) -> str:
    if cmte_type in cfg["party_committee_types"]:
        return "party"
    if cmte_type in cfg["super_pac_committee_types"]:
        return "super_pac"
    return "other"


def party_code(p: str, cfg) -> str | None:
    p = (p or "").upper().strip()
    if p in cfg["dem_party_codes"] or p.startswith("DEMOCRAT"):
        return DEM
    if p in cfg["rep_party_codes"] or p.startswith("REPUBLICAN"):
        return REP
    return None


def build_races(candidates, legislators, cycle, cfg):
    """Seat holders from congress-legislators, cross-checked against FEC candidate filings.

    Returns {race_id: {race_id, office, state, district, holder_party, holder_name,
                       holder_uncertain, uncertain_reason, open_seat, candidate_ids}}.
    """
    yr = str(cycle)
    cands = [c for c in candidates.values() if c["election_yr"] == yr and c["office"] in ("H", "S")]
    fec_to_leg = {}
    house_holder, sen_by_state = {}, defaultdict(list)
    for leg in legislators:
        t = leg["terms"][-1]
        party = t.get("caucus") or t.get("party")
        rec = {"name": f'{leg["name"].get("first", "")} {leg["name"].get("last", "")}'.strip(),
               "party": party_code(party, cfg), "fec": leg["id"].get("fec", []), "term": t}
        for fid in rec["fec"]:
            fec_to_leg[fid] = rec
        if t["type"] == "rep":
            house_holder[f'H-{t["state"]}-{norm_district(t.get("district"))}'] = rec
        elif t["type"] == "sen":
            sen_by_state[t["state"]].append(rec)

    # Which district is each sitting member running in this cycle?
    running_in = defaultdict(set)
    for c in cands:
        leg = fec_to_leg.get(c["candidate_id"])
        if leg:
            running_in[id(leg)].add(race_id(c["office"], c["state"], c["district"]))

    races = {}
    for c in cands:
        rid = race_id(c["office"], c["state"], c["district"])
        if not rid:
            continue
        r = races.setdefault(rid, {"race_id": rid, "office": c["office"], "state": c["state"],
                                   "district": c["district"] if c["office"] == "H" else None,
                                   "candidate_ids": []})
        r["candidate_ids"].append(c["candidate_id"])

    for rid, r in races.items():
        reason = None
        if r["office"] == "H":
            holder = house_holder.get(rid)
            if holder:
                elsewhere = running_in.get(id(holder), set()) - {rid}
                if any(x and x.startswith("H-") for x in elsewhere):
                    reason = f"current member filed in {', '.join(sorted(x for x in elsewhere if x))}"
            # an FEC 'incumbent' here who holds a different seat => lines moved
            for cid in r["candidate_ids"]:
                c = candidates[cid]
                leg = fec_to_leg.get(cid)
                if c["ici"] == "I" and leg and leg["term"]["type"] == "rep":
                    their = f'H-{leg["term"]["state"]}-{norm_district(leg["term"].get("district"))}'
                    if their != rid:
                        reason = reason or f"incumbent {leg['name']} currently holds {their}"
            if not holder:
                inc = [candidates[c] for c in r["candidate_ids"] if candidates[c]["ici"] == "I"]
                holder = {"name": inc[0]["name"], "party": party_code(inc[0]["party"], cfg)} if inc else None
                reason = reason or ("vacant seat" if not holder else None)
        else:
            sens = [s for s in sen_by_state.get(r["state"], []) if s["term"].get("end", "9999") <= f"{cycle + 1}-01-03"]
            running = [s for s in sens if set(s["fec"]) & set(r["candidate_ids"])]
            holder = (running or sens or [None])[0]
            if not holder:
                reason = "no seat up found"
        r["holder_party"] = holder["party"] if holder else None
        r["holder_name"] = holder["name"] if holder else None
        r["holder_uncertain"] = bool(reason) or not r["holder_party"]
        r["uncertain_reason"] = reason if reason else (None if r["holder_party"] else "holder party unknown")
        holder_fec = set(holder.get("fec", [])) if holder else set()
        has_inc = any(candidates[c]["ici"] == "I" for c in r["candidate_ids"])
        r["open_seat"] = not (holder_fec & set(r["candidate_ids"])) and not has_inc
    return races


def primary_cutoffs(election_dates):
    """/election-dates rows -> {state: last primary-or-primary-runoff date (ISO)}."""
    out = {}
    for e in election_dates:
        t = (e.get("election_type_id") or "").upper()
        if t in ("G", "GR", "SG", "SGR") or not e.get("election_date"):
            continue
        st = e.get("election_state")
        d = parse_date(e["election_date"])
        if st and d and (st not in out or d > out[st]):
            out[st] = d
    return out


# ---------------------------------------------------------------- normalize

def from_bulk(row):
    return {
        "source": "bulk", "kind": "ie", "is_notice": True,
        "committee_id": row["spe_id"], "committee_name": row["spe_nam"],
        "candidate_id": row["cand_id"], "candidate_name": row["cand_name"],
        "office": row["can_office"], "state": row["can_office_state"], "district": row["can_office_dis"],
        "row_party": row["cand_pty_aff"], "support_oppose": row["sup_opp"],
        "amount": money(row["exp_amo"]),
        "dissemination_date": parse_date(row["dissem_dt"]) or parse_date(row["exp_date"]) or parse_date(row["receipt_dat"]),
        "filed_at": parse_date(row["receipt_dat"]),
        "file_num": str(row["file_num"]), "prev_file_num": str(row["prev_file_num"] or ""),
        "amends": [], "transaction_id": row["tran_id"], "image_number": row["image_num"],
        "election_type": (row["ele_type"] or "")[:1], "payee": row["pay"], "purpose": row["pur"],
    }


def from_efile(row):
    f = row.get("filing") or {}
    chain = [str(x) for x in (f.get("amendment_chain") or []) if str(x) != str(row["file_number"])]
    if f.get("amends_file"):
        chain.append(str(f["amends_file"]))
    return {
        "source": "efile", "kind": "ie", "is_notice": bool(row.get("is_notice")),
        "committee_id": row["committee_id"], "committee_name": (row.get("committee") or {}).get("name") or f.get("committee_name"),
        "candidate_id": row.get("candidate_id"),
        "candidate_name": ", ".join(x for x in [row.get("candidate_name"), row.get("candidate_first_name")] if x),
        "office": row.get("candidate_office"), "state": row.get("candidate_office_state"),
        "district": row.get("candidate_office_district"), "row_party": row.get("candidate_party"),
        "support_oppose": row.get("support_oppose_indicator"), "amount": money(row.get("expenditure_amount")),
        "dissemination_date": parse_date(row.get("dissemination_date")) or parse_date(row.get("expenditure_date")) or parse_date(f.get("receipt_date")),
        "filed_at": parse_date(f.get("receipt_date") or row.get("load_timestamp")),
        "file_num": str(row["file_number"]), "prev_file_num": "", "amends": chain,
        "transaction_id": row.get("transaction_id"), "image_number": row.get("image_number"),
        "election_type": None, "payee": row.get("payee_name"), "purpose": row.get("expenditure_description"),
    }


def from_processed(row):
    return {
        "source": "processed", "kind": "ie", "is_notice": bool(row.get("is_notice")),
        "committee_id": row["committee_id"], "committee_name": (row.get("committee") or {}).get("name"),
        "candidate_id": row.get("candidate_id"), "candidate_name": row.get("candidate_name"),
        "office": row.get("candidate_office"), "state": row.get("candidate_office_state"),
        "district": row.get("candidate_office_district"), "row_party": row.get("candidate_party"),
        "support_oppose": row.get("support_oppose_indicator"), "amount": money(row.get("expenditure_amount")),
        "dissemination_date": parse_date(row.get("dissemination_date")) or parse_date(row.get("expenditure_date")),
        "filed_at": parse_date(row.get("filing_date")),
        "file_num": str(row.get("file_number")), "prev_file_num": str(row.get("previous_file_number") or ""),
        "amends": [], "transaction_id": row.get("transaction_id"), "image_number": row.get("image_number"),
        "election_type": (row.get("election_type") or "")[:1], "payee": row.get("payee_name"),
        "purpose": row.get("expenditure_description"),
    }


def from_sched_f(row):
    return {
        "source": "sched_f", "kind": "coord", "is_notice": False,
        "committee_id": row["committee_id"], "committee_name": row.get("committee_name"),
        "candidate_id": row.get("candidate_id"), "candidate_name": row.get("candidate_name"),
        "office": row.get("candidate_office"), "state": row.get("candidate_office_state"),
        "district": row.get("candidate_office_district"), "row_party": None,
        "support_oppose": "S", "amount": money(row.get("expenditure_amount")),
        "dissemination_date": parse_date(row.get("expenditure_date")),
        "filed_at": parse_date(row.get("load_date")),
        "file_num": str(row.get("file_number")), "prev_file_num": "", "amends": [],
        "transaction_id": row.get("transaction_id"), "image_number": row.get("image_number"),
        "election_type": "G", "payee": row.get("payee_name"), "purpose": row.get("expenditure_purpose_full"),
    }


# ---------------------------------------------------------------- dedupe

def drop_superseded(rows):
    """Keep only the latest amendment: a filing named as prev_file_num/amends by any row is replaced wholesale."""
    superseded = set()
    for r in rows:
        if r["prev_file_num"]:
            superseded.add(r["prev_file_num"])
        superseded.update(r["amends"])
    kept = [r for r in rows if r["file_num"] not in superseded]
    return kept, len(rows) - len(kept)


def drop_same_transaction(rows, prefer):
    """Same (committee, file, transaction) seen from two sources -> keep the preferred source."""
    rank = {s: i for i, s in enumerate(prefer)}
    best = {}
    for r in rows:
        k = (r["committee_id"], r["file_num"], r["transaction_id"], r["kind"])
        if k not in best or rank.get(r["source"], 99) < rank.get(best[k]["source"], 99):
            best[k] = r
    return list(best.values()), len(rows) - len(best)


def match_key(r):
    return (r["committee_id"], r["candidate_id"], r["dissemination_date"], round(r["amount"]), norm_payee(r["payee"]))


def drop_notice_repeats(rows):
    """A 24/48-hour notice item that later appears on a periodic report: keep the periodic copy.

    Matching is one-to-one on committee, candidate, dissemination date, amount and payee.
    """
    periodic = defaultdict(int)
    for r in rows:
        if r["kind"] == "ie" and not r["is_notice"]:
            periodic[match_key(r)] += 1
    kept, dropped = [], 0
    for r in rows:
        if r["kind"] == "ie" and r["is_notice"] and periodic.get(match_key(r), 0) > 0:
            periodic[match_key(r)] -= 1
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


def fix_future_dates(rows, today):
    """Notices are often filed before the ad airs. Dates after today are pinned to today so no timeline runs ahead."""
    n = 0
    for r in rows:
        if today and r["dissemination_date"] and r["dissemination_date"] > today:
            r["dissemination_date_reported"] = r["dissemination_date"]
            r["dissemination_date"] = today
            n += 1
    return n


def dedupe(rows, on_before_notice_match=None, today=None):
    stats = {"future_dates_pinned_to_today": fix_future_dates(rows, today)}
    rows, stats["superseded_amendments"] = drop_superseded(rows)
    rows, stats["same_transaction"] = drop_same_transaction(rows, prefer=["processed", "bulk", "sched_f", "efile"])
    if on_before_notice_match:
        on_before_notice_match(rows)
    rows, stats["notice_repeated_in_periodic"] = drop_notice_repeats(rows)
    for r in rows:
        r["dedupe_key"] = "|".join(str(x) for x in (r["committee_id"], r["file_num"], r["transaction_id"], r["kind"]))
    return rows, stats


# ---------------------------------------------------------------- attribute

def last_name(s) -> str:
    s = (s or "").upper()
    s = s.split(",")[0] if "," in s else (s.split()[-1] if s.split() else "")
    return re.sub(r"[^A-Z]", "", s)


def match_by_name(r, candidates, races):
    """Raw filings sometimes omit the candidate ID. Recover it from name + state + district, only if unambiguous."""
    ln = last_name(r["candidate_name"])
    st = (r["state"] or "").upper()
    if not ln or not st:
        return None
    office = (r["office"] or "").upper()[:1]
    tries = [office] if office in ("H", "S") else (["S", "H"] if norm_district(r["district"]) == "00" else ["H"])
    for o in tries:
        race = races.get(race_id(o, st, r["district"]))
        if not race:
            continue
        hits = [c for c in race["candidate_ids"] if last_name(candidates[c]["name"]) == ln]
        if len(hits) == 1:
            return candidates[hits[0]]
    return None


def attribute(rows, candidates, committees, races, cfg, cutoffs=None, confirmed=frozenset()):
    """Assign race, committee class and helped party. Returns (kept, buckets)."""
    cutoffs = cutoffs or {}
    kept = []
    buckets = {k: [] for k in ("primary_or_other", "other_cycle", "third_party", "not_congress", "unmatched", "held")}
    for r in rows:
        cand = candidates.get(r["candidate_id"] or "")
        if not cand and r["kind"] == "ie":
            cand = match_by_name(r, candidates, races)
            if cand:
                r["candidate_id"], r["id_recovered"] = cand["candidate_id"], True
        office = (cand or {}).get("office") or (r["office"] or "").upper()[:1]
        if office and office not in ("H", "S"):
            buckets["not_congress"].append(r)
            continue
        # election type: bulk/processed carry it; efile is inferred from the state's primary calendar
        et = r["election_type"]
        if not et:
            st = (cand or {}).get("state") or r["state"]
            cut = cutoffs.get(st)
            et = "G" if (cut and r["dissemination_date"] and r["dissemination_date"] > cut) else ("P" if cut else "G")
            r["election_type"] = et + "?"
        if et[:1] != "G":
            buckets["primary_or_other"].append(r)
            continue
        cap = cfg["hold_row_over"].get(office)
        if cap and r["amount"] >= cap and r["dedupe_key"] not in confirmed:
            buckets["held"].append(r)
            continue
        if not cand:
            buckets["unmatched"].append(r)
            continue
        if cand["election_yr"] != str(cfg["cycle"]):  # e.g. late bills for a 2024 race
            buckets["other_cycle"].append(r)
            continue
        rid = race_id(cand["office"], cand["state"], cand["district"])
        if rid not in races:
            buckets["unmatched"].append(r)
            continue
        cp = party_code(cand["party"], cfg) or party_code(r["row_party"], cfg)
        if not cp:
            buckets["third_party"].append(r)
            continue
        so = (r["support_oppose"] or "").upper()
        if so not in ("S", "O"):
            buckets["unmatched"].append(r)
            continue
        helps = cp if so == "S" else (REP if cp == DEM else DEM)
        cm = committees.get(r["committee_id"], {})
        r.update({
            "race_id": rid, "candidate_party": cp, "helps": helps,
            "committee_class": committee_class(cm.get("type", ""), cfg),
            "committee_name": r["committee_name"] or cm.get("name"),
            "candidate_name": cand["name"],
        })
        if r["kind"] == "coord" and r["committee_class"] != "party":
            r["committee_class"] = "party"  # Schedule F is party-only by law
        kept.append(r)
    return kept, buckets


# ---------------------------------------------------------------- roll up

def _blank_side():
    return {"party_ie": 0.0, "party_coord": 0.0, "outside": 0.0, "super_pac": 0.0, "total": 0.0,
            "first_party_dollar": None, "last_7d": 0.0}


def rollup(rows, races, cfg, as_of: str):
    since = (date.fromisoformat(as_of) - timedelta(days=cfg["momentum_days"] - 1)).isoformat()
    out = {}
    spenders = defaultdict(lambda: defaultdict(float))
    items = defaultdict(list)
    for r in rows:
        rid = r["race_id"]
        race = races[rid]
        o = out.setdefault(rid, {
            "race_id": rid, "office": race["office"], "state": race["state"], "district": race["district"],
            "holder_party": race["holder_party"], "holder_name": race["holder_name"],
            "holder_uncertain": race["holder_uncertain"], "uncertain_reason": race["uncertain_reason"],
            "open_seat": race["open_seat"], DEM: _blank_side(), REP: _blank_side(), "candidates": {},
        })
        s = o[r["helps"]]
        a = r["amount"]
        if r["committee_class"] == "party":
            s["party_coord" if r["kind"] == "coord" else "party_ie"] += a
            d = r["dissemination_date"]
            if d and (not s["first_party_dollar"] or d < s["first_party_dollar"]):
                s["first_party_dollar"] = d
        else:
            s["outside"] += a
            if r["committee_class"] == "super_pac":
                s["super_pac"] += a
        s["total"] += a
        if r["dissemination_date"] and since <= r["dissemination_date"] <= as_of:
            s["last_7d"] += a
        o["candidates"][r["candidate_id"]] = {"name": r["candidate_name"], "party": r["candidate_party"]}
        spenders[rid][(r["committee_id"], r["committee_name"], r["committee_class"], r["helps"])] += a
        items[rid].append(r)
    for rid, o in out.items():
        for p in PARTIES:
            s = o[p]
            for k in ("party_ie", "party_coord", "outside", "super_pac", "total", "last_7d"):
                s[k] = round(s[k], 2)
            hp = o["holder_party"]
            s["side"] = None if (o["holder_uncertain"] or not hp) else ("defense" if hp == p else "offense")
        o["total"] = round(o[DEM]["total"] + o[REP]["total"], 2)
        o["last_7d"] = round(o[DEM]["last_7d"] + o[REP]["last_7d"], 2)
        o["candidates"] = [{"candidate_id": k, **v} for k, v in sorted(o["candidates"].items())]
        top = sorted(spenders[rid].items(), key=lambda kv: -kv[1])[:10]
        o["top_spenders"] = [{"committee_id": k[0], "name": k[1], "class": k[2], "helps": k[3], "amount": round(v, 2)}
                             for k, v in top]
        big = sorted(items[rid], key=lambda x: -x["amount"])[:8]
        o["top_items"] = [{"committee_name": x["committee_name"], "amount": x["amount"], "helps": x["helps"],
                           "date": x["dissemination_date"], "kind": x["kind"], "image_number": x["image_number"],
                           "source": x["source"]} for x in big]
    return out


def headline(rollups, cfg):
    """Offense share, races in play and party footprint by party, House and Senate separately."""
    t = cfg["thresholds"]
    h = {}
    for office in ("H", "S"):
        rs = [r for r in rollups.values() if r["office"] == office]
        for p in PARTIES:
            known = [r for r in rs if r[p]["side"]]
            all_d = sum(r[p]["total"] for r in known)
            off = sum(r[p]["total"] for r in known if r[p]["side"] == "offense")
            h[f"{office}_{p}"] = {
                "offense_share": round(off / all_d, 4) if all_d else None,
                "offense_dollars": round(off, 2), "counted_dollars": round(all_d, 2),
                "excluded_uncertain_dollars": round(sum(r[p]["total"] for r in rs if not r[p]["side"]), 2),
                "races_in_play": sum(1 for r in rs if r[p]["total"] >= t["in_play"]),
                "party_footprint": sum(1 for r in rs if (r[p]["party_ie"] + r[p]["party_coord"]) >= t["party_footprint"]),
                "total": round(sum(r[p]["total"] for r in rs), 2),
                "last_7d": round(sum(r[p]["last_7d"] for r in rs), 2),
                "coord_total": round(sum(r[p]["party_coord"] for r in rs), 2),
            }
    return h


def daily_series(rows, start: str, end: str):
    """Cumulative dollars helping each party by dissemination date, House and Senate."""
    by_day = defaultdict(lambda: defaultdict(float))
    base = defaultdict(float)
    for r in rows:
        d = r["dissemination_date"]
        key = f'{r["race_id"][0]}_{r["helps"]}'
        if not d or d < start:
            base[key] += r["amount"]
        elif d <= end:
            by_day[d][key] += r["amount"]
    keys = [f"{o}_{p}" for o in "HS" for p in PARTIES]
    cum = {k: base[k] for k in keys}
    out = []
    d = date.fromisoformat(start)
    while d.isoformat() <= end:
        for k in keys:
            cum[k] += by_day[d.isoformat()][k]
        out.append({"date": d.isoformat(), **{k: round(cum[k], 2) for k in keys}})
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- alerts

def crossings(rows, cfg):
    """Derive each race/party threshold crossing from the data itself, dated by dissemination date."""
    t = cfg["thresholds"]
    per = defaultdict(list)
    for r in rows:
        per[(r["race_id"], r["helps"])].append(r)
    out = []
    for (rid, p), rs in per.items():
        rs.sort(key=lambda x: (x["dissemination_date"] or "9999", x["amount"]))
        cum, got = 0.0, set()
        for r in rs:
            cum += r["amount"]
            if r["committee_class"] == "party" and "first_party_dollar" not in got and r["amount"] >= t["party_footprint"]:
                got.add("first_party_dollar")
                out.append({"race_id": rid, "party": p, "type": "first_party_dollar", "threshold": t["party_footprint"],
                            "crossed_on": r["dissemination_date"], "by": r["committee_name"]})
            for name, amt in (("first_100k", t["in_play"]), ("first_1m", t["big"])):
                if name not in got and cum >= amt:
                    got.add(name)
                    out.append({"race_id": rid, "party": p, "type": name, "threshold": amt,
                                "crossed_on": r["dissemination_date"], "by": r["committee_name"]})
    return out


def merge_alerts(previous, current, now_iso, first_run: bool):
    """Keep detected_at from earlier runs; stamp newly seen crossings with now.

    On the very first run everything would be 'new', so detected_at falls back to the crossing date.
    """
    prev = {(a["race_id"], a["party"], a["type"]): a for a in previous}
    out = []
    for a in current:
        k = (a["race_id"], a["party"], a["type"])
        if k in prev:
            a["detected_at"] = prev[k]["detected_at"]
        else:
            a["detected_at"] = (a["crossed_on"] + "T00:00:00Z") if first_run else now_iso
        out.append(a)
    # a crossing that vanished (e.g. a correction) stays on record, marked retracted
    cur = {(a["race_id"], a["party"], a["type"]) for a in current}
    for k, a in prev.items():
        if k not in cur:
            out.append({**a, "retracted": True})
    out.sort(key=lambda a: (a["detected_at"], a["crossed_on"] or ""), reverse=True)
    return out


# ---------------------------------------------------------------- checks

def committee_gaps(rows, cfg):
    """Per committee: notice totals vs periodic totals over the period periodic reports cover."""
    flag = cfg["committee_gap_flag"]
    by = defaultdict(list)
    for r in rows:
        if r["kind"] == "ie":
            by[r["committee_id"]].append(r)
    out = []
    for cid, rs in by.items():
        per = [r for r in rs if not r["is_notice"] and r["dissemination_date"]]
        if not per:
            continue
        through = max(r["dissemination_date"] for r in per)
        n = sum(r["amount"] for r in rs if r["is_notice"] and (r["dissemination_date"] or "") <= through)
        p = sum(r["amount"] for r in per)
        if n and max(n, p) >= flag["min_dollars"] and abs(n - p) / max(n, p) > flag["share"]:
            out.append({"committee_id": cid, "name": rs[0]["committee_name"], "notice_total": round(n, 2),
                        "periodic_total": round(p, 2), "through": through})
    return sorted(out, key=lambda x: -abs(x["notice_total"] - x["periodic_total"]))


# ---------------------------------------------------------------- candidate money

def load_candidate_summary(lines):
    """weball26.txt (all-candidates summary) -> {cand_id: cycle-to-date money}."""
    out = {}
    for line in lines:
        f = line.rstrip("\n").split("|")
        if len(f) < 28:
            continue
        out[f[0]] = {"receipts": money(f[5]), "disbursements": money(f[7]), "coh": money(f[10]),
                     "indiv": money(f[17]), "from_party": money(f[26]), "through": parse_date(f[27])}
    return out


def pick_nominees(kept, races, candidates, summary, cfg, sitting_fec=frozenset()):
    """Per race and party, the general-election nominee and their committee money.

    FEC summaries carry no primary results, so the nominee is the candidate general-election
    outside money targets most, if at least nominee_min_ie (basis 'ie'; a floor so a few
    miscoded dollars can't crown the wrong person). With no such spending, fall back to the top fundraiser
    (basis 'receipts'), which can be a primary loser and is marked as inferred.
    """
    ie = defaultdict(float)
    for r in kept:
        if r["kind"] == "ie":
            ie[(r["race_id"], r["candidate_party"], r["candidate_id"])] += r["amount"]
    out = {}
    for rid, race in races.items():
        for p in PARTIES:
            ids = [c for c in race["candidate_ids"] if party_code(candidates[c]["party"], cfg) == p]
            targeted = [c for c in ids if ie.get((rid, p, c), 0) >= cfg["nominee_min_ie"]]
            if targeted:
                cid, basis = max(targeted, key=lambda c: ie[(rid, p, c)]), "ie"
                # namesakes: filers can mix up their IDs. Never fall back to receipts here, since an
                # old war chest can outlast its candidate (SC 2026: Lindsey Graham died; Darline Graham is the nominee).
                twins = [c for c in ids if last_name(candidates[c]["name"]) == last_name(candidates[cid]["name"])]
                if len(twins) > 1:
                    seated = [c for c in twins if c in sitting_fec]
                    twin_ie = sum(ie.get((rid, p, c), 0) for c in twins)
                    if len(seated) == 1:
                        cid = seated[0]
                    elif ie[(rid, p, cid)] < 0.9 * twin_ie:
                        basis = "name_collision"
            else:
                funded = [c for c in ids if c in summary]
                if not funded:
                    continue
                cid, basis = max(funded, key=lambda c: summary[c]["receipts"]), "receipts"
            s = summary.get(cid, {})
            out.setdefault(rid, {})[p] = {
                "candidate_id": cid, "name": candidates[cid]["name"], "basis": basis,
                "receipts": s.get("receipts", 0.0), "coh": s.get("coh", 0.0), "indiv": s.get("indiv", 0.0),
                "from_party": s.get("from_party", 0.0), "through": s.get("through")}
    return out


def split_signal(roll_race, cand, min_gap):
    """Outside money favors one party while candidate fundraising favors the other.

    Needs both nominees identified from general-election spending, and a gap of at least
    min_gap on both measures, so noise and primary losers can't trip it.
    """
    d, r = cand.get(DEM), cand.get(REP)
    if not d or not r or d["basis"] != "ie" or r["basis"] != "ie":
        return None
    og = roll_race[DEM]["total"] - roll_race[REP]["total"]
    cg = d["receipts"] - r["receipts"]
    if abs(og) < min_gap or abs(cg) < min_gap or (og > 0) == (cg > 0):
        return None
    return {"outside_leader": DEM if og > 0 else REP, "candidate_leader": DEM if cg > 0 else REP,
            "outside_gap": round(abs(og), 2), "candidate_gap": round(abs(cg), 2)}


def cand_headline(rollups):
    h = {}
    for office in ("H", "S"):
        rs = [r for r in rollups.values() if r["office"] == office]
        for p in PARTIES:
            c = [r["cand"][p] for r in rs if r.get("cand", {}).get(p)]
            h[f"{office}_{p}"] = {
                "receipts": round(sum(x["receipts"] for x in c), 2), "coh": round(sum(x["coh"] for x in c), 2),
                "from_party": round(sum(x["from_party"] for x in c), 2),
                "nominees": len(c), "inferred": sum(1 for x in c if x["basis"] != "ie"),
                "cand_lead_races": sum(1 for r in rs if r.get("cand", {}).get(p) and r["cand"][p]["receipts"] >
                                       (r["cand"].get(REP if p == DEM else DEM) or {}).get("receipts", 0)),
                "split_favoring": sum(1 for r in rs if r.get("split_signal") and r["split_signal"]["candidate_leader"] == p),
            }
    return h
