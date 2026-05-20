# Core/epoch_coordinator.py
import time
import logging

logger = logging.getLogger("EpochBarrier")

class EpochBarrier:
    def __init__(self, expected_workers: int = 20, timeout: float = 15.0):
        self.expected_workers = expected_workers
        self.timeout = timeout
        self.checkins = set()
        self.barrier_start = 0.0

    def start_epoch(self):
        self.checkins.clear()
        self.barrier_start = time.time()

    def checkin(self, worker_id: str) -> bool:
        self.checkins.add(worker_id)
        return self.is_ready()

    def is_ready(self) -> bool:
        # Resolves when quorum is met or timeout expires (Exception Safety Matrix)
        if len(self.checkins) >= self.expected_workers:
            return True
        if time.time() - self.barrier_start > self.timeout:
            logger.warning(f"Barrier timeout reached. Missing workers: {self.expected_workers - len(self.checkins)}")
            return True
        return False
