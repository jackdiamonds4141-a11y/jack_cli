# Jack Engine

### Turn cheap AI models into an elite reasoning squad.

I got tired of watching $200/month flagship models hallucinate on hard problems. So I built a CLI that takes the cheapest Gemini model available, spawns a swarm of independent workers, makes them argue with each other through a formalized adversarial protocol, and produces outputs that consistently outperform single-shot completions from models 100x the cost.

No fine-tuning. No RAG pipeline. No vector database. Just structured multi-agent debate with strict runtime constraint gates, claim-level deduplication, and POSIX-atomic state persistence over Unix sockets.

The entire thing runs locally on your machine for free.

---

> ⚠️ **Note:** As of now, this framework has only been tested with the **Antigravity IDE**. Universal compatibility with other agentic IDEs is unknown. If you get it working in Cursor, Windsurf, or anything else — let me know.

---

## Getting Started

You need **Python 3.10+** and a free Gemini API key.

### 1. Clone it

```bash
git clone https://github.com/jackdiamonds4141-a11y/jack_cli.git
cd jack_cli
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up your API key

```bash
python3 jack_cli.py --setup
```

That's it. The setup wizard will ask you to paste your key (grab one for free from [Google AI Studio](https://aistudio.google.com/apikey)) and save it locally. The key never touches Git.

This tool is built for the **Gemini AI Studio API**. Any strictly compatible endpoint will work — we just don't support custom calling schemas yet.

---

## How to Use

Jack Engine is designed to be operated by your IDE agent, not by hand. You give your agent a kickoff prompt, it reads the built-in manual, and then it knows how to call the CLI autonomously whenever it hits a hard problem.

### The Copy-Paste Kickoff Prompt

Drop this into your IDE agent chat to get started:

> *"I have a CLI tool at `jack_cli.py` that is set up for brainstorming and complex reasoning. First, run its help command (`python3 jack_cli.py --help`) to read the internal operator manual. Once you fully understand how the tool works — what it does, how layering works, how often to call the swarm, and the critical directives — we will use it to solve our problem. Do not attempt to read or modify the tool's source code. Just execute it as documented."*

The agent will run `--help`, read the full manual baked into the epilog, and from that point on it knows exactly how to invoke the swarm with proper layering, when to call `--cleanup`, and how to consume the consensus dumps.

### Manual Usage (if you want to run it yourself)

```bash
# Clean state from any prior run
python3 jack_cli.py --cleanup

# Fire a single-worker research sweep
python3 jack_cli.py --layer "1.1" --workers 1 \
  --prompt "Derive the critical measurement probability for MIPT in a 2D toric code."

# Fire a full 20-worker adversarial swarm
python3 jack_cli.py --layer "1.1" --workers 20 \
  --prompt "Design a zero-knowledge proof system for federated learning."
```

---

## CLI Quick Reference

| Flag | What it does |
|:---|:---|
| `--setup` | First-time setup. Asks for your Gemini key and saves it locally. |
| `--cleanup` | **Run this first.** Kills stale daemons, wipes sockets, purges all cached state files. |
| `--layer "X.Y"` | Namespaces your task. Use a new layer for each problem. Sequential layers auto-inherit context. |
| `--prompt "..."` | The problem statement fed to every worker in the swarm. |
| `--workers N` | How many workers to spawn (default 20, concurrency capped at 5). |
| `--mode native` | Single-pass mode, no daemon. For simple tasks that don't need multi-agent debate. |
| `--dump-constitution` | Prints the embedded research + agentic protocols to stdout. |

### Environment Variables

| Variable | Default | What it does |
|:---|:---|:---|
| `GEMINI_API_KEY` | — | Your API key. Set via `--setup` or `export` directly. |
| `JACK_SWARM_MODEL` | `gemini-2.5-flash-lite` | Override the model all workers use. |
| `JACK_WORKSPACE` | Repo root | Override the workspace root for the mediator daemon. |

---

## What's Under the Hood

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

- **Conductor** (`jack_cli.py`) boots the mediator daemon, seeds the task pool, spawns N async workers, and collects results.
- **Workers** independently call the Gemini API, generating proposals wrapped in robust XML tags to bypass small-model JSON serialization errors, complete with explicit atomic claims.
- **OSINT Triangulation Pipeline** features a persistent SQLite-backed SearxNG cache, enabling zero-latency concurrent documentation lookups without API rate-limit bottlenecks.
- **Mediator Daemon** (`data_manager.py`) serializes everything through a single Unix Domain Socket. Validates payloads, deduplicates claims, computes glow scores, enforces anchor constraints, and persists state via POSIX atomic writes (`tmp → fsync → rename`).
- **Social State Machine** runs adversarial lifecycle phases: `GENESIS → OPEN_CHALLENGE → SYNTHESIS_PENDING → IDE_REVIEW → PROMOTED`.
- **Embedded Constitution** — research protocols, source verification frameworks, and agentic coordination rules are baked directly into the worker system instructions. No external config files needed.

---

## Project Structure

```
jack_cli/
├── jack_cli.py                  # CLI conductor — the only file you execute
├── requirements.txt             # Python dependencies
├── Core/
│   ├── data_manager.py          # UDS mediator daemon
│   ├── social_state_machine.py  # Adversarial lifecycle + claim registry + glow engine
│   ├── epoch_coordinator.py     # Epoch barrier synchronization
│   ├── halting.py               # Worker halting controller
│   ├── differentiation.py       # Epoch strategy director
│   ├── attention_variants.py    # Position tagger for prompt assembly
│   └── act_accumulator.py       # Claim accumulation
├── tests/                       # Unit tests
├── .env                         # Your API key (gitignored, created by --setup)
└── .gitignore
```

---

## License

MIT
