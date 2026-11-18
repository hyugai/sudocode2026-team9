import unittest

from dataset.pipeline.selection import select_plans


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.plans = [{"journey_id": f"J{i:04d}", "sessions": [None] * size}
                      for i, size in enumerate((3, 3, 2, 2), 1)]

    def test_exact_count_keeps_whole_journeys_and_prefers_earliest_indices(self):
        selected = select_plans(self.plans, samples=5)
        self.assertEqual([p["journey_id"] for p in selected], ["J0001", "J0003"])
        self.assertEqual(sum(len(p["sessions"]) for p in selected), 5)
        self.assertEqual(selected, select_plans(self.plans, samples=5))
        self.assertEqual(select_plans(self.plans, samples=3), self.plans[:1])

    def test_invalid_or_impossible_counts_are_rejected_without_truncation(self):
        for count in (0, -1, True, 1.5, 1, 11):
            with self.subTest(count=count), self.assertRaises(ValueError):
                select_plans(self.plans, samples=count)
        with self.assertRaises(ValueError):
            select_plans(self.plans, limit=2, samples=5)
        self.assertEqual(select_plans(self.plans, limit=2), self.plans[:2])
        self.assertEqual(select_plans(self.plans), self.plans)

    def test_m1_shape_selects_three_and_two_sessions(self):
        plans = [{"journey_id": f"J{i+1:04d}", "sessions": [None] * (3 if i < 20 else 2)} for i in range(50)]
        self.assertEqual([p["journey_id"] for p in select_plans(plans, samples=5)], ["J0001", "J0021"])

    def test_explicit_new_journeys_preserve_plan_order_and_reject_ambiguity(self):
        self.assertEqual(select_plans(self.plans, journey_ids=["J0003", "J0002"]), self.plans[1:3])
        for ids in ([], ["missing"], ["J0001", "J0001"]):
            with self.assertRaises(ValueError): select_plans(self.plans, journey_ids=ids)
        with self.assertRaises(ValueError): select_plans(self.plans, samples=5, journey_ids=["J0001"])


if __name__ == "__main__":
    unittest.main()
