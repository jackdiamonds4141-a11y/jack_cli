# Jack Engine CLI

A lightweight CLI that orchestrates local AI agent swarms under strict runtime constraint gates — adversarial multi-agent debate, claim-level verification, and POSIX-atomic state persistence — to produce research and engineering outputs that consistently out-reason multi-billion dollar flagship models. For free.

Instead of trusting a single LLM completion, Jack spawns a configurable swarm of workers that independently generate proposals, challenge each other's claims, and synthesize consensus through a formalized adversarial protocol. A central mediator daemon serializes all state through Unix Domain Sockets, enforces immutable anchor constraints, and persists everything via atomic writes. The result: hallucination-resistant, citation-grade output from cheap models.

---

## Getting Started

### 1. Clone

```bash
git clone https://github.com/jackdiamonds4141-a11y/jack_cli.git
cd jack_cli
```

### 2. Install Dependencies

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt
```

### 3. Set Up Your API Key

Jack Engine is built for the **Gemini AI Studio API**. Any strictly compatible endpoint will work — we just don't support custom calling schemas yet.

Get a free key from [Google AI Studio](https://aistudio.google.com/apikey), then run:

```bash
python3 jack_cli.py --setup
```

The setup wizard will prompt you to paste your key and save it to a local `.env` file that is automatically gitignored. That's it — you're ready to go.

> **Alternative**: If you prefer environment variables (useful for CI/containers), export directly:
> ```bash
> export GEMINI_API_KEY="your-key-here"
> ```
> The engine checks `os.environ` first, then falls back to `.env`.

### 4. Run Your First Swarm

```bash
python3 jack_cli.py --layer "1.1" --workers 1 \
  --prompt "Derive the critical measurement probability for MIPT in a 2D toric code."
```

---

## How It Works

```
┌─────────────┐     UDS Socket      ┌──────────────────┐
│  jack_cli.py │◄───────────────────►│  data_manager.py │
│  (Conductor) │  /tmp/swarm-        │  (Mediator Daemon)│
│              │  mediator.sock      │                  │
│ ┌──────────┐ │                     │ ┌──────────────┐ │
│ │ Worker 1 │ │                     │ │ Anchor Guard │ │
│ │ Worker 2 │ │    JSON payloads    │ │ Atomic Write │ │
│ │ Worker N │ │────────────────────►│ │ Claim Engine │ │
│ └──────────┘ │                     │ │ Glow Scoring │ │
└─────────────┘                     │ └──────────────┘ │
                                    └──────────────────┘
```

1. **`jack_cli.py`** boots the mediator daemon, seeds the idea pool, and spawns N async workers.
2. Each **worker** calls the Gemini API independently, generating structured JSON proposals with explicit claims.
3. Workers submit results to the **mediator daemon** over a Unix Domain Socket.
4. The daemon validates payloads, runs claim deduplication and glow scoring, enforces anchor constraints, and persists state via POSIX atomic writes (`tmp → fsync → rename`).
5. After all workers complete, the CLI compiles residues (failed/orphaned tasks), writes a consensus dump, and suspends the daemon.

---

## CLI Reference

### Core Options

| Flag | Required | Default | Description |
|:---|:---|:---|:---|
| `--layer` | Yes* | — | Layer index (e.g. `1.1`, `2.3.1`). Namespaces all state files so parallel task trees never collide. |
| `--prompt` | Yes* | — | The seed prompt fed to every worker in the swarm. |
| `--workers` | No | `20` | Number of async workers to spawn. Actual API concurrency is capped at 5 via internal semaphore. |
| `--mode` | No | `swarm` | `swarm` (full multi-agent) or `native` (single-pass, no daemon). |
| `--dump-file` | No | Auto | Override path for the consensus dump JSON. Auto-generated from `--layer` if omitted. |

*\*Required unless using `--setup`, `--cleanup`, or `--dump-constitution`.*

### Utility Flags

| Flag | Description |
|:---|:---|
| `--setup` | **First-time setup wizard.** Prompts for your Gemini API key and saves it to a gitignored `.env` file. |
| `--cleanup` | **Nuclear teardown failsafe.** Kills all daemon and CLI processes, removes the UDS socket file, and purges ALL layer state files (`idea_pool`, `residue_ledger`, `consensus_dump`) plus legacy artifacts. **Run this before any fresh execution** to guarantee zero state contamination from prior runs. |
| `--dump-constitution` | Prints the full embedded protocol constitution to stdout. Useful for inspecting what system instructions the workers receive. |

### Examples

```bash
# First-time setup
python3 jack_cli.py --setup

# Run a single-worker research sweep
python3 jack_cli.py --layer "1.1" --workers 1 \
  --prompt "Analyze the phase diagram of a 2D topological surface code under MIPT."

# Run a full 20-worker adversarial swarm
python3 jack_cli.py --layer "1.1" --workers 20 \
  --prompt "Design a zero-knowledge proof system for federated learning."

# Clean up ALL state before a fresh run
python3 jack_cli.py --cleanup

# Native mode — single-pass, no daemon overhead
python3 jack_cli.py --layer "2.1" --mode native \
  --prompt "Scaffold a basic REST API for the consensus ledger."
```

### Environment Variables

| Variable | Default | Description |
|:---|:---|:---|
| `GEMINI_API_KEY` | — | Your Gemini AI Studio API key. Can also be set via `--setup`. |
| `JACK_SWARM_MODEL` | `gemini-2.5-flash-lite` | Override the default model for all workers. |
| `JACK_WORKSPACE` | Repo root | Override the workspace root directory for the mediator daemon. |

---

## Socket Payload Schema

Workers communicate with the mediator daemon over a Unix Domain Socket at `/tmp/swarm-mediator.sock`. If you want to build a custom client in any language, here's the contract:

### Transport Rules

1. Connect to `socket.AF_UNIX` at `/tmp/swarm-mediator.sock`.
2. Send your JSON payload as UTF-8 bytes via `sendall()`.
3. **Call `socket.SHUT_WR` immediately after sending.** The daemon reads until EOF — without the half-close, the receive loop blocks indefinitely.
4. Read the response bytes until the connection closes.

### Payload Keys

```json
{
  "action": "meme",
  "meme_type": "PROPOSAL",
  "requester": "worker_01",
  "layer_index": "1.1",
  "branch_id": "branch_worker_01_seed_01",
  "content": "Full text of the proposal.",
  "claims": ["Claim 1 text", "Claim 2 text"],
  "target_branch_id": null
}
```

| Key | Type | Required | Description |
|:---|:---|:---|:---|
| `action` | string | Yes | `meme`, `read`, `write`, `status`, `shutdown`, `suspend`, `wakeup`, `load_queue`, `pop_idea`, `record_residue`, or `fact_inject`. |
| `meme_type` | string | For `meme` | `PROPOSAL`, `CHALLENGE`, or `SYNTHESIS`. |
| `requester` | string | Yes | Worker identifier for audit trail. |
| `layer_index` | string | For `meme` | Which layer this submission belongs to. |
| `content` | string | For `meme`/`write` | The generated content payload. |
| `claims` | list[str] | For `meme` | Discrete atomic claims extracted from the content. |
| `target_branch_id` | string | No | Only for challenges — targets a specific branch. |

### Response Format

```json
{
  "status": "ACK",
  "timestamp": "2026-05-21T00:00:00+00:00",
  "reason": "Tweet ingested into GENESIS phase",
  "signals": ["REQUEST_GROUND:abc123"],
  "current_phase": "GENESIS",
  "round_number": 1
}
```

Status is `ACK`, `NACK`, or `EMPTY`. Malformed payloads get a descriptive `NACK` explaining exactly what's wrong.

---

## Project Structure

```
jack_cli/
├── jack_cli.py                  # CLI conductor — boots daemon, spawns workers
├── requirements.txt             # Python dependencies
├── Core/
│   ├── data_manager.py          # UDS mediator daemon (all I/O flows here)
│   ├── social_state_machine.py  # Adversarial lifecycle + claim registry
│   ├── epoch_coordinator.py     # Epoch barrier synchronization
│   ├── halting.py               # Worker halting controller
│   ├── differentiation.py       # Epoch strategy director + loop clock
│   ├── attention_variants.py    # Decoupled position tagger
│   └── act_accumulator.py       # Claim accumulation utilities
├── tests/
│   ├── test_chunk2_differentiation.py
│   ├── test_chunk3_orchestration.py
│   ├── test_chunk4_attention_goblin.py
│   └── test_lti_stabilization.py
├── .env                         # Your API key (gitignored, created by --setup)
└── .gitignore
```

---

## License

MIT
