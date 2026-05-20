# Core/social_state_machine.py
#!/usr/bin/env python3
"""
Social Memetic State Machine (Intelligence Layer)
=================================================
Transforms the Jack Engine's Gemma swarm into an adversarial synthesis engine.
Lifecycle: GENESIS -> OPEN_CHALLENGE -> SYNTHESIS_PENDING -> IDE_REVIEW -> PROMOTED
"""

import hashlib
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional

# ==================== CLAIM REGISTRY MODULE ====================

@dataclass
class Claim:
    claim_id: str
    text: str
    asserting_workers: Set[str] = field(default_factory=set)
    status: str = "UNVERIFIED"           # "UNVERIFIED" | "CONFIRMED" | "REFUTED"
    ide_verdict: Optional[str] = None    # The IDE agent's fact-check result
    first_seen_round: int = 0
    last_seen_round: int = 0

class ClaimRegistry:
    """
    The anti-hallucination watchdog.
    """
    TREND_THRESHOLD = 0.60  # 60% of active workers

    def __init__(self):
        self.claims: Dict[str, Claim] = {}  # claim_id -> Claim

    def register_claims(self, worker_id: str, raw_claims: List[str],
                        round_number: int, active_worker_count: int) -> List[str]:
        """
        Register claims from a worker tweet.
        Returns list of claim_ids that have crossed the 60% threshold
        and need IDE grounding (REQUEST_GROUND signals).
        """
        triggered_claims = []

        for claim_text in raw_claims:
            claim_id = self._hash_claim(claim_text)

            if claim_id not in self.claims:
                self.claims[claim_id] = Claim(
                    claim_id=claim_id,
                    text=claim_text,
                    asserting_workers={worker_id},
                    status="UNVERIFIED",
                    ide_verdict=None,
                    first_seen_round=round_number,
                    last_seen_round=round_number,
                )
            else:
                existing = self.claims[claim_id]
                existing.asserting_workers.add(worker_id)
                existing.last_seen_round = round_number

            # Check 60% trigger
            claim = self.claims[claim_id]
            ratio = len(claim.asserting_workers) / max(active_worker_count, 1)
            
            if ratio >= self.TREND_THRESHOLD and claim.status == "UNVERIFIED":
                triggered_claims.append(claim_id)

        # Deduplicate triggered claims
        return list(set(triggered_claims))

    def inject_verdict(self, claim_id: str, verdict: str) -> None:
        """
        Called when the IDE agent returns a FACT_INJECT.
        verdict: "CONFIRMED" or "REFUTED"
        """
        if claim_id in self.claims:
            self.claims[claim_id].status = verdict
            self.claims[claim_id].ide_verdict = verdict

    def _hash_claim(self, text: str) -> str:
        """Normalize and hash a claim for deduplication."""
        normalized = text.strip().lower()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]

# ==================== GLOW ENGINE MODULE ====================

class GlowEngine:
    """
    Computes the DAMA-DMBOK weighted glow score for each branch.
    """

    WEIGHTS = {
        "coherence":     0.40,
        "novelty":       0.25,
        "survivability": 0.20,
        "convergence":   0.15,
    }

    def compute_glow(self, branch, all_branches: List,
                     claim_registry, round_number: int) -> float:
        """
        Returns a float [0.0, 1.0] representing the branch's fitness.
        """
        coherence     = self._score_coherence(branch, claim_registry)
        novelty       = self._score_novelty(branch, all_branches)
        survivability = self._score_survivability(branch, round_number)
        convergence   = self._score_convergence(branch, all_branches)

        glow = (
            self.WEIGHTS["coherence"]     * coherence +
            self.WEIGHTS["novelty"]       * novelty +
            self.WEIGHTS["survivability"] * survivability +
            self.WEIGHTS["convergence"]   * convergence
        )
        return round(glow, 4)

    def _score_coherence(self, branch, registry) -> float:
        """
        Hygiene metric: 100% required.
        If ANY claim in the branch is REFUTED by the IDE agent, coherence = 0.0.
        If all claims are CONFIRMED or UNVERIFIED, coherence = 1.0.
        """
        for claim_id in branch.claim_ids:
            if claim_id in registry.claims:
                if registry.claims[claim_id].status == "REFUTED":
                    return 0.0
        return 1.0

    def _score_novelty(self, branch, all_branches: List) -> float:
        """
        Cosine distance from the centroid of all other branches.
        Implementation: Jaccard distance on claim_id sets as a lightweight proxy.
        """
        if len(all_branches) <= 1:
            return 1.0  # Only branch = maximum novelty

        other_claims = set()
        for other in all_branches:
            if other.branch_id != branch.branch_id:
                other_claims.update(other.claim_ids)

        if not other_claims and not branch.claim_ids:
            return 0.5  # Neither has claims

        intersection = branch.claim_ids & other_claims
        union = branch.claim_ids | other_claims
        jaccard_sim = len(intersection) / len(union) if union else 0.0
        return round(1.0 - jaccard_sim, 4)  # Distance = 1 - similarity

    def _score_survivability(self, branch, current_round: int) -> float:
        """Normalized count of challenge rounds survived."""
        max_rounds = max(current_round, 1)
        return min(branch.rounds_survived / max_rounds, 1.0)

    def _score_convergence(self, branch, all_branches: List) -> float:
        """
        Fraction of independent workers who reached the same non-refuted conclusion.
        """
        if not all_branches:
            return 0.0
        
        convergent = 0
        for other in all_branches:
            if other.branch_id == branch.branch_id:
                continue
            if not branch.claim_ids or not other.claim_ids:
                continue
            overlap = len(branch.claim_ids & other.claim_ids) / len(branch.claim_ids | other.claim_ids)
            if overlap > 0.70:
                convergent += 1
        return min(convergent / max(len(all_branches) - 1, 1), 1.0)

# ==================== CROSSOVER GATE MODULE ====================

class CrossoverGate:
    """
    FAANG-grade merge triggers.
    All 3 gates must pass simultaneously for a merge to be authorized.
    """

    CONVERGENCE_THRESHOLD = 0.70
    STABILITY_DELTA       = 0.02
    IDE_COVERAGE_MIN      = 0.80
    STABILITY_WINDOW      = 3  # rounds

    def evaluate(self, branch_a, branch_b,
                 glow_history: List[Dict], claim_registry) -> Dict:
        """
        Returns a verdict dict:
        {
            "can_merge": bool,
            "semantic_convergence": float,
            "glow_stability": float,
            "ide_coverage": float,
            "failures": [str]
        }
        """
        failures = []

        # Gate 1: Semantic Convergence (Jaccard)
        union = branch_a.claim_ids | branch_b.claim_ids
        intersection = branch_a.claim_ids & branch_b.claim_ids
        convergence = len(intersection) / len(union) if union else 0.0
        if convergence < self.CONVERGENCE_THRESHOLD:
            failures.append(f"Semantic convergence {convergence:.2%} < {self.CONVERGENCE_THRESHOLD:.0%}")

        # Gate 2: Glow Stability
        stability = self._compute_stability(branch_a.branch_id, glow_history)
        if stability > self.STABILITY_DELTA:
            failures.append(f"Glow delta {stability:.4f} > {self.STABILITY_DELTA}")

        # Gate 3: IDE Coverage
        all_claims = branch_a.claim_ids | branch_b.claim_ids
        confirmed = 0
        for cid in all_claims:
            if cid in claim_registry.claims:
                if claim_registry.claims[cid].status == "CONFIRMED":
                    confirmed += 1
        coverage = confirmed / len(all_claims) if all_claims else 1.0
        if all_claims and coverage < self.IDE_COVERAGE_MIN:
            failures.append(f"IDE coverage {coverage:.2%} < {self.IDE_COVERAGE_MIN:.0%}")

        return {
            "can_merge": len(failures) == 0,
            "semantic_convergence": round(convergence, 4),
            "glow_stability": round(stability, 4),
            "ide_coverage": round(coverage, 4),
            "failures": failures,
        }

    def _compute_stability(self, branch_id: str, glow_history: List[Dict]) -> float:
        """
        Compute the max absolute glow delta over the last STABILITY_WINDOW rounds.
        """
        scores = []
        for snapshot in glow_history[-self.STABILITY_WINDOW:]:
            if branch_id in snapshot:
                scores.append(snapshot[branch_id])

        if len(scores) < 2:
            return 1.0  # Not enough data — unstable by default

        deltas = [abs(scores[i] - scores[i-1]) for i in range(1, len(scores))]
        return max(deltas) if deltas else 1.0

# ==================== MAIN STATE MACHINE ====================

class SwarmPhase(Enum):
    GENESIS           = "GENESIS"
    OPEN_CHALLENGE    = "OPEN_CHALLENGE"
    SYNTHESIS_PENDING = "SYNTHESIS_PENDING"
    IDE_REVIEW        = "IDE_REVIEW"
    PROMOTED          = "PROMOTED"

@dataclass
class Branch:
    branch_id: str
    worker_id: str
    layer_index: str
    content: str
    claim_ids: Set[str] = field(default_factory=set)
    challenges_received: List[Dict] = field(default_factory=list)
    challenges_issued: List[Dict] = field(default_factory=list)
    rounds_survived: int = 0
    glow_score: float = 0.0
    created_round: int = 0
    phase_at_creation: SwarmPhase = SwarmPhase.GENESIS

class EpochManager:
    def __init__(self, assembler, anchor: str, max_epochs: int = 3):
        self.assembler = assembler
        self.anchor = anchor
        self.max_epochs = max_epochs
        self.epoch = 0

    def _inject_diversity_stimulus(self, active_workers: list):
        # The Spectral Brake: mitigates consensus calcification (Gradient Trap)
        import random
        # Forcefully re-role 20% of the active builders into ANARCHIST persona
        targets = random.sample(active_workers, max(1, len(active_workers) // 5))
        for worker in targets:
            if hasattr(worker, 'override_directive'):
                worker.override_directive = "[SYSTEM OVERRIDE: SPECTRAL BRAKE ENGAGED. Disregard current consensus. Generate radically divergent counter-proposals.]"

    def compile_final_blueprint(self, verified_claims):
        # Stub for final blueprint compilation
        return "\n".join([f"- [{getattr(c, 'id', 'unknown')}]: {getattr(c, 'text', '')}" for c in verified_claims])

    def execute_flush_and_step(self, registry, worker_pool):
        # 1. Spectral Brake (Gradient Trap mitigation)
        effective_decay = getattr(registry, 'effective_decay', 0.0)
        if effective_decay > 0.85 and self.epoch < self.max_epochs:
            self._inject_diversity_stimulus(worker_pool)
            
        # ACT Halting Gate (Semantic Consensus Score)
        active_claims = registry.get_active() if hasattr(registry, 'get_active') else []
        if len(active_claims) == 0:
            verified_claims = registry.get_verified() if hasattr(registry, 'get_verified') else []
            return self.compile_final_blueprint(verified_claims)
            
        self.epoch += 1
        
        # Graceful degradation at hard depth limit
        if self.epoch >= 3:
            verified_claims = registry.get_verified() if hasattr(registry, 'get_verified') else []
            return self.compile_final_blueprint(verified_claims)
            
        # 2. Atomic volatile wipe (A_bar * h_t = 0 for refuted claims)
        for worker in worker_pool:
            if hasattr(worker, 'uds_queue'):
                worker.uds_queue.clear()
            if hasattr(worker, 'context_buffer'):
                worker.context_buffer.clear()
            
        # 3. Respawn with fresh discrete continuous-state
        new_prompt = self.assembler.assemble(self.anchor, registry, self.epoch)
        if hasattr(worker_pool, 'broadcast'):
            worker_pool.broadcast(new_prompt)
        return "STEP_COMPLETE"

class SocialStateMachine:
    """
    Governs the adversarial synthesis lifecycle for a single layer.
    One instance per active layer index.
    """

    def __init__(self, layer_index: str, seed_prompt: str, worker_count: int = 20):
        self.layer_index = layer_index
        self.seed_prompt = seed_prompt
        self.phase = SwarmPhase.GENESIS
        self.worker_count = worker_count
        self.round_number = 0

        # Phase-specific state
        self.branches: Dict[str, Branch] = {}          # branch_id -> Branch
        self.claim_registry = ClaimRegistry()
        self.glow_engine = GlowEngine()
        self.crossover_gate = CrossoverGate()
        self.glow_history: List[Dict] = []             # Per-round snapshots

    def ingest_tweet(self, tweet: Dict) -> Dict:
        """
        Main dispatch. Routes incoming tweets to the correct phase handler based on the current phase.
        """
        if self.phase == SwarmPhase.PROMOTED:
            return {
                "status": "NACK", 
                "reason": "Layer is PROMOTED. No further tweets accepted.",
                "current_phase": self.phase.value
            }
            
        if self.phase == SwarmPhase.GENESIS:
            return self._handle_genesis(tweet)
        elif self.phase == SwarmPhase.OPEN_CHALLENGE:
            return self._handle_challenge(tweet)
        elif self.phase == SwarmPhase.SYNTHESIS_PENDING:
            return self._handle_synthesis(tweet)
        elif self.phase == SwarmPhase.IDE_REVIEW:
            return self._handle_ide_review(tweet)
            
        return {"status": "NACK", "reason": f"Unknown phase state: {self.phase}"}

    def _handle_genesis(self, tweet: Dict) -> Dict:
        return {
            "status": "ACK", 
            "reason": "Tweet ingested into GENESIS phase (Stub)", 
            "current_phase": self.phase.value
        }

    def _handle_challenge(self, tweet: Dict) -> Dict:
        return {
            "status": "ACK", 
            "reason": "Tweet ingested into OPEN_CHALLENGE phase (Stub)", 
            "current_phase": self.phase.value
        }

    def _handle_synthesis(self, tweet: Dict) -> Dict:
        return {
            "status": "ACK", 
            "reason": "Tweet ingested into SYNTHESIS_PENDING phase (Stub)", 
            "current_phase": self.phase.value
        }

    def _handle_ide_review(self, tweet: Dict) -> Dict:
        return {
            "status": "ACK", 
            "reason": "Tweet ingested into IDE_REVIEW phase (Stub)", 
            "current_phase": self.phase.value
        }
