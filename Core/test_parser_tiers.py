#!/usr/bin/env python3
"""
Test Harness: 6-Tier Bulletproof Parser Validation
===================================================
Imports the production 6-tier parser and validates it against all 13
classes of malformed output Gemma-4 and small models generate.
"""

import json
import os
import sys

# Ensure parent directory is in sys.path so we can import Core.parser cleanly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Core.parser import parse_output

PASS = 0
FAIL = 0

def test(name, input_str, expected_tier, idea_id="test_task", idea=None):
    global PASS, FAIL
    result = parse_output(input_str, idea_id, idea)
    if result and "content" in result and len(result["content"]) > 10:
        print(f"  ✅ {name} [{expected_tier}] → meme_type={result.get('meme_type')}, content_len={len(result['content'])}, claims={len(result.get('claims', []))}")
        PASS += 1
    else:
        print(f"  ❌ {name} [{expected_tier}] → FAILED (result={result})")
        FAIL += 1


print("\n══════════════════════════════════════════════════")
print("  6-TIER BULLETPROOF PARSER TEST HARNESS (CORE)")
print("══════════════════════════════════════════════════\n")

# ── TIER 1: Perfect JSON ──
print("── TIER 1: Clean JSON ──")
test("Perfect JSON object", json.dumps({
    "meme_type": "PROPOSAL",
    "content": "This is a perfectly formatted proposal with detailed analysis of CRDT convergence.",
    "claims": ["CRDTs guarantee SEC", "Tombstones cause bloat"],
    "target_branch_id": None
}), "TIER 1")

# ── TIER 2: Markdown fenced ──
print("\n── TIER 2: Markdown Fenced ──")
test("```json fenced", '```json\n{"meme_type": "CHALLENGE", "content": "The assertion that CRDTs provide the mathematical foundation is a reductionist fallacy.", "claims": ["SEC does not equal correctness"], "target_branch_id": "branch_01"}\n```', "TIER 2")

test("``` fenced (no json tag)", '```\n{"meme_type": "SYNTHESIS", "content": "Synthesizing the adversarial challenges into a unified architecture for local-first state sync.", "claims": ["Unified architecture needed"], "target_branch_id": null}\n```', "TIER 2")

# ── TIER 3: Preamble/postscript wrapping ──
print("\n── TIER 3: Boundary Slice ──")
test("Text preamble + JSON", 'Here is my response:\n\n{"meme_type": "CHALLENGE", "content": "The Bootstrapping Paradox undermines decentralized discovery claims in production environments.", "claims": ["Bootstrap nodes are SPOF"], "target_branch_id": "branch_seed_01"}', "TIER 3")

# ── TIER 4: Dirty JSON ──
print("\n── TIER 4: Dirty JSON Repair ──")

test("Trailing commas", '{"meme_type": "PROPOSAL", "content": "Delta-state CRDTs with Merkle verification provide optimal bandwidth.", "claims": ["Delta-state is optimal", "Merkle verification is key",], "target_branch_id": null,}', "TIER 4")

test("Single quotes", "{'meme_type': 'CHALLENGE', 'content': 'HLCs are susceptible to clock jump vulnerabilities where physical skew corrupts timelines.', 'claims': ['Clock jumps corrupt HLC', 'Ghost causality is real'], 'target_branch_id': 'branch_01'}", "TIER 4")

test("Unquoted keys", '{meme_type: "SYNTHESIS", content: "The consolidated architecture fuses CI-MDAG causality with VSRM transport.", claims: ["CI-MDAG resolves clock drift", "VSRM prevents Sybil attacks"], target_branch_id: "branch_seed_01"}', "TIER 4")

test("Python None/True/False", '{"meme_type": "PROPOSAL", "content": "A fully decentralized relay mesh eliminates all centralized bottlenecks.", "claims": ["Decentralized relay is viable"], "target_branch_id": None}', "TIER 4")

test("Truncated JSON (missing closing })", '{"meme_type": "SYNTHESIS", "content": "This synthesis fuses all adversarial vectors into a production spec covering tombstone GC and clock drift.", "claims": ["Tombstone GC via epoch compaction", "Clock drift bounded by CI-MDAG"]', "TIER 4")

# ── TIER 5: Regex extraction ──
print("\n── TIER 5: Regex Key-Value Extraction ──")

test("Broken JSON with extractable fields",
     'meme_type = CHALLENGE\ncontent = "The assertion that WebRTC eliminates centralized bottlenecks ignores the NAT/TURN regression to client-server topology in enterprise environments. This is a fundamental architectural vulnerability."\nclaims = ["TURN servers reintroduce centralization", "Enterprise NAT traversal fails"]\ntarget_branch_id = "branch_seed_01"',
     "TIER 5", idea_id="challenge_test")

test("Malformed JSON with readable key-value pairs",
     '{ meme_type: PROPOSAL, "content": "Vector clocks provide causally consistent ordering without physical time dependency, making HLCs unnecessary for pure happens-before relations.", "claims": ["Vector clocks satisfy causality", "HLCs add unnecessary complexity"], target_branch_id: null invalid trailing garbage...',
     "TIER 5")

# ── TIER 6: Pure plain-text ──
print("\n── TIER 6: Pure Plain-Text Fallback ──")

test("Raw reasoning dump (synthesis context)",
     "The assertion that Hybrid Logical Clocks are required for causal ordering is mathematically false. "
     "Lamport timestamps and vector clocks satisfy the happens-before relation independently of physical time. "
     "HLCs introduce specific architectural vulnerabilities including clock jump propagation, ghost causality "
     "(false total ordering under near-identical timestamps), and non-deterministic replay in event-sourcing architectures. "
     "The proposed mitigation is Causal-Interval Merkle DAGs which decouple physical time intervals from logical causality "
     "using hash-linked DAG structures with bounded uncertainty windows. "
     "Furthermore, the CRDT Semantic Gap means that mathematical convergence does not guarantee application-level correctness. "
     "Tombstone accumulation creates unbounded metadata growth requiring epoch-based compaction protocols.",
     "TIER 6", idea_id="synthesis_1_9_gemma", idea={"target_branch_id": "branch_seed_01"})

test("Raw reasoning dump (challenge context)",
     "The claim that delta-state synchronization via Merkle structures is strictly more efficient than full-state replication "
     "is empirically false for small datasets. When the state size is below the Merkle proof computation threshold, "
     "full-state transfer has lower latency and bandwidth overhead. Additionally, Merkle tree rebalancing under high write "
     "throughput creates non-trivial computational overhead that scales with tree depth. The proof verification cost "
     "at each level introduces O(log N) signature validations per sync cycle.",
     "TIER 6", idea_id="challenge_51a1509a")


print(f"\n══════════════════════════════════════════════════")
print(f"  RESULTS: {PASS} PASSED / {FAIL} FAILED / {PASS + FAIL} TOTAL")
print(f"══════════════════════════════════════════════════\n")

sys.exit(1 if FAIL > 0 else 0)
