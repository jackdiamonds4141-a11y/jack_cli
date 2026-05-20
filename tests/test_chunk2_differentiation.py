import sys
import os
import unittest
import re
from unittest.mock import MagicMock

# Ensure the base and Core directories are in the path
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, base_dir)
sys.path.insert(0, os.path.join(base_dir, 'Core'))

from Core.differentiation import LoopClock, EpochStrategyDirector, EpochStrategy
from Core.data_manager import PromptAssembler

class TestLoopClock(unittest.TestCase):
    def test_generate_outputs_well_formed_xml_and_8char_hex_hash(self):
        xml = LoopClock.generate(epoch=2, max_epochs=3)
        self.assertIn('epoch="2"', xml)
        self.assertIn('max="3"', xml)
        
        match = re.search(r'hash="([0-9a-fA-F]{8})"', xml)
        self.assertIsNotNone(match, msg=f"Expected 8-char hex hash in XML, got: {xml}")
        self.assertEqual(len(match.group(1)), 8)

    def test_hash_is_deterministic_and_unique_per_epoch(self):
        xml_1 = LoopClock.generate(epoch=1, max_epochs=3)
        xml_2 = LoopClock.generate(epoch=2, max_epochs=3)
        xml_1_again = LoopClock.generate(epoch=1, max_epochs=3)

        hash_1 = re.search(r'hash="([0-9a-fA-F]{8})"', xml_1).group(1)
        hash_2 = re.search(r'hash="([0-9a-fA-F]{8})"', xml_2).group(1)
        hash_1_again = re.search(r'hash="([0-9a-fA-F]{8})"', xml_1_again).group(1)

        self.assertNotEqual(hash_1, hash_2, "Different epochs must yield different hashes")
        self.assertEqual(hash_1, hash_1_again, "Same epoch must yield identical hash (determinism)")

    def test_clamp_epoch_forces_hard_ceiling_at_trained_max(self):
        self.assertEqual(LoopClock.clamp_epoch(1), 1)
        self.assertEqual(LoopClock.clamp_epoch(3), 3)
        self.assertEqual(LoopClock.clamp_epoch(5), 3)


class TestEpochStrategyDirector(unittest.TestCase):
    def test_epoch_personas_map_correctly(self):
        strat_1 = EpochStrategyDirector.get_directive(1)
        self.assertEqual(strat_1.persona, "EXPLORER")
        self.assertIn("coverage over pruning", strat_1.instruction)

        strat_2 = EpochStrategyDirector.get_directive(2)
        self.assertEqual(strat_2.persona, "ADVERSARY")
        self.assertIn("FORBIDDEN to propose new ideas", strat_2.instruction)

        strat_3 = EpochStrategyDirector.get_directive(3)
        self.assertEqual(strat_3.persona, "CONVERGER")
        self.assertIn("Merge ONLY verified axioms", strat_3.instruction)

    def test_extrapolation_clamps_to_converger_with_warning(self):
        strat_4 = EpochStrategyDirector.get_directive(4)
        self.assertIn("CONVERGER", strat_4.persona)
        self.assertIn("WARNING: Extrapolation Depth Reached", strat_4.instruction)


class TestPromptAssemblerIntegration(unittest.TestCase):
    def setUp(self):
        self.registry = MagicMock()
        self.registry.get_verified.return_value = [MagicMock(id="v1", text="verified claim")]
        self.registry.get_active_sorted_by_weight.return_value = [MagicMock(id="a1", text="active claim")]
        self.registry.get_refuted.return_value = []
        
        budget = MagicMock(verified_share=0.25, active_share=0.25)
        normalizer = MagicMock()
        normalizer.tombstone_refuted.return_value = ""
        self.assembler = PromptAssembler(budget=budget, normalizer=normalizer)

    def test_clock_and_strategy_appear_at_top_of_prompt(self):
        prompt = self.assembler.assemble(anchor_yaml="anchor data", registry=self.registry, epoch=2)
        
        self.assertIn("<loop_clock", prompt)
        self.assertIn("<strategy_adapter", prompt)
        
        prompt_lower = prompt.lower()
        pos_clock = prompt_lower.find("<loop_clock")
        pos_adapter = prompt_lower.find("<strategy_adapter")
        pos_active = prompt_lower.find("<active_residue>")
        
        self.assertLess(pos_clock, pos_adapter, "Loop clock must precede strategy adapter")
        self.assertLess(pos_adapter, pos_active, "Strategy adapter must precede active claims")

if __name__ == '__main__':
    unittest.main()
