# Core/differentiation.py
import hashlib
from dataclasses import dataclass

class LoopClock:
    @staticmethod
    def generate(epoch: int, max_epochs: int) -> str:
        # Generates a unique, non-repeating token signature per epoch
        clock_hash = hashlib.sha256(
            f"jack-engine-loop-{epoch}-of-{max_epochs}".encode()
        ).hexdigest()[:8]
        
        return f'<loop_clock epoch="{epoch}" max="{max_epochs}" hash="{clock_hash}" />'

    @staticmethod
    def clamp_epoch(epoch: int, trained_max: int = 3) -> int:
        return min(epoch, trained_max)

@dataclass(frozen=True)
class EpochStrategy:
    epoch: int
    persona: str
    instruction: str

STRATEGIES = {
    1: EpochStrategy(
        epoch=1,
        persona="EXPLORER",
        instruction="- Generate broad hypotheses and diverse solutions.\n- Prioritize coverage over pruning.\n- Do NOT critique other branches yet."
    ),
    2: EpochStrategy(
        epoch=2,
        persona="ADVERSARY",
        instruction="- Hunt contradictions in active claims.\n- Attack edge cases and logical gaps.\n- You are FORBIDDEN to propose new ideas."
    ),
    3: EpochStrategy(
        epoch=3,
        persona="CONVERGER",
        instruction="- Merge ONLY verified axioms.\n- Prune any claim lacking empirical proof.\n- Synthesize the final coherent blueprint."
    )
}

class EpochStrategyDirector:
    @staticmethod
    def get_directive(epoch: int) -> EpochStrategy:
        # Extrapolation guard: clamps to max trained depth (3) to prevent collapse
        clamped = LoopClock.clamp_epoch(epoch)
        base_strategy = STRATEGIES[clamped]
        
        if epoch > 3:
            return EpochStrategy(
                epoch=epoch,
                persona=f"{base_strategy.persona}_EXTRAPOLATED",
                instruction=base_strategy.instruction + "\n[WARNING: Extrapolation Depth Reached. Maintain strict convergence.]"
            )
        return base_strategy
