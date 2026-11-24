import tempfile
import unittest
from pathlib import Path

from collection_desk.allocate import quota_frontier, reliable_stock, request_bundles
from collection_desk.adjudicate import adjudicate, support_envelope, verification_queue
from collection_desk.io import load_packet
from collection_desk.ledger import Ledger, requery


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class DeskAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.packet = load_packet(DATA)

    def test_window_late_receipts_are_not_completions(self):
        report = adjudicate(self.packet, asof=38)
        by_album = {row["album"]: row for row in report["albums"]}

        self.assertEqual(by_album["A1"]["status"], "incomplete")
        self.assertIn("vessel", by_album["A1"]["missing_slots"])
        self.assertEqual(by_album["A4"]["status"], "incomplete")
        self.assertIn("vessel", by_album["A4"]["missing_slots"])

    def test_early_observation_end_is_not_zero(self):
        report = adjudicate(self.packet, asof=38)
        by_album = {row["album"]: row for row in report["albums"]}

        for album in ("A5", "A7", "A11", "A12"):
            self.assertEqual(by_album[album]["status"], "insufficient", album)
            self.assertEqual(by_album[album]["reason"], "access_truncated", album)

    def test_confirmed_identities_accept_slots(self):
        report = adjudicate(self.packet, asof=38)
        by_album = {row["album"]: row for row in report["albums"]}

        self.assertEqual([x["position"] for x in by_album["A8"]["accepted_slots"]], ["bird", "vessel"])
        self.assertEqual([x["position"] for x in by_album["A9"]["accepted_slots"]], ["bird"])
        queue_albums = {item["album"] for item in verification_queue(self.packet, 38)}
        self.assertIn("A8", queue_albums)  # D2 receipt
        self.assertNotIn("A1", queue_albums)

    def test_sent_cards_are_locked_and_not_reassigned(self):
        stock = {row["mark"]: row for row in reliable_stock(self.packet, 38)}
        self.assertFalse(stock["C11"]["reliable_free"])
        self.assertTrue(stock["C16"]["reliable_free"])

    def test_stock_frontier_never_uses_one_physical_card_twice(self):
        frontier = quota_frontier(self.packet, asof=38, decision_day=None)
        quota_two = next(row for row in frontier if row["quota"] == 2)
        self.assertEqual(quota_two["reliable_additional"], 2)
        plan = quota_two["candidates"][0]
        marks = plan["marks"]
        self.assertEqual(len(marks), len(set(marks)))
        self.assertEqual(plan["protected"], 1)

        # C14 is the only free blue wheel; A9 and A12 cannot both receive it.
        albums = {item["album"] for item in plan["allocations"]}
        self.assertIn("A9", albums)
        self.assertIn("A11", albums)

    def test_cutoff_38_cannot_promise_fresh_worst_case_delivery(self):
        rows = request_bundles(self.packet, asof=38, decision_day=38)
        for row in rows:
            self.assertEqual(row["feasible_bundles"], [], row["album"])

    def test_cutoff_34_has_reliable_protected_bundle_without_locked_c18(self):
        rows = {row["album"]: row for row in request_bundles(self.packet, asof=34, decision_day=34)}
        marks = [bundle["marks"] for bundle in rows["A9"]["feasible_bundles"]]
        self.assertIn(("C16", "C14"), marks)
        for row in rows.values():
            for bundle in row["feasible_bundles"]:
                self.assertNotIn("C18", bundle["marks"])

    def test_support_envelope_reports_single_global_distribution(self):
        envelope = support_envelope(self.packet, 38)
        self.assertEqual((envelope["min_complete_scale"], envelope["max_complete_scale"]), (0, 0))
        self.assertEqual(envelope["distinct_missing_distributions"], [{"bird": 7, "vessel": 9, "wheel": 8}])

    def test_receipt_event_requery_completes_a8_and_preserves_source(self):
        before = (DATA / "commitments.tsv").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "events.jsonl")
            ledger.card_received("A8", "C11", 39, "wheel-b")
            result = requery(self.packet, ledger, asof=40)
            a8 = next(row for row in result["albums"] if row["album"] == "A8")
            self.assertEqual(a8["status"], "complete")
            self.assertEqual(a8["missing_slots"], [])
        after = (DATA / "commitments.tsv").read_text(encoding="utf-8")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
