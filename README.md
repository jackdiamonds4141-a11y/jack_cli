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

## How to Use (The Intended Workflow)

Jack Engine is a brainstorming and complex reasoning tool. It is designed to be operated **by your IDE agent** (Antigravity, Cursor, Windsurf, etc.), not by hand.

The ideal workflow has **three phases**:

### Phase 1: Give your agent the kickoff prompt

Drop this into your IDE agent chat at the start of a new project:

> *"I have a CLI tool at `jack_cli.py` that is set up for brainstorming and complex reasoning. First, run its help command (`python3 jack_cli.py --help`) to read the internal operator manual. Once you fully understand how the tool works — what it does, how layering works, how often to call the swarm, and the critical directives — we will use it to solve our problem. Do not attempt to read or modify the tool's source code. Just execute it as documented."*

The agent will run `--help`, read the full manual baked into the epilog, and from that point on it knows exactly how to invoke the swarm with proper layering, when to call `--cleanup`, and how to consume the consensus dumps.

### Phase 2: The agent creates a plan and highlights brainstorming candidates

After the agent understands the tool, give it your actual task:

> *"Build me a distributed rate-limiter for a multi-region API gateway."*

The agent should then create an **implementation plan** and **identify which sub-tasks need adversarial brainstorming** vs. which ones it can handle natively. For example:

| Sub-task | Needs Brainstorming? |
|:---|:---|
| Set up the project directory structure | ❌ No — trivial scaffolding |
| Design the token bucket algorithm for distributed nodes | ✅ Yes — needs multi-perspective adversarial debate |
| Write the HTTP middleware integration | ❌ No — standard code generation |
| Design the consensus protocol for cross-region sync | ✅ Yes — complex architecture decision |
| Write unit tests | ❌ No — deterministic |

The agent presents this table to **you**, the human, and asks:

> *"I've identified 2 sub-tasks that would benefit from a brainstorming session. Should I send both to the swarm, or would you like to add/remove any from the list?"*

### Phase 3: You confirm, the agent runs the swarm

Once you approve (or modify) the brainstorming list, the agent:
1. Runs `--cleanup` to clear any stale state.
2. Fires the swarm for each approved task with the right `--layer` and `--prompt`.
3. Reads the consensus dump and uses the swarm's output as grounding context for the rest of the implementation.

---

## Example Prompts

Here are real examples of tasks that benefit from the swarm:

### Architecture & System Design
```bash
python3 jack_cli.py --cleanup
python3 jack_cli.py --layer "1.1" --workers 20 \
  --prompt "Design a zero-knowledge proof system for federated learning that preserves differential privacy guarantees while allowing model aggregation across untrusted nodes."
```

### Security & Cryptography
```bash
python3 jack_cli.py --layer "2.1" --workers 20 \
  --prompt "Design a post-quantum key exchange protocol for IoT devices with <2KB RAM. Must resist both Grover and Shor attacks while completing handshake in under 50ms."
```

### OSINT & Investigation
```bash
python3 jack_cli.py --layer "3.1" --workers 20 \
  --prompt "Develop an OSINT methodology to identify the true beneficial owners of shell companies registered in Delaware, using only publicly available data sources."
```

### Hard Science & Physics
```bash
python3 jack_cli.py --layer "4.1" --workers 1 \
  --prompt "Derive the critical measurement probability for MIPT in a 2D toric code."
```

> **Tip:** Use `--workers 1` for single-perspective deep research, and `--workers 20` for multi-agent adversarial debate on problems where you need conflicting viewpoints to converge.

---

## Manual Usage (CLI Quick Reference)

If you want to run the tool yourself instead of through an IDE agent:

```bash
# Clean state from any prior run (always do this first)
python3 jack_cli.py --cleanup

# Fire a full 20-worker adversarial swarm
python3 jack_cli.py --layer "1.1" --workers 20 \
  --prompt "Your problem statement here."

# Check results — the consensus dump contains all worker outputs
cat sessions/<session-id>/consensus_dump_layer_1.1.json
```

### CLI Flags

| Flag | What it does |
|:---|:---|
| `--setup` | First-time setup. Asks for your Gemini key and saves it locally. |
| `--cleanup` | **Run this first.** Kills stale daemons, wipes sockets, purges cached state. |
| `--layer "X.Y"` | Namespaces your task. Use a new layer for each problem. Sequential layers auto-inherit context. |
| `--prompt "..."` | The problem statement fed to every worker in the swarm. |
| `--workers N` | How many workers to spawn (default 20, concurrency capped at 5). |
| `--mode native` | Single-pass mode, no daemon. For simple tasks that don't need multi-agent debate. |
| `--steer "..."` | Inject a mid-flight constraint or challenge into the active swarm. |
| `--resume` | Skip layers that already have a cached consensus dump. |
| `--dump-constitution` | Prints the embedded research + agentic protocols to stdout. |

### Environment Variables

| Variable | Default | What it does |
|:---|:---|:---|
| `GEMINI_API_KEY` | — | Your API key. Set via `--setup` or `export` directly. |
| `API_KEY_FALLBACK_1` | — | Optional second API key for hot-standby rotation on 429 errors. |
| `API_KEY_FALLBACK_2` | — | Optional third API key for hot-standby rotation on 429 errors. |
| `JACK_WORKER_MODEL` | `gemma-4-26b-a4b-it` | Override the model all workers use. |
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
- **API Key Rotation Pool** uses hot-standby failover across up to 3 keys. On a 429, the system instantly rotates to the next available key with zero sleep delay.
- **MapReduce Context Splitting** automatically splits dense synthesis prompts exceeding 80,000 characters into concurrent sub-worker tasks, then merges results using whichever key is free.
- **OSINT Triangulation Pipeline** features a persistent SQLite-backed SearxNG cache, enabling zero-latency concurrent documentation lookups without API rate-limit bottlenecks.
- **Mediator Daemon** (`data_manager.py`) serializes everything through a single Unix Domain Socket. Validates payloads, deduplicates claims, computes glow scores, enforces anchor constraints, and persists state via POSIX atomic writes (`tmp → fsync → rename`).
- **Social State Machine** runs adversarial lifecycle phases: `GENESIS → OPEN_CHALLENGE → SYNTHESIS_PENDING → IDE_REVIEW → PROMOTED`.
- **Embedded Constitution** — research protocols, source verification frameworks, and agentic coordination rules are baked directly into the worker system instructions. No external config files needed.

---

## Project Structure

```
jack_cli/
├── jack_cli.py                  # CLI conductor — the only file you execute
├── jack_agent_manual.md         # Full agent operator manual (for IDE agents)
├── requirements.txt             # Python dependencies
├── recon_router.py              # Layer 0 epistemic query router (O(1) lookup)
├── compressor.py                # Knowledge chunk compression pipeline
├── database_builder.py          # Wiki database builder & indexer
├── knowledge_compiler.py        # Raw document ingestion pipeline
├── inject_verdict.py            # Agent-led audit verdict injector
├── Core/
│   ├── data_manager.py          # UDS mediator daemon
│   ├── social_state_machine.py  # Adversarial lifecycle + claim registry + glow engine
│   ├── epoch_coordinator.py     # Epoch barrier synchronization
│   ├── halting.py               # Worker halting controller
│   ├── differentiation.py       # Epoch strategy director
│   ├── attention_variants.py    # Position tagger for prompt assembly
│   ├── parser.py                # XML-tag output parser
│   └── act_accumulator.py       # Claim accumulation
├── wiki/                        # Compiled knowledge database (auto-generated)
│   ├── index.json               # Master O(1) routing table
│   ├── intel/                   # Intelligence analysis heuristics
│   ├── law/                     # Forensic/legal heuristics
│   ├── science/                 # Scientific review heuristics
│   └── journalism/              # Verification heuristics
├── tests/                       # Unit tests
├── .env                         # Your API keys (gitignored, created by --setup)
└── .gitignore
```

---

## FAQ

**Q: When should I use this vs. just asking my AI agent directly?**
A: Use Jack Engine when a single model completion would risk hallucination or tunnel vision. Architecture decisions, security protocol design, novel algorithms, OSINT methodologies, hard physics — anything where you need multiple independent perspectives to converge on a rigorous answer.

**Q: How long does a swarm run take?**
A: Typically 2–5 minutes for a full 20-worker adversarial swarm on the free Gemini tier. Single-worker research sweeps (`--workers 1`) complete in under 30 seconds.

**Q: Can I use multiple API keys to avoid rate limits?**
A: Yes. Add `API_KEY_FALLBACK_1` and `API_KEY_FALLBACK_2` to your `.env` file. The engine will automatically rotate between all available keys when it hits a 429, with zero-sleep failover.

**Q: What model does it use?**
A: By default, it uses `gemma-4-26b-a4b-it` (a free Gemini model). You can override this with the `JACK_WORKER_MODEL` environment variable.

---

## License

MIT
