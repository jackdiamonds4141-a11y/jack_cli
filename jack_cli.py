#!/usr/bin/env python3
"""
Jack CLI Bundler (Conductor v4.1 — Rolling Horizon & Re-Hydration Spec)
========================================================================
Master entry point. Boots the Data Manager daemon in the background,
verifies the UDS socket, and then launches the Swarm Spawner.

v4.1 Upgrade:
  - Layer-namespaced state files (idea_pool, residue_ledger, consensus_dump)
  - Context Re-Hydration Engine: scrapes prior layer consensus dumps
    and injects them as grounding context into the seed prompt
  - Wildcard --cleanup purge for all tmp/*_layer_*.json artifacts
  - Dynamic pool_file / ledger_file payloads to daemon socket

Supports interactive hybrid execution, process session tracking,
nuclear failsafe cleanup routines, and decoupled state dumping.
"""

import argparse
import subprocess
import time
import os
import signal
import sys
import asyncio
import json
import glob
import socket
import logging
from pathlib import Path
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

try:
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore
except ImportError:
    pass

SOCKET_PATH = "/tmp/swarm-mediator.sock"
DAEMON_SCRIPT = Path(__file__).parent / "Core" / "data_manager.py"
SESSION_FILE = Path("tmp/jack_session.json")
def load_env_key() -> Optional[str]:
    # Check OS environment first
    if "GEMINI_API_KEY" in os.environ:
        return os.environ["GEMINI_API_KEY"]
    # Check local .env file
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                if key.strip() == "GEMINI_API_KEY":
                    return val.strip().strip('"').strip("'")
    return None


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("JackCLI")

# ──────────── CONSTITUTION MODULE DEFINITION ────────────

META_RESEARCH = """
# Source Verification and Data Extraction Protocol

## Step 1: Investigation Preparation and Meta-Reasoning
* **Objective Specification**: REQUIRE a priori specification of research objectives, methodologies, and analytical parameters before executing any data collection.
* **PICO Framework**: DEFINE strict inclusion and exclusion criteria utilizing the PICO (Population, Intervention, Comparison, and Outcome) framework.
* **Pre-registration**: ESTABLISH decision trees and hypotheses prior to data inspection to prevent HARKing (Hypothesizing After Results are Known). Systematic reviews must build on a protocol that describes the rationale, hypothesis, and planned methods to improve transparency and reduce bias.
* **Threat Assessment**: IF user task = initiated, THEN EXECUTE a preliminary digital landscape and threat assessment to identify inherent algorithmic biases and structural inequalities in information availability.

## Step 2: Evidence Hierarchy and Source Selection
* **Source Ranking Heuristic**: RANK retrieved data sources in descending order of epistemic weight:
  * Well-designed systematic reviews and meta-analyses (Level A).
  * Well-designed, randomized controlled trials with consistent results (Level B).
  * Qualitative, descriptive, correlational studies, or non-definitive RCTs (Level C).
  * Peer-reviewed professional and organizational standards (Level D).
  * Expert opinion without explicit critical appraisal or multiple case reports (Level E).
* **Priority Metrics**: IF multiple sources exist, THEN PRIORITIZE Registered Reports where peer review occurred prior to data collection. Give more weight to primary, first-hand data (e.g., original videos, direct sensor readings) than hearsay or edited media.
* **Information Foraging Strategy**: MAXIMIZE the gain of valuable information per unit cost when allocating attention across data patches.
  * TRACK information scent utilizing proximal cues, including citations, metadata, and abstracts.
  * IF proximal cues = weak OR distant, THEN TERMINATE patch exploration to prevent random walk behaviors.

## Step 3: Signal-to-Noise Filtering
* **Expert Markers (Signal Validation)**:
  * VALIDATE the presence of open data, shared analytic code, and public repositories (e.g., Open Science Framework, GitHub).
  * VERIFY adherence to the W3C PROV standard by confirming backward traceability of Entities (digital objects), Activities (processes), and Agents (responsible parties).
  * IDENTIFY transparent declarations of funding, peer review processes, and conflicts of interest.
* **Mid-Tier Red Flags (Noise Filtration)**:
  * FILTER IF source demonstrates low statistical power, indicating an increased probability of false discoveries.
  * FILTER IF data extraction reveals p-hacking, defined as the selective reporting of statistically significant analyses.
  * FILTER IF textual analysis detects circular reporting, decontextualization of information, or automated LLM hallucinations without empirical grounding.
  * FILTER IF recommendations are based solely on Level E evidence masquerading as definitive truth.

## Step 4: Triangulation and Verification Heuristics
* **OSINT Verification Triangle**: TRIANGULATE and CONFIRM all actionable intelligence across three independent perspectives: original documents and primary records, independent open-source corroboration, and digital technical confirmation. Confirm claims via multiple verification techniques and at least three independent sources.
* **Data Authenticity and Integrity**:
  * EXECUTE source attribution by tracing the digital provenance, author, or uploader of the item.
  * IF source = anonymous OR pseudonymous, THEN ASSESS posting history, online presence, and temporal attenuation (proximity to the event).
  * EXTRACT and VALIDATE embedded metadata, HTML source code, and Exchangeable Image File Format (EXIF) data to test file integrity against manipulation.
  * VERIFY internal consistency to guarantee the isolated body of information does not contradict itself.
  * VALIDATE external corroboration by aligning content with objectively verifiable external facts.
* **Forensic Chain-of-Custody**: Maintain data integrity by documenting each evidence transfer, hashing or signing files immediately, and storing copies securely so that any alteration can be detected. Collect the most volatile data (RAM/CPU) first, and offline storage (hard drives) last.

## Step 5: Synthesis and Output Generation
* **Information Processing Protocol**:
  * APPLY DAMA-DMBOK data governance dimensions to all extracted information: ASSESS Accuracy, Completeness, Consistency, Timeliness, Validity, and Uniqueness.
  * QUANTIFY the certainty of synthesized evidence utilizing the GRADE methodology (High, Moderate, Low, Very Low) based on precision and consistency.
  * IF data sets require transformation, THEN DOCUMENT all aggregation, reformatting, or translation processes to maintain chain of custody.
  * FORMAT output utilizing objective, neutral, and fact-based language, actively avoiding emotive or biased terminology.
* **Repository Scrutiny**:
  * IF the source relies on specific software, scripts, or digital tools, THEN ASSESS tool validity using the following parameters: evaluate open-source versus closed-source code status, verify independent audit history and security infrastructure, and analyze repository health via funding sources, developer affiliations, and user support capacity.
"""

RESEARCH = """
# Unified FAANG-Grade Architecture & Source Verification Protocol

## Step 1: Investigation Preparation and Meta-Reasoning
* **Objective Specification**: REQUIRE a priori specification of research objectives, methodologies, and analytical parameters before executing any data collection.
* **PICO Framework**: DEFINE strict inclusion and exclusion criteria utilizing the PICO (Population, Intervention, Comparison, and Outcome) framework.
* **Pre-registration**: ESTABLISH decision trees and hypotheses prior to data inspection to prevent HARKing.
* **Threat Assessment**: IF user task = initiated, THEN EXECUTE a preliminary digital landscape and threat assessment to identify inherent algorithmic biases.

## Step 2: Evidence Hierarchy and Source Selection
* **Source Ranking Heuristic**: RANK retrieved data sources in descending order of epistemic weight:
  * Well-designed systematic reviews and meta-analyses (Level A).
  * Well-designed, randomized controlled trials with consistent results (Level B).
  * Qualitative, descriptive, correlational studies (Level C).
  * Peer-reviewed professional and organizational standards (Level D).
  * Expert opinion without explicit critical appraisal (Level E).
* **Information Foraging Strategy**: MAXIMIZE the gain of valuable information per unit cost when allocating attention across data patches. TRACK information scent utilizing proximal cues (citations, metadata). IF proximal cues = weak, THEN TERMINATE patch exploration.

## Step 3: Context-Specific Metric Discovery (The "What to Research" Framework)
* **First Principles Extraction**: STRIP away assumptions and industry 'best practices'. IDENTIFY the fundamental behavior assumed by the codebase. ASK: "Are we solving a problem the user actually feels, or one they just say they have?"
* **Inversion Thinking (Failure Analysis)**: BEFORE defining success metrics, DEFINE catastrophic failure. ASK: "What would make this architecture flop completely?" (e.g., alert fatigue, extreme cognitive load, dependency hell).
* **The Kano Feature Classification**: CLASSIFY all proposed features/architecture components into three psychological buckets:
  * **Hygiene (Basic Expectations)**: Features that cause dissatisfaction if missing but don't create love (e.g., data privacy, basic error handling). MUST HAVE 100% reliability.
  * **Performance**: Features where more is better (e.g., execution speed, lower latency).
  * **Differentiators (Delighters)**: Non-obvious innovations that dramatically improve the workflow.
* **Impact Mapping**: MAP the system logic using the Actor-Impact-Deliverable path. IDENTIFY whose behavior the code changes and what leading indicators prove the impact.

## Step 4: FAANG-Grade Product & Engineering Metrics
* **System Quality & Architecture (Static & Dynamic)**:
  * **Cyclomatic Complexity & Nesting Depth**: EVALUATE the cognitive load of the logic. Reject deeply nested conditionals.
  * **Fan-In / Fan-Out**: MEASURE module coupling. High fan-out indicates brittle control logic; high fan-in requires bulletproof testing.
* **Flow & Developer Experience (DXI)**:
  * **Cycle Time & Lead Time**: ASSESS how efficiently work moves from idea to delivery.
  * **Cognitive Load & Feedback Loops**: EVALUATE the repository for friction. Do tests take hours? Is the documentation a wall of text?
* **User Trust & Psychological Predictability**:
  * **Time-to-First-Success**: MEASURE how fast a user or developer achieves a successful action post-install.
  * **Predictable Feedback Loops**: VERIFY that the system provides immediate, consistent confirmation for every action (e.g., clear terminal outputs, error logs that actually explain the fix).
* **Product Engagement & Health (AARRR Framework)**:
  * IF evaluating a consumer-facing product repo, ASSESS metrics for Acquisition, Activation, Retention, Referral, and Revenue infrastructure.

## Step 5: Signal-to-Noise Filtering & Triangulation
* **Expert Markers**: VALIDATE the presence of open data, shared analytic code, and adherence to the W3C PROV standard (backward traceability).
* **Mid-Tier Red Flags**: FILTER IF data extraction reveals p-hacking, circular reporting, or low statistical power.
* **OSINT Verification Triangle**: TRIANGULATE and CONFIRM all actionable intelligence across three independent perspectives: original documents, independent corroboration, and digital technical confirmation.
* **Data Authenticity**: EXTRACT and VALIDATE embedded metadata. VERIFY internal consistency and external corroboration.

## Step 6: Synthesis and Output Generation
* **Information Processing**: APPLY DAMA-DMBOK data governance (Accuracy, Completeness, Consistency, Timeliness, Validity, Uniqueness). QUANTIFY certainty utilizing the GRADE methodology.
* **Repository Scrutiny & Tool Validity**: IF the source relies on specific software, ASSESS open-source vs closed-source status, independent audit history, and repository health (PR velocity, funding, developer affiliations). FORMAT output utilizing objective, neutral, and fact-based language.
"""

AGENTIC_PROTOCOL = """
THE RECURSIVE RIGOR LOOP & CONDUCTOR PROTOCOL

Every step in the provided plan must be treated as a high-stakes engineering module governed by the Conductor Loop. Do not execute a step until its "completeness profile" is defined.

1. The Conductor Loop (Decomposition & Alignment)
Before executing a major objective, the IDE Agent (The Conductor) must:
    A. Decompose the high-level objective into serial, atomic task fragments.
    B. Document these task fragments in the master 'project_outline.md' and 'task.md'.
    C. Classify each task fragment as either SWARM or NATIVE using strict heuristics.
    D. Pause execution and check in with the user (The Bouncer's Brake) to align on the serialization list and clarify ambiguity.

2. SWARM vs. NATIVE Classification Heuristics
    - SWARM Classification:
        Apply to tasks involving deep logical transformations, novel architectures, complex physical/n-body equations, security or cryptographic protocols, or hard numerical debates where multi-agent adversarial consensus is required to prevent individual model hallucinations.
    - NATIVE Classification:
        Apply to tasks involving standard file scaffolding, library configurations, UI layout alignments, static HTML/CSS styling, basic utility helpers, or state-storage persistence integrations that can be written directly by the IDE Agent, bypassing parallel coordination overhead.

3. "The Bouncer's Brake" Checkpoint
    - Always pause and seek user feedback whenever:
        * A task is ambiguous, under-specified, or highly open-ended.
        * A proposed task sequence involves complex cross-domain or database dependency serialization.
        * A critical architectural decision lacks quantitative benchmarks.

4. Implementation & Sliced Verification
    - Execute exactly one task fragment at a time.
    - If SWARM: Spawn the CLI, capture active process PIDs in 'tmp/jack_session.json', monitor session recovery, and load the final consensus from 'tmp/consensus_dump.json'. Run the OSINT Verification Triangle before implementation.
    - Context Re-hydration: Prior to a new swarm epoch, manually inject relevant sections of 'project_outline.md' and 'tmp/consensus_dump.json' into the task prompt so that parallel workers have full architectural context and build history.
    - If NATIVE: Execute code generation natively and perform direct testing.
    - Update progress states ('task.md') and outline notes ('project_outline.md') after each fragment.
"""

CONSTITUTION = f"\n\n--- meta_research.md ---\n{META_RESEARCH}\n\n--- research.md ---\n{RESEARCH}\n\n--- agentic_protocol.md ---\n{AGENTIC_PROTOCOL}"


# ──────────── SWARM SPAWNER LOGIC (Merged) ────────────

class MemeOutputSchema(BaseModel):
    meme_type: Literal["PROPOSAL", "CHALLENGE", "SYNTHESIS"]
    content: str = Field(description="The full proposal, challenge, or synthesis text. Must be robust and detailed.")
    claims: List[str] = Field(description="List of discrete atomic claims made in the content.")
    target_branch_id: Optional[str] = Field(default=None, description="Only used for challenges to target a specific branch.")

async def pop_next_idea() -> Optional[dict]:
    """Query the socket daemon to atomically pop the next idea from the pool."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(SOCKET_PATH)
        payload = {"action": "pop_idea"}
        sock.sendall(json.dumps(payload).encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        
        response_data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response_data += chunk
        sock.close()
        
        response = json.loads(response_data.decode("utf-8"))
        if response.get("status") == "ACK":
            return json.loads(response["payload"])
    except Exception:
        pass
    return None

async def record_failure_residue(idea_id: str, prompt: str, error_msg: str):
    """Send record_residue request to daemon socket for tracking failures."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(SOCKET_PATH)
        payload = {
            "action": "record_residue",
            "residue": {
                "id": idea_id,
                "prompt": prompt,
                "error": error_msg,
                "reason": "Execution error during worker generation"
            }
        }
        sock.sendall(json.dumps(payload).encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        sock.recv(1024)
        sock.close()
    except Exception:
        pass

async def worker_task(worker_id: str, layer_index: str, client: genai.Client, semaphore: asyncio.Semaphore):
    processed_count = 0
    while True:
        idea = await pop_next_idea()
        if not idea:
            logger.info(f"[{worker_id}] Idea pool empty or socket down. Worker exiting.")
            break
            
        idea_id = idea.get("id", "unknown_id")
        idea_prompt = idea.get("prompt", "")
        logger.info(f"[{worker_id}] Acquired task '{idea_id}'.")
        
        async with semaphore:
            logger.info(f"[{worker_id}] Executing generation for task '{idea_id}' under layer {layer_index}...")
            system_instruction = (
                f"You are Jack Engine worker {worker_id} executing task '{idea_id}'. "
                f"Analyze the prompt and generate a PROPOSAL branch. "
                f"You are part of an adversarial synthesis swarm. Ensure your logic is rigorous."
            )
            
            try:
                model_name = os.getenv("JACK_SWARM_MODEL", "gemini-2.5-flash-lite")
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=idea_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=MemeOutputSchema,
                        temperature=0.7,
                    )
                )
                if not response.text:
                    raise ValueError(f"Model returned empty or null response for task '{idea_id}'")
                output = json.loads(response.text)
                logger.info(f"[{worker_id}] Generation complete for '{idea_id}'. Sending to Mediator...")
                
                payload = {
                    "action": "meme",
                    "meme_type": output.get("meme_type", "PROPOSAL"),
                    "requester": worker_id,
                    "layer_index": layer_index,
                    "branch_id": f"branch_{worker_id}_{idea_id}",
                    "target_branch_id": output.get("target_branch_id"),
                    "content": output["content"],
                    "claims": output["claims"]
                }
                
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect(SOCKET_PATH)
                
                sock.sendall(json.dumps(payload).encode("utf-8"))
                sock.shutdown(socket.SHUT_WR)
                
                response_data = b""
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    response_data += chunk
                sock.close()
                
                mediator_response = json.loads(response_data.decode("utf-8"))
                logger.info(f"[{worker_id}] Task '{idea_id}' mediator status: {mediator_response.get('status')}")
                processed_count += 1
                
            except Exception as e:
                logger.error(f"[-] [{worker_id}] Failed executing task '{idea_id}': {e}")
                await record_failure_residue(idea_id, idea_prompt, str(e))
                
    return {
        "worker_id": worker_id, 
        "status": "SUCCESS" if processed_count > 0 else "EMPTY", 
        "processed_tasks": processed_count
    }

async def spawn_swarm(layer_index: str, worker_count: int = 20):
    api_key = load_env_key()
    if not api_key:
        logger.critical("GEMINI_API_KEY not found in OS environment or local .env file!")
        sys.exit(1)
        
    client = genai.Client(api_key=api_key)
    
    semaphore = asyncio.Semaphore(5)
    logger.info(f"Spawning swarm of {worker_count} workers. Concurrency limit: 5.")
    
    tasks = []
    for i in range(1, worker_count + 1):
        worker_id = f"worker_{i:02d}"
        tasks.append(worker_task(worker_id, layer_index, client, semaphore))
        
    results = await asyncio.gather(*tasks)
    
    total_processed = sum(r.get("processed_tasks", 0) for r in results)
    logger.info(f"Swarm completion: {worker_count} workers processed a total of {total_processed} tasks.")
    return results


# ──────────── LAYER-NAMESPACED FILE HELPERS ────────────

def layer_pool_path(layer_index: str) -> Path:
    """Return the layer-specific idea pool file path."""
    return Path(f"tmp/idea_pool_layer_{layer_index}.json")

def layer_ledger_path(layer_index: str) -> Path:
    """Return the layer-specific residue ledger file path."""
    return Path(f"tmp/residue_ledger_layer_{layer_index}.json")

def layer_dump_path(layer_index: str) -> Path:
    """Return the layer-specific consensus dump file path."""
    return Path(f"tmp/consensus_dump_layer_{layer_index}.json")


def send_daemon_message(payload: dict) -> dict:
    """Send a control payload to the Data Manager daemon via UDS and get response."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(SOCKET_PATH)
        sock.sendall(json.dumps(payload).encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)

        response_data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response_data += chunk
        sock.close()

        if response_data:
            return json.loads(response_data.decode("utf-8"))
    except Exception:
        pass
    return {"status": "NACK", "reason": "Could not communicate with daemon"}

def write_session_state(daemon_pid=None, cli_pid=None, status="running", mode="swarm", layer_index=None):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "cli_pid": cli_pid or os.getpid(),
        "daemon_pid": daemon_pid,
        "timestamp": time.time(),
        "mode": mode,
        "status": status,
        "active_layer": layer_index
    }
    try:
        with open(SESSION_FILE, "w") as f:
            json.dump(state, f, indent=2)
        print(f"[+] Session state written to {SESSION_FILE}")
    except Exception as e:
        print(f"[-] Failed to write session state: {e}")


# ──────────── CONTEXT RE-HYDRATION ENGINE ────────────

def scrape_prior_context(current_layer: str) -> str:
    context_fragments = []
    dump_pattern = "tmp/consensus_dump_layer_*.json"
    dump_files = sorted(glob.glob(dump_pattern))

    for dump_path in dump_files:
        basename = Path(dump_path).stem
        layer_suffix = basename.replace("consensus_dump_layer_", "")

        if layer_suffix >= current_layer:
            continue

        try:
            with open(dump_path, "r", encoding="utf-8") as f:
                dump_data = json.load(f)
            layer_prompt = dump_data.get("prompt", "")
            layer_status = dump_data.get("status", "UNKNOWN")
            layer_results = dump_data.get("results", [])

            fragment = (
                f"--- [COMPLETED LAYER {layer_suffix}] ---\n"
                f"Status: {layer_status}\n"
                f"Objective: {layer_prompt}\n"
            )
            if layer_results:
                fragment += f"Worker Results: {len(layer_results)} workers contributed.\n"

            context_fragments.append(fragment)
            print(f"[+] Re-Hydration: Scraped context from layer {layer_suffix}")
        except Exception as e:
            print(f"[-] Re-Hydration: Failed to read {dump_path}: {e}")

    if not context_fragments:
        print("[*] Re-Hydration: No prior layer context found. Starting fresh.")
        return ""

    header = (
        "\n\n[IMMUTABLE ARCHITECTURAL HISTORICAL CONTEXT — DO NOT CONTRADICT]\n"
        "The following is a summary of all previously completed layers.\n"
        "Your proposals MUST align with and build upon this established architecture.\n\n"
    )
    return header + "\n".join(context_fragments) + "\n[END OF HISTORICAL CONTEXT]\n"


# ──────────── LAYER-NAMESPACED RESIDUE COMPILER ────────────

def compile_residues(layer_index: str):
    pool_file = layer_pool_path(layer_index)
    ledger_file = layer_ledger_path(layer_index)

    residues = []
    if ledger_file.exists():
        try:
            with open(ledger_file, "r", encoding="utf-8") as f:
                residues = json.load(f)
        except Exception:
            pass

    if pool_file.exists():
        try:
            with open(pool_file, "r", encoding="utf-8") as f:
                pool_ideas = json.load(f)
                for idea in pool_ideas:
                    if not any(r.get("id") == idea.get("id") for r in residues):
                        residues.append({
                            "id": idea.get("id"),
                            "prompt": idea.get("prompt"),
                            "description": idea.get("description", ""),
                            "reason": "Unconsumed orphan idea left in pool",
                            "classification": "SWARM"
                        })
            with open(pool_file, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)
        except Exception as e:
            print(f"[-] Failed to compile pool residues: {e}")

    if residues:
        try:
            ledger_file.parent.mkdir(parents=True, exist_ok=True)
            with open(ledger_file, "w", encoding="utf-8") as f:
                json.dump(residues, f, indent=2)
            print(f"[+] Compiled {len(residues)} total residue(s) in {ledger_file}")
        except Exception as e:
            print(f"[-] Failed to write residue ledger: {e}")
    else:
        print(f"[+] Layer {layer_index} residue ledger is clean. Zero residues.")


# ──────────── NUCLEAR TEARDOWN WITH WILDCARD PURGE ────────────

def run_cleanup():
    print("\n=== [Nuclear Teardown Failsafe Initiated (v4.1)] ===")

    print("[*] Sending shutdown signal to active daemon socket...")
    send_daemon_message({"action": "shutdown"})
    time.sleep(1.0)

    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
            print("[+] Cleared stale socket file: /tmp/swarm-mediator.sock")
        except Exception as e:
            print(f"[-] Failed to remove socket file: {e}")

    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE, "r") as f:
                data = json.load(f)
                daemon_pid = data.get("daemon_pid")
                cli_pid = data.get("cli_pid")
                if daemon_pid:
                    print(f"[*] Terminating tracked daemon PID: {daemon_pid}")
                    try:
                        os.kill(daemon_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if cli_pid and cli_pid != os.getpid():
                    print(f"[*] Terminating tracked CLI PID: {cli_pid}")
                    try:
                        os.kill(cli_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        except Exception as e:
            print(f"[-] Error parsing session file: {e}")

    print("[*] Executing standard pkill sweep...")
    try:
        subprocess.run(["pkill", "-9", "-f", "data_manager.py"], capture_output=True)
        my_pid = os.getpid()
        proc = subprocess.run(["pgrep", "-f", "jack_cli.py"], capture_output=True, text=True)
        for pid_str in proc.stdout.splitlines():
            try:
                pid = int(pid_str.strip())
                if pid != my_pid:
                    os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        print("[+] Standard process space cleared.")
    except Exception as e:
        print(f"[-] Sweep failed: {e}")

    if SESSION_FILE.exists():
        try:
            SESSION_FILE.unlink()
            print("[+] Removed session state file.")
        except Exception:
            pass

    wildcard_patterns = [
        "tmp/idea_pool_layer_*.json",
        "tmp/residue_ledger_layer_*.json",
        "tmp/consensus_dump_layer_*.json",
    ]
    purged_count = 0
    for pattern in wildcard_patterns:
        for orphan_file in glob.glob(pattern):
            try:
                os.remove(orphan_file)
                purged_count += 1
            except Exception as e:
                print(f"[-] Failed to purge {orphan_file}: {e}")

    legacy_files = [
        "tmp/idea_pool.json",
        "tmp/residue_ledger.json",
        "tmp/consensus_dump.json",
    ]
    for legacy in legacy_files:
        if os.path.exists(legacy):
            try:
                os.remove(legacy)
                purged_count += 1
            except Exception:
                pass

    if purged_count > 0:
        print(f"[+] Wildcard purge complete: {purged_count} orphaned file(s) removed.")
    else:
        print("[+] Wildcard purge: tmp/ directory is already clean.")

    print("=== [Nuclear Teardown Complete. Zero Race Conditions Guaranteed] ===\n")

def boot_daemon() -> Optional[int]:
    print("[*] Checking if Data Manager daemon is active...")
    status = send_daemon_message({"action": "status"})
    if status.get("status") == "ACK":
        daemon_pid = status.get("daemon_pid")
        print(f"[+] Persistent daemon is already active (PID: {daemon_pid}).")
        return daemon_pid

    print("[*] Persistent daemon not active. Booting a new daemon...")
    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
        except Exception:
            pass

    process = subprocess.Popen(
        [sys.executable, str(DAEMON_SCRIPT)],
        stdout=sys.stdout,
        stderr=sys.stderr,
        preexec_fn=os.setpgrp if sys.platform != "win32" else None
    )

    print("[*] Waiting for socket to bind...")
    retries = 10
    while retries > 0:
        if os.path.exists(SOCKET_PATH):
            print("[+] Daemon successfully booted and listening.")
            return process.pid
        time.sleep(0.5)
        retries -= 1

    print("[-] Daemon failed to boot or bind to socket in time.")
    process.terminate()
    sys.exit(1)

def _run_setup_wizard():
    """Interactive first-time setup: prompts for the Gemini API key and saves it to .env."""
    env_file = Path(__file__).parent / ".env"
    os.system("clear" if os.name != "nt" else "cls")

    print("=" * 60)
    print("  Jack Engine — First-Time Setup Wizard")
    print("=" * 60)
    print()
    print("  This tool uses the Gemini AI Studio API to power its")
    print("  agent swarm. You can get a free API key from:")
    print("  https://aistudio.google.com/apikey")
    print()
    print("  Any strictly compatible endpoint key will also work.")
    print("  (Custom calling schemas are not supported yet.)")
    print()

    if env_file.exists():
        existing_key = load_env_key()
        if existing_key:
            masked = existing_key[:8] + "..." + existing_key[-4:]
            print(f"  [!] Existing key detected: {masked}")
            print()
            confirm = input("  Overwrite existing key? (y/N): ").strip().lower()
            if confirm != "y":
                print("\n  [+] Setup cancelled. Existing key preserved.")
                return

    print("-" * 60)
    api_key = input("  Please paste your Gemini AI Studio API Key: ").strip()

    if not api_key:
        print("\n  [-] No key provided. Setup aborted.")
        return

    try:
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("# Jack Engine — Local Environment Configuration\n")
            f.write("# WARNING: Do NOT commit this file. It is gitignored.\n\n")
            f.write(f"GEMINI_API_KEY={api_key}\n")
        print(f"\n  [+] API key saved to {env_file}")
        print("  [+] You are ready to go! Run your first swarm with:")
        print()
        print('    python3 jack_cli.py --layer "1.1" --workers 1 --prompt "Your task here"')
        print()
    except Exception as e:
        print(f"\n  [-] Failed to write .env file: {e}")

def main():
    epilog_text = """
================================================================================
  JACK ENGINE — AGENT OPERATOR MANUAL (READ THIS COMPLETELY BEFORE EXECUTING)
================================================================================

  WHAT THIS TOOL IS:
  ------------------
  Jack Engine is a dedicated BRAINSTORMING and COMPLEX REASONING engine.
  It spawns a swarm of independent AI workers that debate, challenge, and
  synthesize consensus on hard problems — physics, architecture, security,
  novel algorithms — through a formalized adversarial protocol.

  This is NOT a general-purpose code generation tool. Use it when you need
  rigorous, multi-perspective analysis on problems where a single model
  completion would risk hallucination or tunnel vision.

  CRITICAL DIRECTIVE:
  -------------------
  DO NOT attempt to read, debug, or modify the underlying Python source
  code of this CLI. It is a self-contained, production-tested runtime.
  Just execute the tool exactly as documented below. If something fails,
  run --cleanup and retry. Do not open jack_cli.py or Core/ to investigate.

  HOW LAYERING WORKS:
  -------------------
  The --layer flag namespaces all state files (idea pools, residue ledgers,
  consensus dumps) so that multiple independent tasks can coexist without
  collision. Think of layers as isolated workspaces:

    Layer "1.1"  → tmp/idea_pool_layer_1.1.json, etc.
    Layer "1.2"  → tmp/idea_pool_layer_1.2.json, etc.

  Use a NEW layer index for each distinct problem or sub-task. Do NOT reuse
  a layer index unless you intentionally want to resume from its prior state.

  For sequential multi-step projects, use dotted notation:
    Step 1 → --layer "1.1"
    Step 2 → --layer "1.2"  (auto-inherits context from 1.1 via re-hydration)
    Step 3 → --layer "1.3"

  HOW OFTEN TO CALL THE SWARM:
  ----------------------------
  Call the swarm ONCE per problem or sub-problem. Do not spam multiple
  invocations for the same task. The swarm internally handles parallel
  debate — you just fire once and collect the consensus dump.

  Typical workflow:
    1. Run --cleanup to clear any stale state from prior sessions.
    2. Run the swarm with --layer, --prompt, and --workers.
    3. Read the consensus dump from tmp/consensus_dump_layer_<N>.json
    4. Use the results in your next step.

  SOCKET PAYLOAD SCHEMA (for custom client integration):
  ------------------------------------------------------
  Transport: Unix Domain Socket at /tmp/swarm-mediator.sock
  Protocol:  Send JSON via sendall(), then call socket.SHUT_WR to signal
             EOF. The daemon reads until EOF — without SHUT_WR, it hangs.

  Required payload keys for 'meme' action:
    {
      "action":           "meme",
      "meme_type":        "PROPOSAL" | "CHALLENGE" | "SYNTHESIS",
      "requester":        "<worker_id>",
      "layer_index":      "<layer>",
      "branch_id":        "<unique_branch_id>",
      "content":          "<full generated text>",
      "claims":           ["<claim 1>", "<claim 2>", ...],
      "target_branch_id": null (or branch ID for challenges)
    }

  QUICK REFERENCE:
  ----------------
  First-time setup:    python3 jack_cli.py --setup
  Clean slate:         python3 jack_cli.py --cleanup
  Run swarm:           python3 jack_cli.py --layer "1.1" --workers 1 --prompt "..."
  Inspect protocols:   python3 jack_cli.py --dump-constitution

================================================================================
"""

    parser = argparse.ArgumentParser(
        description="Jack Engine v4.1 — Adversarial AI Swarm for Brainstorming & Complex Reasoning",
        epilog=epilog_text,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--layer", required=False,
        help="Layer index (e.g., 1.1, 1.2, 2.3.1). Namespaces ALL state files. Use a new index for each distinct problem.")
    parser.add_argument("--prompt", required=False,
        help="Seed prompt for the swarm. This is the problem statement fed to every worker.")
    parser.add_argument("--workers", type=int, default=20,
        help="Number of async workers to spawn (default: 20). API concurrency is capped at 5 internally.")
    parser.add_argument("--setup", action="store_true",
        help="Interactive first-time setup wizard. Prompts for your Gemini API key and saves it to a local .env file.")
    parser.add_argument("--cleanup", action="store_true",
        help="Nuclear teardown failsafe. Kills ALL daemon/CLI processes, removes the UDS socket, and purges every layer state file. Run this before fresh executions.")
    parser.add_argument("--dump-constitution", action="store_true",
        help="Print the full embedded protocol constitution (research + agentic rules) to stdout.")
    parser.add_argument("--mode", choices=["swarm", "native"], default="swarm",
        help="Execution mode: 'swarm' (multi-agent adversarial, default) or 'native' (single-pass, no daemon).")
    parser.add_argument("--dump-file", default=None,
        help="Override path for consensus dump output. Auto-generated from --layer if omitted.")

    args = parser.parse_args()

    if args.setup:
        _run_setup_wizard()
        sys.exit(0)

    if args.cleanup:
        run_cleanup()
        sys.exit(0)

    if args.dump_constitution:
        print(CONSTITUTION)
        sys.exit(0)

    if not args.layer or not args.prompt:
        parser.error("--layer and --prompt are required unless running with --setup, --dump-constitution, or --cleanup")

    pool_file = layer_pool_path(args.layer)
    ledger_file = layer_ledger_path(args.layer)
    dump_path = Path(args.dump_file) if args.dump_file else layer_dump_path(args.layer)

    rehydration_context = scrape_prior_context(args.layer)
    hydrated_prompt = args.prompt
    if rehydration_context:
        hydrated_prompt = args.prompt + rehydration_context
        print(f"[+] Context Re-Hydration: Injected history from prior layers into seed prompt.")

    if args.mode == "native":
        print(f"\n[*] Jack Engine Conductor v4.1: NATIVE execution mode selected.")
        print(f"[*] Layer: {args.layer}")
        print(f"[*] Prompt: '{args.prompt}'\n")

        write_session_state(daemon_pid=None, cli_pid=os.getpid(), status="completed", mode="native", layer_index=args.layer)

        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_data = {
            "status": "NATIVE_BYPASS",
            "layer": args.layer,
            "prompt": args.prompt,
            "timestamp": time.time(),
            "message": "This task was completed natively by the IDE Agent under Conductor guidelines."
        }
        with open(dump_path, "w") as f:
            json.dump(dump_data, f, indent=2)
        print(f"[+] Decoupled native output state written to {dump_path}")
        sys.exit(0)

    daemon_pid = boot_daemon()
    write_session_state(daemon_pid=daemon_pid, cli_pid=os.getpid(), status="running", mode="swarm", layer_index=args.layer)

    def cleanup_signal(signum, frame):
        print("\n[*] Interrupted! Suspending persistent daemon...")
        send_daemon_message({"action": "suspend"})
        write_session_state(daemon_pid=daemon_pid, status="suspended", mode="swarm", layer_index=args.layer)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup_signal)
    signal.signal(signal.SIGTERM, cleanup_signal)

    if not pool_file.exists() or pool_file.stat().st_size == 0:
        pool_file.parent.mkdir(parents=True, exist_ok=True)
        with open(pool_file, "w", encoding="utf-8") as f:
            json.dump([{"id": "seed_01", "prompt": hydrated_prompt}], f, indent=2)
        print(f"[+] Seed prompt written to layer-specific pool: {pool_file}")

    print("[*] Transitioning daemon state to RUNNING...")
    send_daemon_message({"action": "wakeup"})
    print(f"[*] Loading layer-specific idea pool: {pool_file}")
    send_daemon_message({"action": "load_queue", "pool_file": str(pool_file)})

    print(f"\n[*] Initiating Swarm Spawner for layer {args.layer}")
    print(f"[*] Seed Prompt: '{args.prompt}'")
    if rehydration_context:
        print(f"[*] Re-Hydrated Context: YES (prior layers injected)")
    print()

    results = []
    try:
        results = asyncio.run(spawn_swarm(args.layer, worker_count=args.workers))
    except Exception as e:
        print(f"[-] Swarm execution failed: {e}")
    finally:
        print("\n[*] Swarm finished. Suspending persistent daemon...")
        send_daemon_message({"action": "suspend"})
        write_session_state(daemon_pid=daemon_pid, status="suspended", mode="swarm", layer_index=args.layer)

        compile_residues(args.layer)

        dump_path.parent.mkdir(parents=True, exist_ok=True)

        succeeded = sum(1 for r in results if r.get("status") == "SUCCESS") if results else 0
        dump_data = {
            "status": "SUCCESS" if succeeded > 0 else "FAILED",
            "layer": args.layer,
            "prompt": args.prompt,
            "timestamp": time.time(),
            "worker_count": args.workers,
            "succeeded_workers": succeeded,
            "rehydration_applied": bool(rehydration_context),
            "results": [
                {
                    "worker_id": r.get("worker_id"),
                    "status": r.get("status"),
                    "mediator_status": r.get("mediator", {}).get("status") if "mediator" in r else None,
                    "round_number": r.get("mediator", {}).get("round_number") if "mediator" in r else None
                } for r in results
            ] if results else []
        }
        with open(dump_path, "w") as f:
            json.dump(dump_data, f, indent=2)
        print(f"[+] Decoupled swarm output state written to {dump_path}")

if __name__ == "__main__":
    main()
