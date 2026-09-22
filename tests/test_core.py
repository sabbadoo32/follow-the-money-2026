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


if __name__ == "__main__":
    unittest.main()
