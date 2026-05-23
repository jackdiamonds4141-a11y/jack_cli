# Core/data_manager.py
#!/usr/bin/env python3
"""
Data Manager Daemon: Single-Source-of-Truth I/O Mediator (Reloaded)
=========================================================
Jack Engine — Asynchronous UDS Mediator for the Gemma Swarm.

Transport: Unix Domain Socket (/tmp/swarm-mediator.sock)
Concurrency Model: Single-threaded serial accept() loop.
                   The Linux kernel manages the FIFO backlog queue.
Write Discipline: POSIX atomic writes (tmp -> fsync -> os.rename).
Guard: All mutations verified against anchor.yaml before commit.
"""

import os
import sys
import socket
import json
import yaml
import logging
import signal
import math
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass

from social_state_machine import SocialStateMachine, SwarmPhase
from epoch_coordinator import EpochBarrier
from halting import HaltingController

class DaemonShutdownRequest(Exception):
    pass

# ──────────── CONSTANTS (Frozen at Boot) ────────────
# Resolve workspace root dynamically:
#   1. JACK_WORKSPACE env var (explicit override)
#   2. Parent of Core/ directory (the repository root)
WORKSPACE_ROOT = Path(os.environ.get("JACK_WORKSPACE", Path(__file__).parent.parent)).resolve()
ANCHOR_PATH = WORKSPACE_ROOT / "References" / "Layering" / "Layering_Prompts" / "anchor.yaml"

# ──────────── LOGGING ────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DataManager")


# ==================== MARKDOWN LEDGER MODULE ====================

class MarkdownLedger:
    """
    Handles formatting of state into Human-readable Markdown + Machine-readable YAML.
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.state_dir = self.workspace_root / "Artifacts" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def generate_layer_branches_markdown(self, state_machine) -> tuple[Path, str]:
        """
        Generates the content for state/layer_{N}_branches.md
        """
        file_path = self.state_dir / f"layer_{state_machine.layer_index}_branches.md"
        
        frontmatter = {
            "layer_index": state_machine.layer_index,
            "phase": state_machine.phase.value,
            "round_number": state_machine.round_number,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "branch_count": len(state_machine.branches)
        }

        lines = []
        lines.append("---")
        lines.append(yaml.dump(frontmatter, sort_keys=False).strip())
        lines.append("---")
        lines.append("")

        registry = getattr(state_machine, "claim_registry", None)

        for branch_id, branch in state_machine.branches.items():
            lines.append(f"## Branch: {branch_id}")
            lines.append(f"- **Worker**: {branch.worker_id}")
            lines.append(f"- **Glow Score**: {branch.glow_score:.4f}")
            lines.append(f"- **Rounds Survived**: {branch.rounds_survived}")
            lines.append(f"- **Claims**:")
            if branch.claim_ids and registry:
                for cid in branch.claim_ids:
                    if cid in registry.claims:
                        c = registry.claims[cid]
                        lines.append(f"  - [{c.status}] {c.text}")
            else:
                lines.append("  - (No claims)")
            
            lines.append("")
            lines.append("### Content")
            lines.append(f"> {branch.content}")
            lines.append("")
            
            if branch.challenges_received:
                lines.append("### Challenges Received")
                for idx, chal in enumerate(branch.challenges_received, 1):
                    lines.append(f"{idx}. **{chal.get('worker_id')}** (Round {chal.get('round')}): \"{chal.get('text')}\"")
                lines.append("")
                
            lines.append("---")
            lines.append("")

        # Return the relative path so data_manager can handle it properly via validate_request
        rel_path = file_path.relative_to(self.workspace_root)
        return Path(rel_path), "\n".join(lines)

    def generate_claim_registry_markdown(self, claim_registry) -> tuple[Path, str]:
        """
        Generates the content for state/claim_registry.md
        """
        file_path = self.state_dir / "claim_registry.md"
        
        claims = claim_registry.claims.values()
        confirmed = sum(1 for c in claims if c.status == "CONFIRMED")
        refuted = sum(1 for c in claims if c.status == "REFUTED")
        unverified = sum(1 for c in claims if c.status == "UNVERIFIED")

        frontmatter = {
            "total_claims": len(claims),
            "confirmed": confirmed,
            "refuted": refuted,
            "unverified": unverified,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

        lines = []
        lines.append("---")
        lines.append(yaml.dump(frontmatter, sort_keys=False).strip())
        lines.append("---")
        lines.append("")
        lines.append("| Claim ID | Text | Asserting Workers | Status | IDE Verdict |")
        lines.append("|:---|:---|:---|:---|:---|")
        
        for c in claims:
            workers = ", ".join(sorted(c.asserting_workers))
            verdict = c.ide_verdict if c.ide_verdict else "—"
            lines.append(f"| {c.claim_id} | {c.text} | {workers} | {c.status} | {verdict} |")

        rel_path = file_path.relative_to(self.workspace_root)
        return Path(rel_path), "\n".join(lines)


# ==================== MAIN DATA MANAGER MODULES ====================

@dataclass
class TokenBudget:
    max_tokens: int = 6000 
    anchor_share: float = 0.35   # B_i equivalent (fixed injection)
    verified_share: float = 0.25 # Surviving A_bar * h_t
    active_share: float = 0.25   # Contested A_bar * h_t
    refute_share: float = 0.10   # Tombstones (decay evidence)
    
class ContextNormalizer:
    def __init__(self, budget: TokenBudget):
        self.budget = budget

    def calculate_decay_weight(self, claim, current_epoch: int) -> float:
        # Dynamic decay scaler (V1.2 fix)
        depth_scaler = 0.5 + (0.1 * current_epoch) 
        age_penalty = math.exp(-depth_scaler * (current_epoch - getattr(claim, 'epoch_born', current_epoch)))
        anchor_bonus = 1.2 if getattr(claim, 'anchor_touch', False) else 0.8
        return age_penalty * getattr(claim, 'glow', 1.0) * anchor_bonus

    def tombstone_refuted(self, refuted_claims) -> str:
        # Deterministic compression of refuted claims to prevent token explosion
        lines = []
        for c in refuted_claims:
            tombstone = f"- [{getattr(c, 'id', 'unknown')}] REFUTED (epoch {getattr(c, 'refuted_epoch', 'unknown')}): {getattr(c, 'text', '')[:80]}..."
            lines.append(tombstone)
        return "\n".join(lines)

class PromptAssembler:
    def __init__(self, budget: TokenBudget, normalizer: ContextNormalizer):
        self.budget = budget
        self.normalizer = normalizer

    def _format(self, claims, share: float) -> str:
        # Enforce TokenBudget shares (V1.3 Fix)
        allowed_chars = int((self.budget.max_tokens * share) * 4) 
        current_chars = 0
        lines = []
        
        for c in claims:
            claim_text = getattr(c, 'text', str(c))
            line = f"- [{getattr(c, 'id', 'unknown')}] {claim_text}"
            
            if current_chars + len(line) > allowed_chars:
                lines.append("")
                break
                
            lines.append(line)
            current_chars += len(line)
            
        return "\n".join(lines)

    def assemble(self, anchor_yaml: str, registry, epoch: int) -> str:
        # B * e injection (Frozen Input)
        anchor_block = f"""<anchor priority="CRITICAL" immutable="true">\n{anchor_yaml}\n</anchor>"""
        
        # A_bar * h_t (Decayed State)
        verified = registry.get_verified() if hasattr(registry, 'get_verified') else []
        active = registry.get_active_sorted_by_weight() if hasattr(registry, 'get_active_sorted_by_weight') else []
        refuted = registry.get_refuted() if hasattr(registry, 'get_refuted') else []

        # --- CHUNK 2 INJECTIONS ---
        from differentiation import EpochStrategyDirector, LoopClock
        strategy = EpochStrategyDirector.get_directive(epoch)
        clock_block = LoopClock.generate(epoch, max_epochs=3)
        
        adapter_block = f"""{clock_block}
<strategy_adapter persona="{strategy.persona}">
{strategy.instruction}
</strategy_adapter>"""

        # Fixed slot order ensures structural stability across recursive loops
        return f"""<epoch_counter value="{epoch}" />
{anchor_block}

{adapter_block}

<verified_axioms>
{self._format(verified, self.budget.verified_share)}
</verified_axioms>

<active_residue>
{self._format(active, self.budget.active_share)}
</active_residue>

<refutation_tombstones>
{self.normalizer.tombstone_refuted(refuted)}
</refutation_tombstones>

<execution_directive>
- The <anchor> is absolute. 
- Process <active_residue> strictly within anchor boundaries.
- Do not repeat patterns found in <refutation_tombstones>.
</execution_directive>"""


class DataManagerDaemon:
    """
    The central nervous system of the Jack Engine.
    All disk I/O for the 20-worker Gemma swarm and the native IDE agent
    flows through this single-threaded serializer.
    """

    def __init__(self, session_id: str = "default", expected_workers: int = 20):
        self.session_id = session_id
        self.expected_workers = expected_workers
        self.workspace_root = WORKSPACE_ROOT.resolve()
        self.session_dir = self.workspace_root / "sessions" / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.socket_path = f"/tmp/swarm-mediator-{self.session_id}.sock"
        self.server = None
        self.anchor_config = self._load_anchor()
        self.frozen_files = self._parse_frozen_files()
        self.active_layers: dict[str, SocialStateMachine] = {}
        self.state = "INIT"
        self.idea_pool: list = []
        
        self.barrier = EpochBarrier(expected_workers=self.expected_workers, timeout=15.0)
        self.halting_controller = HaltingController()
        self.barrier.start_epoch() # Initialize first clock

        budget = TokenBudget()
        normalizer = ContextNormalizer(budget)
        self.assembler_factory = PromptAssemblerFactory(budget, normalizer)

        logger.info(f"Workspace root: {self.workspace_root}")
        logger.info(f"Anchor loaded. Frozen files: {self.frozen_files}")

    # ──────────── ANCHOR LOADER ────────────
    def _load_anchor(self) -> dict:
        """Load and parse anchor.yaml — the immutable project law."""
        if not ANCHOR_PATH.exists():
            logger.warning(f"anchor.yaml not found at {ANCHOR_PATH}. Running without anchor constraints.")
            return {}
        try:
            with open(ANCHOR_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            if config is None:
                config = {}
            logger.info("anchor.yaml loaded successfully.")
            return config
        except Exception as e:
            logger.error(f"Failed to parse anchor.yaml: {e}. Running without anchor constraints.")
            return {}

    def _parse_frozen_files(self) -> list[str]:
        """Extract the list of immutable file patterns from anchor config."""
        frozen = self.anchor_config.get("FROZEN_FILES", [])
        if frozen is None:
            frozen = []
        return [str(f) for f in frozen]

    # ──────────── ANCHOR GUARD ────────────
    def validate_request(self, target_path: Path, action: str) -> tuple[bool, str]:
        """
        Anchor Guard: Verify every I/O request against anchor.yaml rules.
        """
        try:
            resolved = target_path.resolve(strict=False)
        except (OSError, ValueError) as e:
            return False, f"Path resolution failed: {e}"

        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            return False, f"ACCESS DENIED: {resolved} is outside workspace root {self.workspace_root}"

        if action in ("write", "delete"):
            anchor_resolved = ANCHOR_PATH.resolve()
            if resolved == anchor_resolved:
                return False, "ANCHOR VIOLATION: anchor.yaml is an immutable contract. Writes forbidden."

        if action in ("write", "delete") and self.frozen_files:
            for pattern in self.frozen_files:
                if resolved.match(pattern) or resolved.name == pattern:
                    return False, f"ANCHOR VIOLATION: {resolved.name} matches frozen pattern '{pattern}'"

        logger.debug(f"Guard PASS: action={action}, target={resolved}")
        return True, "PASS"

    # ──────────── POSIX ATOMIC WRITE ────────────
    def atomic_write(self, target_path: Path, content: str) -> bool:
        """
        POSIX Atomic Write Protocol
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f".{target_path.name}.tmp")

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            os.rename(temp_path, target_path)

            dir_fd = os.open(str(target_path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

            logger.info(f"Atomic write complete: {target_path}")
            return True

        except Exception as e:
            if temp_path.exists():
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            logger.error(f"Atomic write FAILED for {target_path}: {e}")
            raise

    # ──────────── CLIENT HANDLER ────────────
    def handle_client(self, conn: socket.socket) -> None:
        try:
            chunks = []
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            raw_data = b"".join(chunks).decode("utf-8")

            if not raw_data.strip():
                self._send_response(conn, "NACK", reason="Empty payload received")
                return

            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError as e:
                self._send_response(conn, "NACK", reason=f"Malformed JSON: {e}")
                return

            action = payload.get("action")
            target_rel = payload.get("target_file")
            content = payload.get("content", "")
            requester = payload.get("requester", "unknown")
            role = payload.get("role", "BUILDER")
            glow = payload.get("glow", 0)
            current_epoch = payload.get("epoch", 0)

            if action not in ("status", "suspend", "wakeup", "shutdown", "load_queue", "pop_idea", "record_residue", "fact_inject", "steer", "worker_exit"):
                if self.halting_controller.evaluate_worker(requester, role, current_epoch, glow):
                    self._send_response(conn, "NACK", reason="Worker halted by HaltingController.")
                    return

            self.barrier.checkin(requester)

            if action in ("status", "suspend", "wakeup", "shutdown", "load_queue", "pop_idea", "record_residue", "fact_inject", "steer", "worker_exit"):
                if action == "status":
                    self._send_response(conn, "ACK", payload=json.dumps({
                        "daemon_state": self.state,
                        "daemon_pid": os.getpid(),
                        "ideas_remaining": len(self.idea_pool),
                        "active_layers": list(self.active_layers.keys())
                    }))
                elif action == "suspend":
                    self.state = "SUSPEND"
                    logger.info("Daemon state transitioned to SUSPEND.")
                    self._send_response(conn, "ACK", reason="State transitioned to SUSPEND")
                elif action == "wakeup":
                    self.state = "RUNNING"
                    logger.info("Daemon state transitioned to RUNNING.")
                    self._send_response(conn, "ACK", reason="State transitioned to RUNNING")
                elif action == "shutdown":
                    logger.info("Shutdown action received.")
                    self._send_response(conn, "ACK", reason="Shutdown initiated")
                    raise DaemonShutdownRequest()
                elif action == "worker_exit":
                    self._send_response(conn, "ACK", reason="Worker exit registered")
                elif action == "load_queue":
                    pool_file_rel = payload.get("pool_file")
                    if pool_file_rel:
                        pool_file = Path(pool_file_rel)
                        if not pool_file.is_absolute():
                            pool_file = self.workspace_root / pool_file_rel
                    else:
                        pool_file = self.session_dir / "idea_pool.json"

                    self._active_pool_file = pool_file

                    if pool_file.exists():
                        try:
                            with open(pool_file, "r", encoding="utf-8") as f:
                                self.idea_pool = json.load(f)
                            logger.info(f"Loaded {len(self.idea_pool)} ideas from {pool_file}")
                            self._send_response(conn, "ACK", reason=f"Loaded {len(self.idea_pool)} ideas from {pool_file.name}")
                        except Exception as e:
                            self._send_response(conn, "NACK", reason=f"Failed to load pool: {e}")
                    else:
                        self._send_response(conn, "NACK", reason=f"Pool file not found: {pool_file}")
                elif action == "pop_idea":
                    if self.idea_pool:
                        idea = self.idea_pool.pop(0)
                        try:
                            active_pool = getattr(self, "_active_pool_file",
                                                  self.session_dir / "idea_pool.json")
                            active_pool.parent.mkdir(parents=True, exist_ok=True)
                            with open(active_pool, "w", encoding="utf-8") as f:
                                json.dump(self.idea_pool, f, indent=2)
                        except Exception as e:
                            logger.error(f"Failed to persist popped pool: {e}")
                        self._send_response(conn, "ACK", payload=json.dumps(idea))
                    else:
                        self._send_response(conn, "EMPTY", reason="No ideas remaining in pool")
                elif action == "steer":
                    steer_prompt = payload.get("prompt")
                    layer_index = payload.get("layer")
                    if not steer_prompt:
                        self._send_response(conn, "NACK", reason="Missing 'prompt' for steer action")
                    else:
                        if not hasattr(self, "idea_pool") or self.idea_pool is None:
                            self.idea_pool = []
                        new_idea = {
                            "id": f"steer_{int(datetime.now().timestamp())}",
                            "prompt": steer_prompt,
                            "description": "Mid-flight steering constraint injected by IDE agent",
                            "classification": "SWARM"
                        }
                        self.idea_pool.append(new_idea)
                        active_pool = self.session_dir / f"idea_pool_layer_{layer_index}.json" if layer_index else getattr(self, "_active_pool_file", self.session_dir / "idea_pool.json")
                        try:
                            active_pool.parent.mkdir(parents=True, exist_ok=True)
                            with open(active_pool, "w", encoding="utf-8") as f:
                                json.dump(self.idea_pool, f, indent=2)
                            logger.info(f"Steering prompt injected: '{steer_prompt}' saved to {active_pool}")
                            self._send_response(conn, "ACK", reason=f"Steering constraint injected into active pool for layer {layer_index or 'default'}")
                        except Exception as e:
                            logger.error(f"Failed to persist steered pool: {e}")
                            self._send_response(conn, "NACK", reason=f"Failed to persist steered pool: {e}")

                elif action == "record_residue":
                    residue = payload.get("residue")
                    layer_index = payload.get("layer_index")
                    if residue:
                        residues = []
                        ledger_file_rel = payload.get("ledger_file")
                        if ledger_file_rel:
                            residue_file = Path(ledger_file_rel)
                            if not residue_file.is_absolute():
                                residue_file = self.workspace_root / ledger_file_rel
                        else:
                            residue_file = self.session_dir / f"residue_ledger_layer_{layer_index}.json" if layer_index else self.session_dir / "residue_ledger.json"

                        residue_file.parent.mkdir(parents=True, exist_ok=True)
                        if residue_file.exists():
                            try:
                                with open(residue_file, "r", encoding="utf-8") as f:
                                    residues = json.load(f)
                            except Exception:
                                pass
                        residues.append(residue)
                        try:
                            with open(residue_file, "w", encoding="utf-8") as f:
                                json.dump(residues, f, indent=2)
                        except Exception as e:
                            logger.error(f"Failed to save residue: {e}")

                        self._send_response(conn, "ACK", reason=f"Residue recorded to {residue_file.name}")
                    else:
                        self._send_response(conn, "NACK", reason="Missing 'residue' parameter in payload")
                elif action == "fact_inject":
                    claim_id = payload.get("claim_id")
                    verdict = payload.get("verdict")
                    layer = payload.get("layer")
                    if not claim_id or not verdict or not layer:
                        self._send_response(conn, "NACK",
                                             reason="Missing 'claim_id', 'verdict', or 'layer' in payload")
                    elif verdict not in ("CONFIRMED", "REFUTED"):
                        self._send_response(conn, "NACK",
                                             reason=f"Invalid verdict '{verdict}'. Must be CONFIRMED or REFUTED.")
                    else:
                        ssm = self.active_layers.get(layer)
                        if ssm and hasattr(ssm, "claim_registry"):
                            ssm.claim_registry.inject_verdict(claim_id, verdict)
                            try:
                                ledger = MarkdownLedger(self.workspace_root)
                                rel_path, content = ledger.generate_claim_registry_markdown(
                                    ssm.claim_registry
                                )
                                abs_path = self.workspace_root / rel_path
                                abs_path.parent.mkdir(parents=True, exist_ok=True)
                                tmp_path = abs_path.with_suffix(".tmp")
                                with open(tmp_path, "w", encoding="utf-8") as f:
                                    f.write(content)
                                    f.flush()
                                    import os as _os
                                    _os.fsync(f.fileno())
                                tmp_path.rename(abs_path)
                                logger.info(f"FACT_INJECT: Claim {claim_id[:12]} -> {verdict} "
                                            f"(layer {layer}). Registry re-written.")
                                self._send_response(conn, "ACK",
                                                     reason=f"Claim {claim_id[:12]} marked {verdict}")
                            except Exception as e:
                                logger.error(f"FACT_INJECT persistence failed: {e}")
                                self._send_response(conn, "ACK",
                                                     reason=f"Verdict applied in-memory but persistence failed: {e}")
                        else:
                            self._send_response(conn, "NACK",
                                                 reason=f"No active SocialStateMachine for layer '{layer}'.")
                return

            if not action or not target_rel and action not in ("meme", "steer"):
                self._send_response(conn, "NACK", reason="Missing required fields: 'action' and 'target_file'")
                return

            if action not in ("read", "write", "meme", "steer"):
                self._send_response(conn, "NACK", reason=f"Unknown action: '{action}'. Allowed: read, write, meme, steer")
                return


            if action == "meme":
                self._handle_meme(conn, payload, requester)
                return

            if action == "write" and not content:
                self._send_response(conn, "NACK", reason="Write action requires non-empty 'content' field")
                return

            target_path = (self.workspace_root / target_rel).resolve()

            logger.info(f"[{requester}] {action.upper()} → {target_rel}")

            allowed, guard_reason = self.validate_request(target_path, action)
            if not allowed:
                logger.warning(f"[{requester}] BLOCKED: {guard_reason}")
                self._send_response(conn, "NACK", reason=guard_reason)
                return

            if action == "read":
                if not target_path.exists():
                    self._send_response(conn, "NACK", reason=f"File not found: {target_rel}")
                else:
                    with open(target_path, "r", encoding="utf-8") as f:
                        file_content = f.read()
                    self._send_response(conn, "ACK", payload=file_content)
                    logger.info(f"[{requester}] READ complete: {target_rel} ({len(file_content)} bytes)")

            elif action == "write":
                self.atomic_write(target_path, content)
                self._send_response(conn, "ACK", reason="Atomic write committed successfully")
                logger.info(f"[{requester}] WRITE complete: {target_rel} ({len(content)} bytes)")

            if self.barrier.is_ready():
                logger.info("EpochBarrier ready. Triggering flush and step.")
                self.barrier.start_epoch()

        except DaemonShutdownRequest:
            raise
        except Exception as e:
            logger.error(f"handle_client exception: {e}", exc_info=True)
            try:
                self._send_response(conn, "NACK", reason=f"Internal daemon error: {str(e)}")
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _send_response(self, conn: socket.socket, status: str,
                       reason: str = "", payload: str = "") -> None:
        response = {
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if reason:
            response["reason"] = reason
        if payload:
            response["payload"] = payload
        try:
            conn.sendall(json.dumps(response).encode("utf-8"))
        except BrokenPipeError:
            logger.warning("Client disconnected before response could be sent.")

    def _handle_meme(self, conn: socket.socket, payload: dict, requester: str) -> None:
        layer_index = payload.get("layer_index")
        if not layer_index:
            self._send_response(conn, "NACK", reason="Missing 'layer_index' for meme action")
            return

        if layer_index not in self.active_layers:
            seed_prompt = payload.get("content", "Empty Seed")
            self.active_layers[layer_index] = SocialStateMachine(layer_index, seed_prompt)
            logger.info(f"[{requester}] Instantiated new SocialStateMachine for layer {layer_index}")

        state_machine = self.active_layers[layer_index]
        response_dict = state_machine.ingest_tweet(payload)
        
        signals = []
        if response_dict.get("status") == "ACK":
            meme_type = payload.get("meme_type")
            if meme_type in ("PROPOSAL", "CHALLENGE", "SYNTHESIS"):
                raw_claims = payload.get("claims", [])
                triggered_claims = state_machine.claim_registry.register_claims(
                    requester, raw_claims, state_machine.round_number, state_machine.worker_count
                )
                for cid in triggered_claims:
                    signals.append(f"REQUEST_GROUND:{cid}")

            elif meme_type == "FACT_INJECT":
                claim_id = payload.get("claim_id")
                verdict = payload.get("verdict")
                if claim_id and verdict:
                    state_machine.claim_registry.inject_verdict(claim_id, verdict)

            try:
                ledger = MarkdownLedger(self.workspace_root)
                branch_rel, branch_content = ledger.generate_layer_branches_markdown(state_machine)
                self.atomic_write((self.workspace_root / branch_rel).resolve(), branch_content)
                
                registry_rel, registry_content = ledger.generate_claim_registry_markdown(state_machine.claim_registry)
                self.atomic_write((self.workspace_root / registry_rel).resolve(), registry_content)
                logger.info(f"[{requester}] MEME processed, state persisted to Markdown ledger")
            except Exception as e:
                logger.error(f"Failed to persist state: {e}")

            # Autonomous adversarial loop: append new ideas generated by state transition
            new_ideas = response_dict.get("new_ideas", [])
            if new_ideas:
                if not hasattr(self, "idea_pool") or self.idea_pool is None:
                    self.idea_pool = []
                self.idea_pool.extend(new_ideas)
                active_pool = getattr(self, "_active_pool_file", self.session_dir / f"idea_pool_layer_{layer_index}.json")
                try:
                    active_pool.parent.mkdir(parents=True, exist_ok=True)
                    with open(active_pool, "w", encoding="utf-8") as f:
                        json.dump(self.idea_pool, f, indent=2)
                    logger.info(f"Automatically queued {len(new_ideas)} new ideas to active pool: {active_pool}")
                except Exception as e:
                    logger.error(f"Failed to persist dynamically queued ideas: {e}")


        final_response = {
            "status": response_dict.get("status", "NACK"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": response_dict.get("reason", ""),
            "signals": signals,
            "current_phase": response_dict.get("current_phase", state_machine.phase.value),
            "round_number": state_machine.round_number
        }
        try:
            conn.sendall(json.dumps(final_response).encode("utf-8"))
        except BrokenPipeError:
            logger.warning("Client disconnected before response could be sent.")

    def run(self):
        if os.path.exists(self.socket_path):
            logger.warning(f"Removing stale socket at {self.socket_path}")
            os.remove(self.socket_path)

        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.socket_path)
        self.server.listen(128)

        logger.info(f"Data Manager listening on {self.socket_path} ...")
        logger.info("Serial execution mode: one connection at a time.")

        def _shutdown(signum, frame):
            logger.info(f"Received signal {signum}. Shutting down gracefully.")
            self._cleanup()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        try:
            while True:
                conn, _ = self.server.accept()
                try:
                    self.handle_client(conn)
                except DaemonShutdownRequest:
                    logger.info("Shutdown requested via socket control command. Exiting.")
                    break
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Shutting down.")
        finally:
            self._cleanup()

    def _cleanup(self):
        if self.server:
            self.server.close()
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        logger.info("Cleanup complete.")

from attention_variants import DecoupledPositionTagger

class GoblinResourceController:
    def __init__(self, token_limit: int = 6000):
        self.token_limit = token_limit

    def emergency_compress(self, pool_data: dict) -> dict:
        current = pool_data["epoch_watermark"]
        
        for c in pool_data["claims"].values():
            if len(c["digest"]) > 40:
                c["digest"] = c["digest"][:37] + "..."

        to_drop = [
            cid for cid, c in pool_data["claims"].items()
            if c["status"] == "PENDING" and c["epoch_born"] < current - 1 and not c["anchor_touch"]
        ]
        for cid in to_drop:
            del pool_data["claims"][cid]

        return pool_data

class FlatPromptAssembler:
    def assemble(self, anchor: str, pool_data: dict, directive: str) -> str:
        goblin = GoblinResourceController()
        pool_chars = sum(len(str(c)) for c in pool_data.get("claims", {}).values())
        estimated_tokens = pool_chars // 4
        
        if estimated_tokens > goblin.token_limit:
            pool_data = goblin.emergency_compress(pool_data)

        lines = [
            "<PROMPT_PAYLOAD>",
            f"<ANCHOR>{anchor}</ANCHOR>",
            "<SEMANTIC_POOL>"
        ]
        
        tagger = DecoupledPositionTagger()
        for cid, c in pool_data.get("claims", {}).items():
            pos = tagger.tag(c.get("epoch_born", 0), "sys") 
            lines.append(tagger.build_flat_xml_node(cid, pos, c.get("digest", ""), c.get("status", "PENDING")))
            
        lines.append("</SEMANTIC_POOL>")
        lines.append(f"<DIRECTIVE>{directive}</DIRECTIVE>")
        lines.append("</PROMPT_PAYLOAD>")
        return "\n".join(lines)

class PromptAssemblerFactory:
    def __init__(self, budget: TokenBudget, normalizer: ContextNormalizer):
        self.legacy_assembler = PromptAssembler(budget, normalizer)
        self.flat_assembler = FlatPromptAssembler()

    def route_and_assemble(self, anchor: str, registry, pool_data: dict, epoch: int, directive: str) -> str:
        if epoch <= 3:
            return self.legacy_assembler.assemble(anchor, registry, epoch)
        else:
            return self.flat_assembler.assemble(anchor, pool_data, directive)


if __name__ == "__main__":
    import sys
    session_id = sys.argv[1] if len(sys.argv) > 1 else "default"
    try:
        expected_workers = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    except ValueError:
        expected_workers = 20
        
    daemon = DataManagerDaemon(session_id=session_id, expected_workers=expected_workers)
    daemon.run()
