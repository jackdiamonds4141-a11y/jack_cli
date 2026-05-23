# Core/social_state_machine.py
#!/usr/bin/env python3

"""
Social Memetic State Machine (Intelligence Layer)
=================================================
Transforms the Jack Engine's Gemma swarm into an adversarial synthesis engine.
Lifecycle: GENESIS -> OPEN_CHALLENGE -> SYNTHESIS_PENDING -> IDE_REVIEW -> PROMOTED
"""

import hashlib
import time
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
        self.expected_tasks = {"seed_01"}
        self.completed_tasks = set()
        self.phase_start_time = 0.0


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
        branch_id = tweet.get("branch_id")
        claims = tweet.get("claims", [])
        claim_ids = set(self.claim_registry._hash_claim(c) for c in claims)

        # Register claims
        self.claim_registry.register_claims(
            tweet.get("requester"),
            claims,
            self.round_number,
            self.worker_count
        )

        # Build branch and compute glow score
        branch = Branch(
            branch_id=branch_id,
            worker_id=tweet.get("requester"),
            layer_index=self.layer_index,
            content=tweet.get("content"),
            claim_ids=claim_ids,
            created_round=self.round_number,
            phase_at_creation=self.phase
        )
        self.branches[branch_id] = branch
        branch.glow_score = self.glow_engine.compute_glow(
            branch,
            list(self.branches.values()),
            self.claim_registry,
            self.round_number
        )

        # Dynamic generation of adversarial challenges
        new_ideas = []
        for claim_text in claims:
            claim_hash = self.claim_registry._hash_claim(claim_text)
            challenge_prompt = (
                f"CHALLENGE PROMPT: The following claim has been asserted in Layer {self.layer_index}: '{claim_text}'.\n"
                f"Under the strict constraints of the Swarm Constitution (REGIMEGUARD and OSINT Verification Triangle):\n"
                f"1. Critically analyze and challenge this claim.\n"
                f"2. Identify at least 3 concrete failure modes, scalability limits, or architectural vulnerabilities associated with it.\n"
                f"3. Propose a precise, highly optimized decentralized counter-measure or mitigation.\n\n"
                f"Formulate your response as an adversarial CHALLENGE branch targeting parent branch '{branch_id}'."
            )
            new_ideas.append({
                "id": f"challenge_{claim_hash[:8]}",
                "prompt": challenge_prompt,
                "description": f"Adversarial challenge targeting claim: {claim_hash[:12]}",
                "classification": "SWARM",
                "target_branch_id": branch_id
            })

        self.phase = SwarmPhase.OPEN_CHALLENGE
        self.round_number += 1
        
        # Track dynamically generated challenges for the round barrier
        import time
        self.expected_tasks = {idea["id"] for idea in new_ideas}
        self.completed_tasks = set()
        self.phase_start_time = time.time()

        return {
            "status": "ACK",
            "reason": f"Ingested GENESIS proposal '{branch_id}' and generated {len(new_ideas)} adversarial challenges.",
            "current_phase": self.phase.value,
            "new_ideas": new_ideas
        }



    def _handle_challenge(self, tweet: Dict) -> Dict:
        branch_id = tweet.get("branch_id")
        target_branch_id = tweet.get("target_branch_id")

        if not target_branch_id or target_branch_id not in self.branches:
            return {
                "status": "NACK",
                "reason": f"Challenge target_branch_id '{target_branch_id}' not found in active branches.",
                "current_phase": self.phase.value
            }

        idea_id = tweet.get("idea_id")
        if not idea_id:
            parts = branch_id.split("_")
            if len(parts) >= 3:
                idea_id = "_".join(parts[2:])

        claims = tweet.get("claims", [])
        claim_ids = set(self.claim_registry._hash_claim(c) for c in claims)

        # Register claims
        self.claim_registry.register_claims(
            tweet.get("requester"),
            claims,
            self.round_number,
            self.worker_count
        )

        # Build challenge branch
        branch = Branch(
            branch_id=branch_id,
            worker_id=tweet.get("requester"),
            layer_index=self.layer_index,
            content=tweet.get("content"),
            claim_ids=claim_ids,
            created_round=self.round_number,
            phase_at_creation=self.phase
        )
        self.branches[branch_id] = branch
        branch.glow_score = self.glow_engine.compute_glow(
            branch,
            list(self.branches.values()),
            self.claim_registry,
            self.round_number
        )

        # Record challenge under parent branch
        challenge_meta = {
            "branch_id": branch_id,
            "worker_id": tweet.get("requester"),
            "content": tweet.get("content")
        }
        self.branches[target_branch_id].challenges_received.append(challenge_meta)

        # Add to completed tasks
        if idea_id:
            self.completed_tasks.add(idea_id)

        # Check round barrier — strictly task-completion-driven, no timeout fallback.
        # Workers implement their own retry/backoff against rate limits, so we wait
        # patiently for every single expected task to report in.
        barrier_cleared = len(self.completed_tasks) >= len(self.expected_tasks)

        if not barrier_cleared:
            return {
                "status": "ACK",
                "reason": f"Ingested CHALLENGE branch '{branch_id}'. Barrier progress: {len(self.completed_tasks)}/{len(self.expected_tasks)} tasks completed. Waiting for others.",
                "current_phase": self.phase.value,
                "new_ideas": []
            }

        # Barrier cleared! Construct consolidated Synthesis prompt merging all challenges
        challenge_contents = []
        for b in self.branches.values():
            if b.phase_at_creation == SwarmPhase.OPEN_CHALLENGE:
                challenge_contents.append(f"Challenge by {b.worker_id}:\n{b.content}")

        proposal_content = self.branches[target_branch_id].content
        
        synthesis_prompt = (
            f"SYNTHESIS PROMPT: You are the Synthesis Engine. Your task is to resolve the tension and merge:\n"
            f"1. PROPOSAL Branch '{target_branch_id}':\n{proposal_content}\n\n"
            f"2. CHALLENGES received:\n" + "\n\n".join(challenge_contents) + "\n\n"
            f"Under the strict constraints of the Swarm Constitution (REGIMEGUARD and OSINT Verification Triangle), you MUST synthesize a reconciled architecture:\n"
            f"- Directly address and resolve all critical vulnerabilities, edge cases, and failure modes highlighted in the challenges.\n"
            f"- Retain the core decentralization and structural benefits of the original proposal.\n"
            f"- Design a highly optimized, fully consistent specification incorporating clear mitigations."
        )

        synthesis_id = f"synthesis_{self.layer_index.replace('.', '_')}"
        new_ideas = [{
            "id": synthesis_id,
            "prompt": synthesis_prompt,
            "description": f"Synthesis merging proposal '{target_branch_id}' and all {len(challenge_contents)} active challenges",
            "classification": "SWARM",
            "target_branch_id": target_branch_id
        }]

        self.phase = SwarmPhase.SYNTHESIS_PENDING
        self.round_number += 1
        self.expected_tasks = {synthesis_id}
        self.completed_tasks = set()
        self.phase_start_time = time.time()

        return {
            "status": "ACK",
            "reason": f"Round barrier cleared ({len(self.completed_tasks)}/{len(self.expected_tasks)}). Ingested CHALLENGE branch '{branch_id}' and generated consolidated SYNTHESIS task.",
            "current_phase": self.phase.value,
            "new_ideas": new_ideas
        }


    def _handle_synthesis(self, tweet: Dict) -> Dict:
        branch_id = tweet.get("branch_id")
        target_branch_id = tweet.get("target_branch_id")

        if not target_branch_id or target_branch_id not in self.branches:
            return {
                "status": "NACK",
                "reason": f"Synthesis target_branch_id '{target_branch_id}' not found in active branches.",
                "current_phase": self.phase.value
            }

        idea_id = tweet.get("idea_id")
        if not idea_id:
            parts = branch_id.split("_")
            if len(parts) >= 3:
                idea_id = "_".join(parts[2:])

        claims = tweet.get("claims", [])
        claim_ids = set(self.claim_registry._hash_claim(c) for c in claims)

        # Register claims
        self.claim_registry.register_claims(
            tweet.get("requester"),
            claims,
            self.round_number,
            self.worker_count
        )

        # Build synthesis branch
        branch = Branch(
            branch_id=branch_id,
            worker_id=tweet.get("requester"),
            layer_index=self.layer_index,
            content=tweet.get("content"),
            claim_ids=claim_ids,
            created_round=self.round_number,
            phase_at_creation=self.phase
        )
        self.branches[branch_id] = branch
        branch.glow_score = self.glow_engine.compute_glow(
            branch,
            list(self.branches.values()),
            self.claim_registry,
            self.round_number
        )

        # Add to completed tasks
        if idea_id:
            self.completed_tasks.add(idea_id)

        # Check round barrier — strictly task-completion-driven, no timeout fallback.
        barrier_cleared = len(self.completed_tasks) >= len(self.expected_tasks)

        if not barrier_cleared:
            return {
                "status": "ACK",
                "reason": f"Ingested SYNTHESIS branch '{branch_id}'. Barrier progress: {len(self.completed_tasks)}/{len(self.expected_tasks)} tasks completed. Waiting for others.",
                "current_phase": self.phase.value,
                "new_ideas": []
            }

        # Evaluate semantic convergence using CrossoverGate
        crossover_res = self.crossover_gate.evaluate(
            self.branches[target_branch_id],
            branch,
            self.glow_history,
            self.claim_registry
        )

        # Transition to IDE_REVIEW to invite grounding
        self.phase = SwarmPhase.IDE_REVIEW
        self.round_number += 1
        review_id = f"review_{self.layer_index.replace('.', '_')}"
        self.expected_tasks = {review_id}
        self.completed_tasks = set()
        self.phase_start_time = time.time()

        return {
            "status": "ACK",
            "reason": (
                f"Ingested SYNTHESIS branch '{branch_id}'. "
                f"Convergence evaluate can_merge={crossover_res.get('can_merge')} "
                f"(Jaccard={crossover_res.get('semantic_convergence')})."
            ),
            "current_phase": self.phase.value,
            "crossover_result": crossover_res
        }


    def _handle_ide_review(self, tweet: Dict) -> Dict:
        branch_id = tweet.get("branch_id")
        idea_id = tweet.get("idea_id")
        if not idea_id:
            parts = branch_id.split("_")
            if len(parts) >= 3:
                idea_id = "_".join(parts[2:])

        if idea_id:
            self.completed_tasks.add(idea_id)

        self.phase = SwarmPhase.PROMOTED
        return {
            "status": "ACK",
            "reason": "Synthesis successfully reviewed and PROMOTED to final consensus.",
            "current_phase": self.phase.value
        }


