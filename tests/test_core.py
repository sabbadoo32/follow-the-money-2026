import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ftm import cadence, core, run

CFG = run.CFG


def row(**kw):
    base = {"source": "bulk", "kind": "ie", "is_notice": True, "committee_id": "C1", "committee_name": "PAC ONE",
            "candidate_id": "H6MI08001", "candidate_name": "SMITH, ANN", "office": "H", "state": "MI", "district": "08",
            "row_party": "", "support_oppose": "S", "amount": 1000.0, "dissemination_date": "2026-09-10",
            "filed_at": "2026-09-11", "file_num": "100", "prev_file_num": "", "amends": [], "transaction_id": "T1",
            "image_number": "1", "election_type": "G", "payee": "Acme Media", "purpose": "TV", "dedupe_key": ""}
    base.update(kw)
    return base


CANDS = {
    "H6MI08001": {"candidate_id": "H6MI08001", "name": "SMITH, ANN", "party": "DEM", "election_yr": "2026", "state": "MI", "office": "H", "district": "08", "ici": "C", "status": "C"},
    "H6MI08002": {"candidate_id": "H6MI08002", "name": "JONES, BOB", "party": "REP", "election_yr": "2026", "state": "MI", "office": "H", "district": "08", "ici": "I", "status": "C"},
    "H6MI08003": {"candidate_id": "H6MI08003", "name": "GREEN, CY", "party": "GRE", "election_yr": "2026", "state": "MI", "office": "H", "district": "08", "ici": "C", "status": "C"},
    "S4PA00001": {"candidate_id": "S4PA00001", "name": "OLD, SEN", "party": "DEM", "election_yr": "2024", "state": "PA", "office": "S", "district": "00", "ici": "I", "status": "C"},
}
CMTES = {"C1": {"type": "O", "name": "PAC ONE"}, "CP": {"type": "Y", "name": "DCCC"}}
LEGS = [{"name": {"first": "Bob", "last": "Jones"}, "id": {"fec": ["H6MI08002"]},
         "terms": [{"type": "rep", "state": "MI", "district": 8, "party": "Republican"}]}]


def races():
    return core.build_races(CANDS, LEGS, 2026, CFG)


class Attribution(unittest.TestCase):
    def go(self, rows):
        rows, _ = core.dedupe(rows)
        return core.attribute(rows, CANDS, CMTES, races(), CFG)

    def test_support_dem_helps_dem(self):
        kept, _ = self.go([row()])
        self.assertEqual(kept[0]["helps"], "DEM")

    def test_oppose_rep_helps_dem_and_oppose_dem_helps_rep(self):
        kept, _ = self.go([row(candidate_id="H6MI08002", support_oppose="O", transaction_id="a"),
                           row(support_oppose="O", transaction_id="b")])
        self.assertEqual(sorted(r["helps"] for r in kept), ["DEM", "REP"])

    def test_primary_third_party_other_cycle_dropped(self):
        kept, b = self.go([row(election_type="P", transaction_id="a"), row(candidate_id="H6MI08003", transaction_id="b"),
                           row(candidate_id="S4PA00001", office="S", state="PA", transaction_id="c")])
        self.assertEqual(kept, [])
        self.assertEqual((len(b["primary_or_other"]), len(b["third_party"]), len(b["other_cycle"])), (1, 1, 1))

    def test_blank_candidate_id_recovered_by_name(self):
        kept, b = self.go([row(candidate_id="", candidate_name="JONES, ROBERT", support_oppose="O")])
        self.assertEqual(kept[0]["candidate_id"], "H6MI08002")
        self.assertEqual(kept[0]["helps"], "DEM")

    def test_unknown_candidate_unmatched(self):
        _, b = self.go([row(candidate_id="", candidate_name="NOBODY, X")])
        self.assertEqual(len(b["unmatched"]), 1)

    def test_huge_row_held_until_confirmed(self):
        r = row(amount=9_000_000_000)
        kept, b = self.go([r])
        self.assertEqual((len(kept), len(b["held"])), (0, 1))
        rows, _ = core.dedupe([row(amount=9_000_000_000)])
        kept, _ = core.attribute(rows, CANDS, CMTES, races(), CFG, confirmed={rows[0]["dedupe_key"]})
        self.assertEqual(len(kept), 1)

    def test_efile_election_type_from_primary_calendar(self):
        cut = {"MI": "2026-08-04"}
        rows, _ = core.dedupe([row(election_type=None, dissemination_date="2026-07-01", transaction_id="a"),
                               row(election_type=None, dissemination_date="2026-09-01", transaction_id="b")])
        kept, b = core.attribute(rows, CANDS, CMTES, races(), CFG, cutoffs=cut)
        self.assertEqual((len(kept), len(b["primary_or_other"])), (1, 1))


class Dedupe(unittest.TestCase):
    def test_amendment_replaces_original(self):
        rows, st = core.dedupe([row(file_num="100", amount=500), row(file_num="101", prev_file_num="100", amount=700)])
        self.assertEqual([r["amount"] for r in rows], [700])
        self.assertEqual(st["superseded_amendments"], 1)

    def test_amendment_chain(self):
        rows, _ = core.dedupe([row(file_num="1"), row(file_num="2", prev_file_num="1"), row(file_num="3", prev_file_num="2")])
        self.assertEqual([r["file_num"] for r in rows], ["3"])

    def test_efile_amends_field(self):
        rows, _ = core.dedupe([row(file_num="1"), row(source="efile", file_num="2", amends=["1"], transaction_id="X")])
        self.assertEqual([r["file_num"] for r in rows], ["2"])

    def test_same_transaction_two_sources_counted_once(self):
        rows, _ = core.dedupe([row(), row(source="efile")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "bulk")

    def test_notice_repeated_on_periodic_counted_once_periodic_wins(self):
        n = row(file_num="200", transaction_id="N1", payee="ACME MEDIA, INC")
        p = row(source="processed", is_notice=False, file_num="300", transaction_id="P1", payee="Acme Media Inc")
        rows, st = core.dedupe([n, p])
        self.assertEqual([r["source"] for r in rows], ["processed"])
        self.assertEqual(st["notice_repeated_in_periodic"], 1)

    def test_notice_match_is_one_to_one(self):
        rows, _ = core.dedupe([row(file_num="200", transaction_id="N1"), row(file_num="201", transaction_id="N2"),
                               row(source="processed", is_notice=False, file_num="300", transaction_id="P1")])
        self.assertEqual(len(rows), 2)

    def test_same_file_identical_items_both_kept(self):
        rows, _ = core.dedupe([row(transaction_id="A"), row(transaction_id="B")])
        self.assertEqual(len(rows), 2)

    def test_future_dates_pinned(self):
        rows, st = core.dedupe([row(dissemination_date="2026-10-09")], today="2026-09-22")
        self.assertEqual(rows[0]["dissemination_date"], "2026-09-22")


class Rollup(unittest.TestCase):
    def setUp(self):
        rows, _ = core.dedupe([
            row(amount=60_000, transaction_id="a", dissemination_date="2026-09-01"),
            row(amount=50_000, transaction_id="b", dissemination_date="2026-09-20"),
            row(committee_id="CP", amount=10, transaction_id="c", dissemination_date="2026-09-15"),
            row(candidate_id="H6MI08001", support_oppose="O", amount=5_000, transaction_id="d"),
        ])
        self.kept, _ = core.attribute(rows, CANDS, CMTES, races(), CFG)
        self.roll = core.rollup(self.kept, races(), CFG, "2026-09-22")

    def test_split_and_side(self):
        r = self.roll["H-MI-08"]
        self.assertEqual(r["holder_party"], "REP")
        self.assertEqual((r["DEM"]["outside"], r["DEM"]["party_ie"], r["DEM"]["side"]), (110_000, 10, "offense"))
        self.assertEqual((r["REP"]["total"], r["REP"]["side"]), (5_000, "defense"))
        self.assertEqual(r["DEM"]["first_party_dollar"], "2026-09-15")
        self.assertEqual(r["DEM"]["last_7d"], 50_000)

    def test_headline(self):
        h = core.headline(self.roll, CFG)
        self.assertEqual(h["H_DEM"]["offense_share"], 1.0)
        self.assertEqual(h["H_REP"]["offense_share"], 0.0)
        self.assertEqual((h["H_DEM"]["races_in_play"], h["H_DEM"]["party_footprint"]), (1, 1))

    def test_rollup_rebuilt_not_accumulated(self):
        again = core.rollup(self.kept, races(), CFG, "2026-09-22")
        self.assertEqual(again["H-MI-08"]["total"], self.roll["H-MI-08"]["total"])

    def test_crossings_dated_by_data(self):
        c = {(a["type"], a["party"]): a["crossed_on"] for a in core.crossings(self.kept, CFG)}
        self.assertEqual(c[("first_100k", "DEM")], "2026-09-20")
        self.assertEqual(c[("first_party_dollar", "DEM")], "2026-09-15")
        self.assertNotIn(("first_1m", "DEM"), c)

    def test_merge_alerts_keeps_detected_at(self):
        cur = core.crossings(self.kept, CFG)
        first = core.merge_alerts([], cur, "2026-09-22T10:00:00Z", first_run=True)
        second = core.merge_alerts(first, core.crossings(self.kept, CFG), "2026-09-23T10:00:00Z", first_run=False)
        self.assertEqual({a["detected_at"] for a in first}, {a["detected_at"] for a in second})


class Races(unittest.TestCase):
    def test_redistricting_flags_holder_uncertain(self):
        cands = dict(CANDS)
        cands["H6MI08002"] = {**CANDS["H6MI08002"], "district": "09"}  # member now files in a renumbered district
        rs = core.build_races(cands, LEGS, 2026, CFG)
        self.assertTrue(rs["H-MI-09"]["holder_uncertain"])
        self.assertTrue(rs["H-MI-08"]["holder_uncertain"])

    def test_clean_seat_not_uncertain(self):
        self.assertFalse(races()["H-MI-08"]["holder_uncertain"])


class Cadence(unittest.TestCase):
    S = CFG["schedule"]

    def t(self, s):
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

    def test_windows(self):
        self.assertTrue(cadence.should_run(self.t("2026-10-01T05:07"), "7 * * * *", self.S))
        self.assertFalse(cadence.should_run(self.t("2026-10-01T05:37"), "37 * * * *", self.S))
        self.assertTrue(cadence.should_run(self.t("2026-10-20T05:37"), "37 * * * *", self.S))
        self.assertFalse(cadence.should_run(self.t("2026-11-10T05:07"), "7 * * * *", self.S))
        self.assertTrue(cadence.should_run(self.t("2026-11-10T11:07"), "7 * * * *", self.S))
        self.assertFalse(cadence.should_run(self.t("2026-12-20T11:07"), "7 * * * *", self.S))
        self.assertTrue(cadence.should_run(self.t("2026-12-20T11:07"), None, self.S))


class FailureLeavesLastGoodData(unittest.TestCase):
    def test_failed_check_does_not_touch_site(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            off = tmp / "off"
            off.mkdir()
            (off / "ie.csv").write_text("cand_id,cand_name\n")  # truncated download
            for f in ("cm.txt", "cn.txt"):
                (off / f).write_text("")
            (off / "leg.json").write_text("[]")
            site = tmp / "site" / "data"
            site.mkdir(parents=True)
            (site / "races.json").write_text('{"races":["last good"]}')
            code = run.main(["--offline", str(off), "--out", str(tmp / "site")])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads((site / "races.json").read_text()), {"races": ["last good"]})
        finally:
            shutil.rmtree(tmp)


class CandidateMoney(unittest.TestCase):
    SUMMARY = {"H6MI08001": {"receipts": 3_000_000, "coh": 1_000_000, "indiv": 0, "from_party": 0, "through": "2026-06-30"},
               "H6MI08002": {"receipts": 1_000_000, "coh": 400_000, "indiv": 0, "from_party": 5000, "through": "2026-06-30"},
               "H6MI08004": {"receipts": 9_000_000, "coh": 0, "indiv": 0, "from_party": 0, "through": "2026-03-31"}}

    def cands(self, loser=False, twin=False):
        c = dict(CANDS)
        if loser:  # a primary loser who out-raised the nominee
            c["H6MI08004"] = {**CANDS["H6MI08001"], "candidate_id": "H6MI08004", "name": "RICH, LOSER"}
        if twin:
            c["H6MI08004"] = {**CANDS["H6MI08001"], "candidate_id": "H6MI08004", "name": "SMITH, OTHER"}
        return c

    def run_(self, rows, cands):
        rs = core.build_races(cands, LEGS, 2026, CFG)
        rows, _ = core.dedupe(rows)
        kept, _ = core.attribute(rows, cands, CMTES, rs, CFG)
        return kept, rs, core.pick_nominees(kept, rs, cands, self.SUMMARY, CFG)

    def test_summary_parse(self):
        f = ["H1"] + [""] * 4 + ["123.5", "0", "100", "0", "0", "23.5"] + ["0"] * 6 + ["50"] + [""] * 8 + ["7", "06/30/2026"]
        s = core.load_candidate_summary(["|".join(f)])
        self.assertEqual((s["H1"]["receipts"], s["H1"]["coh"], s["H1"]["from_party"], s["H1"]["through"]), (123.5, 23.5, 7, "2026-06-30"))

    def test_nominee_is_ie_target_not_top_fundraiser(self):
        _, _, n = self.run_([row(amount=50_000)], self.cands(loser=True))
        self.assertEqual((n["H-MI-08"]["DEM"]["candidate_id"], n["H-MI-08"]["DEM"]["basis"]), ("H6MI08001", "ie"))

    def test_below_floor_falls_back_to_receipts(self):
        _, _, n = self.run_([row(amount=500)], self.cands(loser=True))
        self.assertEqual((n["H-MI-08"]["DEM"]["candidate_id"], n["H-MI-08"]["DEM"]["basis"]), ("H6MI08004", "receipts"))

    def test_namesake_dominant_ie_target_kept_not_bigger_war_chest(self):
        # SC 2026 pattern: the new nominee shares a last name with a better-funded predecessor
        _, _, n = self.run_([row(amount=50_000)], self.cands(twin=True))
        self.assertEqual((n["H-MI-08"]["DEM"]["candidate_id"], n["H-MI-08"]["DEM"]["basis"]), ("H6MI08001", "ie"))

    def test_namesake_split_ie_flagged(self):
        _, _, n = self.run_([row(amount=50_000, transaction_id="a"),
                             row(candidate_id="H6MI08004", candidate_name="SMITH, OTHER", amount=40_000, transaction_id="b")],
                            self.cands(twin=True))
        self.assertEqual(n["H-MI-08"]["DEM"]["basis"], "name_collision")

    def test_split_signal(self):
        kept, rs, n = self.run_([row(amount=50_000, transaction_id="a"),
                                 row(candidate_id="H6MI08002", amount=900_000, transaction_id="b")], self.cands())
        roll = core.rollup(kept, rs, CFG, "2026-09-22")["H-MI-08"]
        sig = core.split_signal(roll, n["H-MI-08"], 250_000)
        self.assertEqual((sig["outside_leader"], sig["candidate_leader"]), ("REP", "DEM"))
        n["H-MI-08"]["REP"]["basis"] = "receipts"
        self.assertIsNone(core.split_signal(roll, n["H-MI-08"], 250_000))
        n["H-MI-08"]["REP"].update(basis="ie", reported=False)  # no summary row reads as $0; must not flag
        self.assertIsNone(core.split_signal(roll, n["H-MI-08"], 250_000))

    def test_no_split_when_both_agree_or_gap_small(self):
        kept, rs, n = self.run_([row(amount=900_000, transaction_id="a"),
                                 row(candidate_id="H6MI08002", amount=50_000, transaction_id="b")], self.cands())
        roll = core.rollup(kept, rs, CFG, "2026-09-22")["H-MI-08"]
        self.assertIsNone(core.split_signal(roll, n["H-MI-08"], 250_000))
        self.assertIsNone(core.split_signal(roll, n["H-MI-08"], 5_000_000))


class FreshCandidateMoney(unittest.TestCase):
    def nominees(self, **kw):
        c = {"candidate_id": "H1", "name": "A", "basis": "ie", "reported": True, "committee_id": "C9",
             "receipts": 1_000_000, "coh": 500_000, "through": "2026-06-30"}
        c.update(kw)
        return {"H-MI-08": {"DEM": c}}

    def test_latest_report_prefers_later_coverage_then_amendment(self):
        rows = [{"committee_id": "C9", "coverage_end_date": "2026-06-30", "total_receipts_ytd": 1, "file_number": 5},
                {"committee_id": "C9", "coverage_end_date": "2026-09-30", "total_receipts_ytd": 2, "file_number": 6},
                {"committee_id": "C9", "coverage_end_date": "2026-09-30", "total_receipts_ytd": 3, "file_number": 7}]
        self.assertEqual(core.latest_reports(rows)["C9"]["receipts"], 3)

    def test_newer_efile_report_overrides_older_summary(self):
        n = self.nominees()
        core.apply_fresh_money(n, {"C9": {"through": "2026-09-30", "receipts": 2_000_000, "coh": 900_000, "file_number": 1, "report": "Q3"}}, {})
        self.assertEqual((n["H-MI-08"]["DEM"]["receipts"], n["H-MI-08"]["DEM"]["through"]), (2_000_000, "2026-09-30"))

    def test_older_efile_report_ignored(self):
        n = self.nominees(through="2026-07-29")
        core.apply_fresh_money(n, {"C9": {"through": "2026-06-30", "receipts": 1, "coh": 1, "file_number": 1, "report": "Q2"}}, {})
        self.assertEqual(n["H-MI-08"]["DEM"]["receipts"], 1_000_000)

    def test_new_committee_first_report_marks_reported(self):
        n = self.nominees(reported=False, receipts=0, coh=0, through=None)
        core.apply_fresh_money(n, {"C9": {"through": "2026-09-30", "receipts": 4_000_000, "coh": 3_000_000, "file_number": 1, "report": "Q3"}}, {})
        self.assertTrue(n["H-MI-08"]["DEM"]["reported"])

    def test_parse_f6_raw_filing(self):
        fs = "\x1c"
        text = "\n".join([fs.join(["HDR", "FEC", "8.5"]),
                          fs.join(["F6N", "C00843763", "", "McBride for Delaware Inc."]),
                          fs.join(["F65", "C00843763", "16290867", "PAC", "FMC Corporation Good Government Program", "", "", "", "", "",
                                   "2929 Walnut St", "", "Philadelphia", "PA", "191045054", "C00033704", "20260911", "5000.00", "", ""]),
                          fs.join(["F65", "C00843763", "16290868", "IND", "", "DOE", "JANE", "", "", "",
                                   "1 Main St", "", "Dover", "DE", "19901", "", "20260912", "3300.00", "", ""])])
        items = core.parse_f6(text)
        self.assertEqual([(i["date"], i["amount"]) for i in items], [("2026-09-11", 5000.0), ("2026-09-12", 3300.0)])
        self.assertEqual(items[1]["from"], "JANE DOE")

    def test_48h_only_counts_after_report_and_respects_amendments(self):
        filings = {"1": {"committee_id": "C9", "amends": [], "items": [{"date": "2026-10-16", "amount": 5000}]},
                   "2": {"committee_id": "C9", "amends": ["1"], "items": [{"date": "2026-10-16", "amount": 6000},
                                                                          {"date": "2026-06-01", "amount": 999999}]}}
        n = self.nominees(through="2026-10-14")
        core.apply_fresh_money(n, {}, core.live_f6(filings))
        c = n["H-MI-08"]["DEM"]
        self.assertEqual((c["late_48h"], c["late_48h_count"], c["late_48h_through"]), (6000, 1, "2026-10-16"))


class KeyedPathSmoke(unittest.TestCase):
    """Runs build() down the API-key path against a fake OpenFEC, so wiring bugs surface before the key exists."""

    def test_keyed_build_with_fake_api(self):
        from unittest import mock
        from ftm import sources
        S = Path(__file__).parent / "fixtures"
        tmp = Path(tempfile.mkdtemp())

        class FakeAPI:
            calls = 0
            def __init__(self, *a, **k): pass
            def get(self, path, **p):
                FakeAPI.calls += 1
                return {"results": [], "pagination": {"pages": 1, "last_indexes": None}}
            def pages(self, path, **p):
                FakeAPI.calls += 1
                if path == "/efile/reports/house-senate/":
                    yield {"committee_id": "CPCC1", "coverage_end_date": "2026-09-30", "total_receipts_ytd": 7_000_000,
                           "cash_on_hand_end_period": 2_000_000, "file_number": 99, "document_description": "OCTOBER QUARTERLY 2026",
                           "receipt_date": "2026-10-15"}
                if path == "/efile/filings/":
                    yield {"file_number": 500, "committee_id": "CPCC1", "receipt_date": "2026-10-20", "fec_url": "x"}

        f65 = "\x1c".join(["F65", "CPCC1", "t", "IND", "", "DOE", "JO", "", "", "", "a", "", "c", "MI", "1", "", "20261019", "2500.00"])
        with mock.patch.object(sources, "OpenFEC", FakeAPI), \
             mock.patch.object(sources, "api_key", lambda: "k"), \
             mock.patch.object(sources, "fetch", lambda url, **k: (f65.encode(), {})), \
             mock.patch.object(sources, "bulk_ie", lambda u: ([{"cand_id": "H6MI08001", "cand_name": "SMITH, ANN", "spe_id": "C1", "spe_nam": "PAC ONE",
                    "ele_type": "G", "can_office_state": "MI", "can_office_dis": "08", "can_office": "H", "cand_pty_aff": "DEM",
                    "exp_amo": "100", "exp_date": "", "agg_amo": "", "sup_opp": "S", "pur": "TV", "pay": "X", "file_num": str(i),
                    "amndt_ind": "N", "tran_id": f"T{i}", "image_num": "1", "receipt_dat": "20-OCT-26", "fec_election_yr": "2026",
                    "prev_file_num": "", "dissem_dt": "19-OCT-26"} for i in range(6000)], "lm")), \
             mock.patch.object(sources, "bulk_zip_lines", lambda u: ((
                    ["H6MI08001|SMITH, ANN|DEM|2026|MI|H|08|C|C|CPCC1", "H6MI08002|JONES, BOB|REP|2026|MI|H|08|I|C|CPCC2"]
                    if "cn26" in u else ["C1|PAC ONE|||||||U|O|"] if "cm26" in u else []), "lm")), \
             mock.patch.object(sources, "legislators", lambda u: LEGS), \
             mock.patch.object(run, "STATE", tmp):
            b = run.build(datetime(2026, 10, 21, 12, tzinfo=timezone.utc))
        shutil.rmtree(tmp)
        c = b["roll"]["H-MI-08"]["cand"]["DEM"]
        self.assertEqual((c["receipts"], c["through"], c["late_48h"]), (7_000_000, "2026-09-30", 2500))
        self.assertGreater(FakeAPI.calls, 3)


if __name__ == "__main__":
    unittest.main()
