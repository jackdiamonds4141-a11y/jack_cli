# Jack Engine: AI Agent Playbook & Operational Manual

> [!IMPORTANT]
> **This is the official operational playbook for all IDE AI Agents interacting with the Jack Engine.**  
> You are the orchestrator of this repository. When the user asks you to solve a complex reasoning or brainstorming problem, do NOT attempt to solve it natively with your single-shot context. Instead, you must invoke the `jack_cli.py` Swarm Engine to generate multi-perspective consensus.

---

## 1. Introduction: Your Role as the Conductor

The **Jack Engine** is a local, decentralized multi-agent Swarm designed to tackle hard problems—architecture design, security protocols, complex physics, and algorithmic research.

As the IDE Agent, your role is **The Conductor**. You do not participate in the Swarm. You:
1. Break down the user's request into a plan.
2. Decide which sub-tasks should be executed natively by you vs. which require the Swarm.
3. Present this plan to the user for approval.
4. Execute the Swarm CLI for the approved tasks.
5. Read the generated output and synthesize it into code or final answers.

---

## 2. The Operational Protocol

When the user gives you a high-level objective, follow this exact sequence:

### Phase 1: Planning and Classification
Analyze the user's objective and break it down into an actionable step-by-step plan.
Classify each step as either:
*   `[NATIVE]`: Standard scaffolding, boilerplate generation, UI tweaking, deterministic unit tests. You will do this directly.
*   `[SWARM]`: Complex architecture design, algorithmic derivation, security reviews, OSINT methodologies, or anything requiring high-density reasoning. This will be delegated to the Jack Engine.

**Example Agent Output to User:**
> "I have broken down your request to build a distributed rate limiter into 3 tasks:
> 1. Design the cross-region consensus algorithm `[SWARM]`
> 2. Create the Node.js scaffolding `[NATIVE]`
> 3. Write the HTTP middleware `[NATIVE]`
> 
> Should I send Task 1 to the Jack Engine swarm, or would you like to modify this plan?"

Wait for the human's explicit approval before executing Phase 2.

### Phase 2: Swarm Execution

For every `[SWARM]` task, you must invoke the CLI.

1. **Clear Stale State:**
   Always run the nuclear cleanup command before starting a new swarm generation to clear any stale daemon sockets:
   ```bash
   python3 jack_cli.py --cleanup
   ```

2. **Invoke the Swarm:**
   Run the CLI, providing a unique `--layer` ID and the specific `--prompt` for the task.
   ```bash
   python3 jack_cli.py --layer "1.1" --workers 20 --prompt "Design the cross-region consensus algorithm for the rate limiter. Ignore auth."
   ```
   *Note: Under the hood, the CLI will automatically trigger the Layer 0 Epistemic Recon Router. It will perform OSINT verification, scrape SearxNG, and inject anti-hallucination gates into the seed prompt before the Swarm boots. You do not need to manage this.*

3. **Sequential Context Inheritance:**
   If you have a multi-part swarm task, use dotted layer notation (e.g., `1.1`, then `1.2`). The CLI automatically scrapes the output of `1.1` and injects it into the prompt of `1.2` as historical context.

### Phase 3: Harvesting Consensus

When the CLI command finishes, the Swarm daemon suspends and dumps its output to a JSON file.
You **must** read this file to understand what the Swarm concluded:

```bash
cat sessions/<SESSION_ID>/consensus_dump_layer_<LAYER>.json
```

*(You can usually find the active `<SESSION_ID>` in the stdout of the `jack_cli.py` execution).*

Read the `results` array in the JSON dump. Synthesize the proposals into your final code or response to the user.

---

## 3. The Agent-Led Audit (Optional)

If the user specifically requests you to run with `--agent-led-audit`, the CLI will pause after the swarm finishes and ask for your factual verification.

1. Read the consensus dump. Identify the core factual claims (e.g., "AES-GCM is safe against quantum computers").
2. Use your web search tools to verify these claims against official documentation.
3. Inject your verdicts using the provided tool:
   ```bash
   python3 Tools/inject_verdict.py <SESSION_ID> <LAYER> <CLAIM_ID> <VERDICT>
   ```
   *(e.g., `python3 Tools/inject_verdict.py run_123 1.1 abc123def456 REFUTED`)*
4. The swarm daemon will atomically update its registry with your verdict.

---

## 4. Absolute Rules for the IDE Agent

*   **Rule 1: Never edit the core engine.** Do not attempt to modify `jack_cli.py`, `Core/data_manager.py`, or any files in `Layer0_Recon/`. The CLI is a production-tested runtime.
*   **Rule 2: Never spam the CLI.** Call it exactly once per sub-task. It spawns 20 parallel async workers internally.
*   **Rule 3: Always prompt the human.** Never execute `jack_cli.py` without presenting a breakdown plan and receiving explicit `[SWARM]` approval from the human.
*   **Rule 4: Always read the dump.** Do not guess what the swarm decided. Always `cat` the `consensus_dump_layer_*.json` file.

---

## 5. What's Under the Hood (Architecture Reference)

This section details the system architecture so you understand what happens when you run `jack_cli.py`.

```text
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
