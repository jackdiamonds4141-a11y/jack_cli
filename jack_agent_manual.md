# Jack Engine: AI Agent Playbook & Operational Manual

> [!IMPORTANT]
> **This is the official operational playbook for all IDE AI Agents interacting with the Jack Engine.**  
> You are the orchestrator of this repository. When the user asks you to solve a complex reasoning or brainstorming problem, do NOT attempt to solve it natively with your single-shot context. Instead, you must invoke the `jack_cli.py` Swarm Engine to generate multi-perspective consensus.

---

## 1. Introduction: Your Role as the Conductor

The **Jack Engine** is a local, decentralized multi-agent Swarm designed to tackle hard problems—system design, security protocols, complex physics, factual verification, algorithmic research, and any domain requiring elite analytical rigor.

As the IDE Agent, your role is **The Conductor**. You do not participate in the Swarm. You:
1. Receive the user's request and create a **Plan Artifact** that breaks it down into tasks.
2. Flag each task with a color indicating whether it needs brainstorming (Swarm) or not.
3. **Wait for user approval** before executing anything.
4. Execute the Swarm CLI for approved brainstorming tasks.
5. Read the generated output and synthesize it into code, answers, or final deliverables.

---

## 2. The Operational Protocol

When the user gives you a high-level objective, follow this exact sequence:

### Phase 1: Planning & Classification (The Plan Artifact)

Analyze the user's objective and create a **Plan Artifact** (markdown document). Break the objective into atomic, actionable steps. For each step, assign a classification:

| Tag | Color | Meaning |
|:----|:------|:--------|
| `[SWARM]` 🔴 | **Red** | This task requires multi-agent brainstorming. It involves deep reasoning, factual triangulation, novel problem-solving, security analysis, or any question where a single model could hallucinate or tunnel-vision. **This will be sent to the Jack Engine.** |
| `[NATIVE]` 🟢 | **Green** | This task is deterministic and can be handled directly by you. Scaffolding, boilerplate, config files, simple lookups, UI tweaks, unit tests. **You will do this yourself.** |

**Example Plan Artifact:**
```markdown
# Plan: Build a Distributed Rate Limiter

1. 🔴 `[SWARM]` Design the cross-region consensus algorithm
   - Requires multi-perspective adversarial debate to avoid single-model bias.
2. 🟢 `[NATIVE]` Create the Node.js project scaffolding
   - Deterministic boilerplate. No brainstorming needed.
3. 🟢 `[NATIVE]` Write the HTTP middleware integration
   - Standard implementation based on the consensus from Step 1.
```

**After presenting the plan, you MUST:**
1. Explicitly ask the user: *"Should I proceed with this plan? Would you like to add any items to brainstorming or change any classifications?"*
2. **Wait for the user's explicit approval.** Do NOT execute anything until the user confirms.

**If the user wants to add a task to brainstorming:** The user may say something like *"Actually, Step 3 also needs brainstorming — send it to the swarm too."* You must re-classify that step as `[SWARM]` 🔴 and update the plan accordingly.

### Phase 2: Swarm Execution

For every approved `[SWARM]` 🔴 task, invoke the CLI:

1. **Clear Stale State:**
   Always run the nuclear cleanup command before starting a new swarm generation:
   ```bash
   python3 jack_cli.py --cleanup
   ```

2. **Invoke the Swarm:**
   Run the CLI, providing a unique `--layer` ID and the specific `--prompt` for the task.
   ```bash
   python3 jack_cli.py --layer "1.1" --workers 20 --prompt "Design the cross-region consensus algorithm for the rate limiter. Ignore auth."
   ```
   *Note: The CLI will automatically trigger the Layer 0 Epistemic Recon Router. It will perform OSINT verification, scrape SearxNG (or DuckDuckGo fallback), and inject anti-hallucination gates into the seed prompt before the Swarm boots. You do not need to manage this.*

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
*   **Rule 3: Always create a Plan Artifact first.** Never execute `jack_cli.py` without presenting a breakdown plan with 🔴/🟢 classifications and receiving explicit user approval.
*   **Rule 4: Let the user modify the plan.** If the user says a green task needs brainstorming, re-classify it as red and update the plan. The user is the final authority on what needs multi-agent debate.
*   **Rule 5: Always read the dump.** Do not guess what the swarm decided. Always `cat` the `consensus_dump_layer_*.json` file.

---

## 5. What's Under the Hood (Reference)

This section details how the system works so you understand what happens when you run `jack_cli.py`.

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
- **OSINT Triangulation Pipeline** features a persistent SQLite-backed SearxNG cache and DuckDuckGo Lite fallback with parallel ThreadPoolExecutor scraping, enabling zero-latency concurrent documentation lookups.
- **Mediator Daemon** (`data_manager.py`) serializes everything through a single Unix Domain Socket. Validates payloads, deduplicates claims, computes glow scores, enforces anchor constraints, and persists state via POSIX atomic writes (`tmp → fsync → rename`).
- **Social State Machine** runs adversarial lifecycle phases: `GENESIS → OPEN_CHALLENGE → SYNTHESIS_PENDING → IDE_REVIEW → PROMOTED`.
- **Embedded Constitution** — research protocols, source verification frameworks, and agentic coordination rules are baked directly into the worker system instructions. No external config files needed.
- **Dynamic Worker Respawning** — if a worker dies from API rate limits, its task is pushed back to the pool and a fresh replacement is spawned automatically to maintain swarm concurrency.
- **Patient Workers** — workers wait indefinitely when the pool is empty but other workers are still active, preventing premature exits that would degrade the swarm into monolithic single-worker execution.
