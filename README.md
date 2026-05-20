# Jack Engine CLI

**Supercharge your vibe coding.** Jack Engine orchestrates local AI agent swarms under strict runtime constraint gates — adversarial multi-agent debate, claim-level verification, and POSIX-atomic state persistence — to produce research and engineering outputs that consistently beat multi-billion dollar flagship models. For free.

Instead of trusting a single LLM completion, Jack spawns a configurable swarm of workers that independently generate proposals, challenge each other's claims, and synthesize consensus through a formalized adversarial protocol. A central mediator daemon serializes all state through Unix Domain Sockets, enforces immutable anchor constraints, and persists everything via atomic writes. The result: hallucination-resistant, citation-grade output.

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/jackdiamonds4141-a11y/jack_cli.git
cd jack_cli
```

### 2. Install Dependencies

Jack Engine requires Python 3.10+ and the following packages:

```bash
pip install google-genai pydantic pyyaml requests trafilatura
```

### 3. Set Your API Key

Jack Engine uses Google's Gemini API. You need a free API key from [Google AI Studio](https://aistudio.google.com/apikey).

**Option A — Environment variable** (recommended for CI/scripts):

```bash
export GEMINI_API_KEY="your-api-key-here"
```

**Option B — Local `.env` file** (recommended for development):

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your-api-key-here
```

> The `.env` file is gitignored by default and will never be committed.

The engine checks `os.environ` first, then falls back to `.env`.

You can also override the default model by setting:

```bash
export JACK_SWARM_MODEL="gemini-2.5-flash"  # default: gemini-2.5-flash-lite
```

### 4. Run

```bash
python jack_cli.py --layer "1.1" --workers 1 --prompt "Your research question here"
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
| `--layer` | Yes* | — | Layer index (e.g., `1.1`, `1.1.2`). Namespaces all state files so parallel task trees don't collide. |
| `--prompt` | Yes* | — | The seed prompt fed to every worker in the swarm. |
| `--workers` | No | `20` | Number of concurrent workers to spawn. Actual concurrency is capped at 5 via semaphore. |
| `--mode` | No | `swarm` | `swarm` (multi-agent) or `native` (single-pass, no daemon). |
| `--dump-file` | No | Auto | Override path for the consensus dump JSON. Auto-generated from `--layer` if omitted. |

*\*Required unless using `--cleanup` or `--dump-constitution`.*

### Utility Options

| Flag | Description |
|:---|:---|
| `--cleanup` | **Nuclear teardown.** Kills all daemon/CLI processes, removes the UDS socket, purges ALL layer state files (`idea_pool`, `residue_ledger`, `consensus_dump`), and clears legacy artifacts. Run this before any fresh execution to guarantee zero state contamination. |
| `--dump-constitution` | Prints the full embedded protocol constitution (meta-research, research, and agentic protocol rules) to stdout. Useful for inspecting what system instructions the workers receive. |

### Examples

```bash
# Run a single-worker quantum physics analysis
python jack_cli.py --layer "1.1" --workers 1 \
  --prompt "Derive the critical measurement probability for MIPT in a 2D toric code."

# Clean up all state before a fresh run
python jack_cli.py --cleanup

# Inspect the embedded protocols
python jack_cli.py --dump-constitution

# Native mode (bypass daemon, single-pass)
python jack_cli.py --layer "2.1" --mode native \
  --prompt "Scaffold a basic REST API for the consensus ledger."
```

---

## Socket Payload Schema

Workers communicate with the mediator daemon over a Unix Domain Socket at `/tmp/swarm-mediator.sock`. If you want to build your own custom client (in any language), here's the contract:

### Transport Rules

1. Connect to `socket.AF_UNIX` at `/tmp/swarm-mediator.sock`.
2. Send your JSON payload as UTF-8 bytes via `sendall()`.
3. **You MUST call `socket.SHUT_WR` immediately after sending.** The daemon's receive loop reads until EOF — without the half-close, it will block indefinitely.
4. Read the response bytes until the connection closes.

### Payload Keys

```json
{
  "action": "meme",
  "meme_type": "PROPOSAL",
  "requester": "worker_01",
  "layer_index": "1.1",
  "branch_id": "branch_worker_01_seed_01",
  "content": "Full text of the proposal, challenge, or synthesis.",
  "claims": ["Claim 1 text", "Claim 2 text"],
  "target_branch_id": null
}
```

| Key | Type | Required | Description |
|:---|:---|:---|:---|
| `action` | string | Yes | One of: `meme`, `read`, `write`, `status`, `shutdown`, `suspend`, `wakeup`, `load_queue`, `pop_idea`, `record_residue`, `fact_inject`. |
| `meme_type` | string | For `meme` | `PROPOSAL`, `CHALLENGE`, or `SYNTHESIS`. |
| `requester` | string | Yes | Worker identifier for audit trail. |
| `layer_index` | string | For `meme` | Which layer this submission belongs to. |
| `content` | string | For `meme`/`write` | The actual generated content. |
| `claims` | list[str] | For `meme` | Discrete atomic claims extracted from the content. |
| `target_branch_id` | string | No | Only used for challenges — the branch being targeted. |

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

Status will be `ACK`, `NACK`, or `EMPTY`. If the payload is malformed or missing required fields, the daemon returns a descriptive `NACK` explaining exactly what's wrong.

---

## Project Structure

```
jack_cli_production/
├── jack_cli.py                  # CLI conductor — boots daemon, spawns swarm
├── Core/
│   ├── data_manager.py          # UDS mediator daemon — all I/O flows through here
│   ├── social_state_machine.py  # Adversarial synthesis lifecycle + claim registry
│   ├── epoch_coordinator.py     # Epoch barrier synchronization
│   ├── halting.py               # Worker halting controller
│   ├── differentiation.py       # Epoch strategy director + loop clock
│   ├── attention_variants.py    # Decoupled position tagger for prompt assembly
│   └── act_accumulator.py       # Claim accumulation utilities
├── tests/
│   ├── test_chunk2_differentiation.py
│   ├── test_chunk3_orchestration.py
│   ├── test_chunk4_attention_goblin.py
│   └── test_lti_stabilization.py
├── .env                         # Your API key (gitignored)
├── .gitignore
└── README.md
```

---

## License

MIT
