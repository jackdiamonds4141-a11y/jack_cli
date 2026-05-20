import sys
import os
import unittest
from unittest.mock import MagicMock

# Ensure the base and Core directories are in the path
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, base_dir)
sys.path.insert(0, os.path.join(base_dir, 'Core'))

from attention_variants import CompressedSemanticPool, DecoupledPositionTagger
from data_manager import GoblinResourceController, FlatPromptAssembler

class TestCompressedSemanticPool(unittest.TestCase):
    def test_latent_truncation_and_anchor_touch(self):
        pool = CompressedSemanticPool(max_digest_len=80)
        
        c1 = MagicMock(claim_id="c1", text="A" * 100, status="ACTIVE", epoch_born=1, anchor_links=["anchor_alpha"])
        c2 = MagicMock(claim_id="c2", text="Short", status="PENDING", epoch_born=1, anchor_links=["random_link"])
        
        pool.compress_claims([c1, c2], current_epoch=2, frozen_anchor_claims=["anchor_alpha"])
        
        self.assertEqual(pool.pool["epoch_watermark"], 2)
        
        # Test 80-char latent truncation
        digest1 = pool.pool["claims"]["c1"]["digest"]
        self.assertEqual(len(digest1), 80)
        self.assertTrue(digest1.endswith("..."))
        
        # Test anchor-touch immunity
        self.assertTrue(pool.pool["claims"]["c1"]["anchor_touch"])
        
        digest2 = pool.pool["claims"]["c2"]["digest"]
        self.assertEqual(digest2, "Short")
        self.assertFalse(pool.pool["claims"]["c2"]["anchor_touch"])

class TestDecoupledPositionTagger(unittest.TestCase):
    def test_decoupled_rope_coordinates_sequence(self):
        tagger = DecoupledPositionTagger()
        tag1 = tagger.tag(epoch=2, worker_id="worker_07")
        tag2 = tagger.tag(epoch=2, worker_id="worker_07")
        tag3 = tagger.tag(epoch=2, worker_id="worker_08")
        
        self.assertEqual(tag1, "E2W07S001")
        self.assertEqual(tag2, "E2W07S002")
        self.assertEqual(tag3, "E2W08S001")

    def test_flat_xml_output(self):
        tagger = DecoupledPositionTagger()
        xml = tagger.build_flat_xml_node("c1", "E2W07S001", "some digest", "ACTIVE")
        self.assertEqual(xml, '<CLAIM id="c1" pos="E2W07S001" status="ACTIVE">some digest</CLAIM>')
        self.assertNotIn("\n", xml)
        self.assertEqual(xml.count("<CLAIM"), 1)
        self.assertEqual(xml.count("</CLAIM>"), 1)

class TestGoblinResourceController(unittest.TestCase):
    def test_emergency_compress_truncation_and_anchor_preservation(self):
        controller = GoblinResourceController()
        pool_data = {
            "epoch_watermark": 3,
            "claims": {
                "c1": {"digest": "A" * 80, "status": "ACTIVE", "epoch_born": 1, "anchor_touch": False},
                "c2": {"digest": "B" * 80, "status": "PENDING", "epoch_born": 1, "anchor_touch": False}, # Stale, prune
                "c3": {"digest": "C" * 80, "status": "PENDING", "epoch_born": 1, "anchor_touch": True},  # Stale but immune
                "c4": {"digest": "D" * 80, "status": "PENDING", "epoch_born": 2, "anchor_touch": False}  # Not stale yet
            }
        }
        
        compressed = controller.emergency_compress(pool_data)
        claims = compressed["claims"]
        
        self.assertEqual(len(claims["c1"]["digest"]), 40)
        self.assertTrue(claims["c1"]["digest"].endswith("..."))
        
        self.assertNotIn("c2", claims, "Stale untouched PENDING claim must be pruned")
        self.assertIn("c3", claims, "Stale PENDING claim with anchor_touch MUST survive")
        self.assertIn("c4", claims, "Fresh PENDING claim must survive")
        self.assertIn("c1", claims, "ACTIVE claim must survive")

class TestFlatPromptAssembler(unittest.TestCase):
    def test_linear_continuity(self):
        assembler = FlatPromptAssembler()
        pool_data = {
            "claims": {
                "c1": {"epoch_born": 2, "digest": "hello", "status": "ACTIVE"}
            }
        }
        
        prompt = assembler.assemble("ANCHOR_DATA", pool_data, "DIRECTIVE_DATA")
        
        self.assertIn("<ANCHOR>ANCHOR_DATA</ANCHOR>", prompt)
        self.assertIn("<SEMANTIC_POOL>", prompt)
        self.assertIn("<DIRECTIVE>DIRECTIVE_DATA</DIRECTIVE>", prompt)
        
        idx_anchor = prompt.find("<ANCHOR>")
        idx_pool = prompt.find("<SEMANTIC_POOL>")
        idx_directive = prompt.find("<DIRECTIVE>")
        
        self.assertLess(idx_anchor, idx_pool)
        self.assertLess(idx_pool, idx_directive)
        
        self.assertEqual(prompt.count("<CLAIM"), 1)
        self.assertEqual(prompt.count("</CLAIM>"), 1)

if __name__ == '__main__':
    unittest.main()
