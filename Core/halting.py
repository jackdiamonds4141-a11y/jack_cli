# Core/halting.py
class HaltingController:
    def __init__(self):
        self.halted_builders = set()

    def evaluate_worker(self, worker_id: str, role: str, epoch: int, glow: float, median_glow: float = 40.0) -> bool:
        # Fake Halting for structural adversaries - they must always be present to attack
        if role == "ADVERSARY":
            return False
            
        # Dynamic threshold: prune if glow is less than half the median (V3.4 fix)
        dynamic_threshold = max(10.0, median_glow * 0.5)
        if epoch >= 1 and glow < dynamic_threshold:
            self.halted_builders.add(worker_id)
            return True
            
        return False

    def get_active_workers(self, all_workers: list) -> list:
        return [w for w in all_workers if w not in self.halted_builders]
