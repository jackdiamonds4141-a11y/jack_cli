import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure the base and Core directories are in the path
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, base_dir)
sys.path.insert(0, os.path.join(base_dir, 'Core'))

from Core.epoch_coordinator import EpochBarrier
from Core.halting import HaltingController
from Core.act_accumulator import DiscreteACTAccumulator

class TestEpochBarrier(unittest.TestCase):
    def setUp(self):
        self.barrier = EpochBarrier(expected_workers=3, timeout=5.0)
        self.barrier.start_epoch()

    def test_quorum_success_triggers_ready(self):
        self.assertFalse(self.barrier.checkin("worker_1"))
        self.assertFalse(self.barrier.checkin("worker_2"))
        self.assertTrue(self.barrier.checkin("worker_3"))

    @patch('time.time')
    def test_timeout_safety_prevents_infinite_hang(self, mock_time):
        mock_time.return_value = 1000.0
        self.barrier.start_epoch()
        
        self.barrier.checkin("worker_1")
        self.assertFalse(self.barrier.is_ready())
        
        mock_time.return_value = 1005.1
        self.assertTrue(self.barrier.is_ready(), "Barrier must unlock on timeout to prevent deadlock")


class TestHybridHaltingController(unittest.TestCase):
    def setUp(self):
        self.controller = HaltingController()

    def test_adversary_is_never_halted_fake_halting(self):
        for glow in [0.0, 5.0, 50.0]:
            result = self.controller.evaluate_worker("adv_1", "ADVERSARY", epoch=2, glow=glow)
            self.assertFalse(result, "Adversaries must always remain active to maintain social pressure")

    def test_builder_with_low_glow_is_halted_real_halting(self):
        result = self.controller.evaluate_worker("build_1", "BUILDER", epoch=1, glow=15.0, median_glow=40.0)
        self.assertTrue(result)
        self.assertIn("build_1", self.controller.halted_builders)

    def test_get_active_workers_filters_halted_builders(self):
        self.controller.halted_builders.add("build_2")
        all_workers = ["adv_1", "build_1", "build_2"]
        active = self.controller.get_active_workers(all_workers)
        
        self.assertIn("adv_1", active)
        self.assertIn("build_1", active)
        self.assertNotIn("build_2", active)


class TestDiscreteACTAccumulator(unittest.TestCase):
    def setUp(self):
        self.accumulator = DiscreteACTAccumulator(tau=0.99)

    def test_remainder_trick_and_sorting(self):
        c1 = MagicMock(claim_id="c1", status="VALIDATED", epoch_validated=1, endorsements=2)
        c2 = MagicMock(claim_id="c2", status="VALIDATED", epoch_validated=2, endorsements=2)
        c3 = MagicMock(claim_id="c3", status="VALIDATED", epoch_validated=3, endorsements=2)
        c4 = MagicMock(claim_id="c4", status="VALIDATED", epoch_validated=4, endorsements=5)
        
        claims = [c3, c1, c4, c2]
        
        weights = self.accumulator.compute_weights(claims)
        
        self.assertAlmostEqual(weights.get("c1", 0.0), 0.4)
        self.assertAlmostEqual(weights.get("c2", 0.0), 0.4)
        self.assertAlmostEqual(weights.get("c3", 0.0), 0.19)
        self.assertEqual(weights.get("c4", 0.0), 0.0)

    def test_compile_weighted_report_excludes_zero_weights(self):
        c1 = MagicMock(claim_id="c1", text="Good Claim")
        c2 = MagicMock(claim_id="c2", text="Ignored Claim")
        weights = {"c1": 0.5, "c2": 0.0}
        
        report = self.accumulator.compile_weighted_report([c1, c2], weights)
        self.assertIn("Good Claim", report)
        self.assertIn("0.500", report)
        self.assertNotIn("Ignored Claim", report)

if __name__ == '__main__':
    unittest.main()
