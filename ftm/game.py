"""Smart Money (tagline: Think like the insiders): a daily 10-question game generated from the tracker's own data.

One puzzle per day, frozen the first time the pipeline runs that day, so everyone plays the same set.
Questions come from the rollup (live filings) plus a fixed bank of campaign-finance rules.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date

from . import core

LAUNCH = date(2026, 9, 28)  # puzzle #1 (Eastern time)
PARTY = {"DEM": "Democrats", "REP": "Republicans"}

# Rules questions. Facts are FEC rules for 2025-26; each links to its glossary entry.
RULES = [
    ("Can a super PAC give $10,000 directly to a House candidate's campaign?", ["Yes", "No"], 1,
     "Super PACs can raise unlimited money but can't give to candidates or coordinate with them. They can only spend independently.", "super_pac"),
    ("What's the most one person can give a House candidate for the 2026 general election?", ["$3,500", "$10,000", "Unlimited"], 0,
     "The 2025-26 limit is $3,500 per election; the primary and general each count as separate elections.", "candidate_committee"),
    ("After NRSC v. FEC (June 2026), how much can a party spend in coordination with its Senate nominee?", ["Up to a set limit per state", "Unlimited", "Nothing"], 1,
     "The Supreme Court struck down the limits on party coordinated spending, so parties can now spend without limit alongside their candidates.", "nrsc"),
    ("A super PAC airs a $1,000 ad on Oct. 20. How fast must it tell the FEC?", ["Within 24 hours", "Within 48 hours", "On its next monthly report"], 0,
     "From Oct. 15 to Nov. 1, independent expenditures of $1,000 or more must be reported within 24 hours.", "notice_24_48"),
    ("In the final 60 days, who pays less for the same TV spot?", ["The candidate", "A super PAC", "They pay the same"], 0,
     "Stations must sell candidates airtime at the lowest unit charge. Outside groups pay market rates, which climb near Election Day.", "lowest_unit_charge"),
    ("Does a 501(c)(4) nonprofit that runs election ads have to disclose its donors?", ["Always", "Generally no", "Only if over $1M"], 1,
     "It must report the ad spending, but generally not its donors unless they gave for that ad. That's why it's called dark money.", "nonprofit"),
    ("Can a corporation give unlimited money to a super PAC?", ["Yes", "No"], 0,
     "Since Citizens United and SpeechNow.org (2010), corporations, unions and individuals can give super PACs unlimited sums.", "super_pac"),
    ("Can a corporation give directly to a candidate's campaign?", ["Yes, up to $3,500", "No"], 1,
     "Corporations and unions can't contribute to federal candidates. They can form PACs, or give to super PACs.", "candidate_committee"),
    ("A party's coordinated spending in the last three weeks before Nov. 3 is disclosed when?", ["Within 24 hours", "Oct. 22", "Dec. 3"], 2,
     "Coordinated spending appears only on regular reports. Anything after Oct. 14 lands on the post-general report, due Dec. 3.", "coordinated"),
    ("What starts the clock on a 24- or 48-hour spending report?", ["Paying for the ad", "The ad reaching the public", "Booking the airtime"], 1,
     "The reporting clock starts on the dissemination date, when the ad first reaches the public.", "dissemination_date"),
    ("How often do House and Senate campaigns file their regular reports in an election year?", ["Monthly", "Quarterly, plus pre- and post-election", "Only after the election"], 1,
     "Candidate committees file quarterly, plus 12 days before and 30 days after each election. Monthly filing is only an option for PACs and parties.", "periodic"),
    ("A hybrid PAC can do what a super PAC can't. What?", ["Give directly to candidates from a limited account", "Take unlimited corporate money", "Keep its donors secret"], 0,
     "A hybrid PAC keeps two accounts: a limited one for contributions to candidates and an unlimited one for independent spending.", "hybrid_pac"),
    ("In the final 20 days, a campaign gets a $2,000 check. What must it do?", ["Nothing until the next report", "Report it within 48 hours", "Return it"], 1,
     "Contributions of $1,000 or more received in the last 20 days must be reported within 48 hours on Form 6.", "f6"),
]


def race_name(r):
    if r["office"] == "S":
        return f'the {r["state"]} Senate race'
    d = int(r["district"] or 0)
    return f'{r["state"]}\'s {"at-large" if d == 0 else f"{d}{_ord(d)} District"} House race'


def race_label(r):
    """Short label for answer buttons: "IA Senate", "IA's 1st District"."""
    if r["office"] == "S":
        return f'{r["state"]} Senate'
    d = int(r["district"] or 0)
    return f'{r["state"]}\'s {"at-large seat" if d == 0 else f"{d}{_ord(d)} District"}'


def short_name(name):
    """Filed committee names can run long ("... DBA CVA Action and DBA LIBRE Action")."""
    name = name.split(" DBA ")[0].split(" dba ")[0].strip()
    return name if len(name) <= 60 else name[:57].rstrip() + "..."


def _ord(n):
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _fmt(x):
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${round(x / 1e3)}K"


def _q(kind, prompt, options, answer, why, gloss, race_id=None):
    return {"kind": kind, "prompt": prompt, "options": options, "answer": answer, "why": why,
            "glossary": gloss, "race_id": race_id}


def offense_defense(rng, races, n):
    pool = [(r, p) for r in races for p in core.PARTIES
            if not r["holder_uncertain"] and r["holder_party"] and r[p]["total"] >= 250_000]
    out = []
    for r, p in rng.sample(pool, min(n, len(pool))):
        ans = 1 if r["holder_party"] == p else 0
        holder = PARTY[r["holder_party"]]
        out.append(_q("offense_defense",
                      f"Groups helping {PARTY[p]} have spent {_fmt(r[p]['total'])} in {race_name(r)}. Are {PARTY[p]} playing offense or defense?",
                      ["Offense", "Defense"], ans,
                      f"{holder} hold this seat now, so money helping {PARTY[p]} here is {'defense' if ans else 'offense'}.",
                      "offense", r["race_id"]))
    return out


def bigger_bet(rng, races, n):
    pool = [r for r in races if r["total"] >= 500_000]
    out, tries = [], 0
    while len(out) < n and tries < 200 and len(pool) >= 2:
        tries += 1
        a, b = rng.sample(pool, 2)
        hi, lo = max(a["total"], b["total"]), min(a["total"], b["total"])
        if hi < lo * 1.3:
            continue
        opts = [a, b]
        ans = 0 if a["total"] > b["total"] else 1
        out.append(_q("bigger_bet", "Which race has drawn more outside money so far in the general election?",
                      [race_label(a), race_label(b)], ans,
                      f"{race_label(opts[ans])}: {_fmt(opts[ans]['total'])}. {race_label(opts[1 - ans])}: {_fmt(opts[1 - ans]['total'])}.",
                      "helps", opts[ans]["race_id"]))
    return out


def split_question(rng, races, n):
    pool = [r for r in races if r.get("split_signal")]
    out = []
    for r in rng.sample(pool, min(n, len(pool))):
        s = r["split_signal"]
        ans = 0 if s["candidate_leader"] == "DEM" else 1
        cd, cr = r["cand"]["DEM"], r["cand"]["REP"]
        out.append(_q("split",
                      f"In {race_name(r)}, outside money favors {PARTY[s['outside_leader']]} by {_fmt(s['outside_gap'])}. Whose nominee has raised more?",
                      [f"The Democrat ({cd['name'].split(',')[0].title()})", f"The Republican ({cr['name'].split(',')[0].title()})"], ans,
                      f"Outside money and candidate money point opposite ways here: the {'Democrat' if ans == 0 else 'Republican'} leads fundraising by {_fmt(s['candidate_gap'])}.",
                      "split_signal", r["race_id"]))
    return out


def who_helps(rng, races, n):
    pool = [(r, s) for r in races for s in r["top_spenders"][:3] if s["amount"] >= 250_000 and s["name"]]
    out, seen = [], set()
    rng.shuffle(pool)
    # alternate the right answer between parties so the round can't be gamed
    want = ["DEM", "REP"] * n
    for r, s in pool:
        if len(out) >= n or s["name"] in seen or s["helps"] != want[len(out)]:
            continue
        seen.add(s["name"])
        kind = {"super_pac": "a super PAC", "party": "a party committee", "other": "an outside group"}.get(s["class"], "a group")
        out.append(_q("who_helps", f"{short_name(s['name'])} ({kind}) has spent {_fmt(s['amount'])} in {race_name(r)}. Which party is it helping?",
                      ["Democrats", "Republicans"], 0 if s["helps"] == "DEM" else 1,
                      f"Its spending supports the {'Democrat' if s['helps'] == 'DEM' else 'Republican'} or attacks their opponent. Every group's filings list who it backs or opposes.",
                      "support_oppose", r["race_id"]))
    return out


def rules(rng, n):
    return [_q("rules", q, opts, a, why, g) for q, opts, a, why, g in rng.sample(RULES, n)]


def make_puzzle(races: list, day: str) -> dict:
    """Deterministic for a given day and data."""
    rng = random.Random(hashlib.sha256(f"smart-money-{day}".encode()).hexdigest())
    races = sorted(races, key=lambda r: r["race_id"])
    qs = (offense_defense(rng, races, 2) + bigger_bet(rng, races, 2) + split_question(rng, races, 1)
          + who_helps(rng, races, 2))
    qs += rules(rng, 10 - len(qs))
    rng.shuffle(qs)
    number = (date.fromisoformat(day) - LAUNCH).days + 1
    return {"day": day, "number": number, "questions": qs}
