import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure the base and Core directories are in the path
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, base_dir)
sys.path.insert(0, os.path.join(base_dir, 'Core'))

from data_manager import ContextNormalizer, PromptAssembler, TokenBudget
from social_state_machine import EpochManager

class TestContextNormalizer(unittest.TestCase):
    def setUp(self):
        self.budget = TokenBudget()
        self.normalizer = ContextNormalizer(budget=self.budget)

    def test_calculate_decay_weight_applies_epoch_age_and_anchor_bonus(self):
        claim = MagicMock()
        claim.epoch_born = 2
        claim.cites_anchor = True
        claim.glow = 0.9

        import math
        weight = self.normalizer.calculate_decay_weight(claim, current_epoch=5)
        # Using depth_scaler = 0.5 + 0.1 * 5 = 1.0
        # claim.anchor_touch resolves as MagicMock (Truthy), so anchor_bonus = 1.2
        expected = math.exp(-1.0 * 3) * 0.9 * 1.2
        self.assertAlmostEqual(weight, expected, places=5)

    def test_tombstone_refuted_compresses_claims(self):
        claims = []
        for i in range(3):
            m = MagicMock()
            m.id = f"ref-{i}"
            m.text = f"Text {i}" * 10
            m.refuted_epoch = 1
            claims.append(m)
        
        compressed = self.normalizer.tombstone_refuted(claims)
        lines = compressed.split('\n')
        self.assertEqual(len(lines), 3)
        self.assertLess(len(compressed), 700)
        self.assertIn("REFUTED", compressed)

class TestPromptAssembler(unittest.TestCase):
    def setUp(self):
        self.budget = TokenBudget()
        self.normalizer = ContextNormalizer(self.budget)
        self.assembler = PromptAssembler(self.budget, self.normalizer)

    def test_assembled_xml_strictly_maintains_slot_order(self):
        registry = MagicMock()
        registry.get_verified.return_value = []
        registry.get_active_sorted_by_weight.return_value = []
        registry.get_refuted.return_value = []

        xml = self.assembler.assemble("ANCHOR_DATA", registry, 2)
        
        epoch_idx = xml.find("<epoch_counter")
        anchor_idx = xml.find("<anchor priority")
        verified_idx = xml.find("<verified_axioms>")
        active_idx = xml.find("<active_residue>")
        refuted_idx = xml.find("<refutation_tombstones>")
        directive_idx = xml.find("<execution_directive>")
        
        self.assertTrue(0 <= epoch_idx < anchor_idx < verified_idx < active_idx < refuted_idx < directive_idx)
        self.assertIn("ANCHOR_DATA", xml)

class TestEpochManager(unittest.TestCase):
    def setUp(self):
        self.assembler = MagicMock()
        self.manager = EpochManager(assembler=self.assembler, anchor="TEST_ANCHOR", max_epochs=3)
        self.manager._inject_diversity_stimulus = MagicMock()
        self.manager.compile_final_blueprint = MagicMock(return_value="FINAL_BLUEPRINT")

    def test_act_halting_gate_short_circuits_when_no_active_claims(self):
        registry = MagicMock()
        registry.effective_decay = 0.5
        registry.get_active.return_value = []
        worker_pool = MagicMock()

        result = self.manager.execute_flush_and_step(registry, worker_pool)
        self.assertEqual(result, "FINAL_BLUEPRINT")
        self.assertEqual(self.manager.epoch, 0)

    def test_hard_depth_limit_forces_final_blueprint_at_epoch_gte_3(self):
        registry = MagicMock()
        registry.effective_decay = 0.5
        registry.get_active.return_value = [MagicMock()]
        worker_pool = MagicMock()
        
        self.manager.epoch = 2
        result = self.manager.execute_flush_and_step(registry, worker_pool)
        self.assertEqual(self.manager.epoch, 3)
        self.assertEqual(result, "FINAL_BLUEPRINT")

    def test_spectral_brake_triggers_diversity_injection(self):
        registry = MagicMock()
        registry.effective_decay = 0.90
        registry.get_active.return_value = [MagicMock()]
        worker_pool = MagicMock()
        
        self.manager.execute_flush_and_step(registry, worker_pool)
        self.manager._inject_diversity_stimulus.assert_called_once_with(worker_pool)

    def test_volatile_wipe_calls_clear_on_all_worker_buffers_during_standard_step(self):
        registry = MagicMock()
        registry.effective_decay = 0.5
        registry.get_active.return_value = [MagicMock()]
        
        worker_pool = MagicMock()
        worker1 = MagicMock()
        worker2 = MagicMock()
        worker_pool.__iter__.return_value = [worker1, worker2]
        
        result = self.manager.execute_flush_and_step(registry, worker_pool)
        
        self.assertEqual(result, "STEP_COMPLETE")
        worker1.uds_queue.clear.assert_called_once()
        worker1.context_buffer.clear.assert_called_once()
        worker2.uds_queue.clear.assert_called_once()
        worker2.context_buffer.clear.assert_called_once()
        
        self.manager.assembler.assemble.assert_called_once()
        worker_pool.broadcast.assert_called_once()

if __name__ == '__main__':
    unittest.main()
