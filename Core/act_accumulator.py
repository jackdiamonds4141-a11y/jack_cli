# Core/act_accumulator.py
class DiscreteACTAccumulator:
    def __init__(self, tau: float = 0.99):
        self.tau = tau
        
    def compute_weights(self, claims: list) -> dict:
        weights = {}
        cumulative_consensus = 0.0
        
        # Sort by validation epoch to respect reasoning trajectory
        sorted_claims = sorted([c for c in claims if getattr(c, 'status', '') == "VALIDATED"], key=lambda c: getattr(c, 'epoch_validated', 0))
        
        for c in sorted_claims:
            p_t = min(1.0, getattr(c, 'endorsements', 0) / 5.0) # Social consensus probability
            claim_id = getattr(c, 'claim_id', 'unknown')
            
            if cumulative_consensus + p_t < self.tau:
                weights[claim_id] = p_t
                cumulative_consensus += p_t
            else:
                # ACT Halting Step Remainder Trick
                weights[claim_id] = self.tau - cumulative_consensus
                cumulative_consensus = self.tau
                break
                
        return weights

    def compile_weighted_report(self, claims: list, weights: dict) -> str:
        weighted = [(c, weights.get(getattr(c, 'claim_id', 'unknown'), 0.0)) for c in claims if weights.get(getattr(c, 'claim_id', 'unknown'), 0.0) > 0.0]
        weighted.sort(key=lambda x: x[1], reverse=True)
        
        lines = ["# FINAL LAYER BLUEPRINT (Weighted ACT Accumulation)\n"]
        for claim, w in weighted:
            lines.append(f"## {getattr(claim, 'claim_id', 'unknown')} (weight: {w:.3f})\n{getattr(claim, 'text', '')}\n")
            
        return "\n".join(lines)
