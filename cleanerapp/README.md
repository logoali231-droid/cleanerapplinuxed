# AI File Cleaner

A Linux file cleaner with a tabular Q-learning agent that learns per-user
keep/delete preferences. Detects unused installers, orphaned Minecraft mods,
virtual-machine leftovers, and stale screenshots. Moves files to Trash, never
permanently deletes. Runs entirely offline.

**Language:** Python 3.8+
**GUI:** PyQt5
**Learning:** Tabular Q-learning (no external ML dependencies)
**Platform:** Linux (tested on Linux Mint 21/22, Ubuntu 22.04+)

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
  - [Scan Pipeline](#scan-pipeline)
  - [Decision Engine](#decision-engine)
  - [Protection Layers](#protection-layers)
  - [Learning System](#learning-system)
- [Module Breakdown](#module-breakdown)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Testing](#testing)
- [Design Decisions](#design-decisions)
- [Extending the System](#extending-the-system)
- [License](#license)

---

## Features

- **Tabular Q-learning agent** with dynamic per-context confidence thresholds
- **Rule system** — user-defined protections and flags that override the AI
- **Trash-safe deletion** — every file moves to Trash; one-click restore
- **Structural orphan detection** for Minecraft mods and VM images
- **Content sniffing** — never flags scripts, executables, documents, or secrets
- **dpkg ownership check** — never touches files owned by installed packages
- **Screenshot detection** with configurable age threshold
- **Decision log** — every user decision is recorded for calibration analysis
- **No network access** — the agent learns locally and never phones home

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Wizard (PyQt5)                         │
│  Welcome → Choose Folder → Scan → Review → Clean Up → Done      │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ScannerThread (QThread)                     │
│                                                                 │
│  os.walk() ──► Rule Check ──► Structural Checks ──► AI Check   │
│       │              │                │                  │      │
│       │              ▼                ▼                  ▼      │
│       │        RulesManager      minecraft.py      QLearningAgent
│       │                          virtualmachines   (agent.py)
│       │                          protection.py           │      │
│       │                                                  │      │
│       ▼                                                  ▼      │
│  results list ──────────────────────────────────► signal:      │
│                                                    files_found  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Review & Action Layer                      │
│                                                                 │
│  Group by (name, size, age) → User unchecks → Confirm → Trash   │
│                                                                 │
│  agent.record_decision()  ← per-file calibration data          │
│  agent.reinforce_from_user() ← Q-table update from batch        │
└─────────────────────────────────────────────────────────────────┘
```

---

## How It Works

### Scan Pipeline

The scanner walks the target directory tree using `os.walk()` with directory
pruning. Each file passes through a decision pipeline in strict order. The
first check that matches determines the outcome.

```
For each file:
  1. Orphan Minecraft mod?          → FLAG (confidence = 999)
  2. VM leftover?                   → FLAG (confidence = 999)
  3. User rule = "protect"?         → SKIP
  4. User rule = "flag"?            → FLAG
  5. Path in game/system dir?       → SKIP
  6. dpkg-owned?                    → SKIP
  7. Content sniff says code/doc?   → SKIP
  8. Screenshot > threshold?        → FLAG
  9. AI says "delete" + confidence? → FLAG
 10. Otherwise                      → SKIP
```

The pipeline is intentionally ordered from most specific to least specific.
Structural checks (1, 2) run before rules (3, 4) because they are
evidence-based — a mod jar not loaded by any instance is a leftover regardless
of what a broad folder rule says.

**Why two passes?** The scanner first counts files (`_count_files`) to
establish a denominator for the progress bar and ETA. The second pass does the
actual analysis. This costs one extra `os.walk()` but gives the user accurate
progress feedback from the first second.

### Decision Engine

The AI decision is made by a **tabular Q-learning agent** with a state space
of `(7 × 5 × 5 × 7) = 1,225` discrete states and 2 actions (keep/delete).

**State discretization** (`state.py`):

| Dimension | Buckets | Example |
|-----------|---------|---------|
| Extension | 7 | installer, archive, log, game, code, media, other |
| Size | 5 | <100 KB, <1 MB, <10 MB, <100 MB, ≥100 MB |
| Age | 5 | <7d, <30d, <90d, <365d, ≥1y |
| Location | 7 | /tmp, Downloads, cache, game dir, Trash, system, other |

**Q-table update rule:**

```
Q(s, a) ← Q(s, a) + α · [r − Q(s, a)]
```

Where:
- `α = 0.15` (learning rate)
- `r` is the reward signal
- `s` is the discretized state
- `a` is the action (0 = keep, 1 = delete)

**Confidence calculation:**

```
confidence(s) = |Q(s, delete) − Q(s, keep)| × (1 − e^(−visits/10))
```

The exponential term discounts confidence for under-explored states. A state
seen 10 times is trusted ~63% as much as one seen 100 times. Confidence
saturates at ~95% around 30 visits.

**Action selection:**

```python
def act(self, s, explore=False):
    if explore and random.random() < self.current_epsilon():
        return random.randint(0, 1)
    q = self._q(s)
    if q[0] == q[1]:
        return 0  # tie-break: keep (conservative)
    return 0 if q[0] > q[1] else 1
```

Ties always resolve to "keep" — the conservative default.

### Protection Layers

Protection is enforced at multiple levels, each with a specific purpose:

**Level 1 — Hardcoded path protection** (`protection.py`):

```python
PSEUDO_FS = ("/proc", "/sys", "/dev", "/run", "/snap", ...)
SYSTEM_PROTECTED = ("/usr", "/etc", "/bin", "/lib", "/var/lib", ...)
GAME_DIRS = [f"{HOME}/.steam", f"{HOME}/.minecraft",
             f"{HOME}/.local/share/PrismLauncher", ...]
```

These are absolute. No rule or AI decision can override them.

**Level 2 — Content sniffing** (`sniff_file_kind`):

Reads the first 4 KB of a file and classifies it structurally:

| Kind | Action |
|------|--------|
| `critical` (`.kdbx`, `id_rsa`, `.env`, `wallet.dat`) | Skip |
| `office-doc` (`.docx`, `.odt`, `.xlsx`) | Skip |
| `text-code` (shebang, `import`, `#include`) | Skip |
| `binary-exec` (ELF header) | Skip |
| `binary-archive` (`.deb`, `.zip`, `.tar`) | Allow (installer detection) |
| `binary-magic` (PNG, JPEG, PDF) | Allow (screenshot detection) |
| `text-log` (contains "error", "warn", "traceback") | Allow |

**Level 3 — dpkg ownership** (`is_dpkg_owned`):

Reads `/var/lib/dpkg/info/*.list` into a cached set of ~500K paths. Any file
that appears in this set is skipped. This prevents the cleaner from ever
touching a system binary, library, or config file managed by `apt`.

**Level 4 — User rules** (`rules.py`):

Rules are JSON-persisted and matched in order. Four rule types:

- `folder` — path prefix match
- `extension` — suffix match (case-insensitive)
- `name_contains` — substring match
- `glob` — wildcard pattern match

Rules are seeded once with 35 sensible defaults (Documents, .ssh, /usr, etc.)
and can be edited at runtime.

**Level 5 — AI** (`agent.py`):

The AI only sees files that survived Levels 1–4. Its job is to make the final
keep/delete call based on learned preferences.

### Learning System

The agent learns from user decisions through three mechanisms:

**1. Per-file calibration** (`record_decision`):

Every time a user accepts or rejects an AI suggestion, the decision is logged
with its full context:

```python
{
  "t": 1759315200,
  "state": [2, 2, 3, 0],
  "kind": "binary-archive",
  "conf": 2.5,
  "accepted": true,
  "path": "/home/user/Downloads/installer.deb"
}
```

This feeds:
- `conf_stats` — global histogram of (confidence → acceptance rate)
- `conf_stats_ctx` — per-context histogram keyed by `(bucket, ext, loc)`
- `conf_history` — rolling window for drift detection
- `decisions.jsonl` — append-only log for offline analysis

**2. Batch reinforcement** (`reinforce_from_user`):

When a batch is confirmed, decisions are grouped by state and applied as
weighted Q-table updates:

```python
R = 3.0
MAX_BOOST = 10

for state, count in delete_counts.items():
    weight = min(count, MAX_BOOST)
    agent.learn(state, 1, +R * weight)   # delete was correct
    agent.learn(state, 0, -R * weight)   # keep would be wrong
```

The `MAX_BOOST` cap prevents a 500-file batch from saturating the Q-values.

**3. Dynamic threshold** (`dynamic_threshold`):

The minimum confidence required to show a suggestion is derived from history,
not hardcoded:

```python
def dynamic_threshold(self, state=None, target_acceptance=0.5, min_samples=15):
    # Prefer per-context data when available
    if state is not None:
        ctx = {b: v for (b, e, l), v in self.conf_stats_ctx.items()
               if e == state[0] and l == state[3]}
        if ctx:
            for b in sorted(ctx.keys()):
                shown, accepted = self._aggregate(ctx, b)
                if shown >= min_samples and accepted / shown >= target_acceptance:
                    return float(b)
    # Fall back to global
    ...
```

This means a user who consistently accepts 2.0-confidence suggestions in
`~/Downloads` gets a lower threshold there than in `~/Documents`.

**4. Epsilon decay** (`current_epsilon`):

Exploration rate decays as the agent sees more distinct states:

```python
def current_epsilon(self):
    visited = self.visited_states()
    decay = 0.995 ** max(0, visited - 50)
    return max(0.02, self.epsilon * decay)
```

Early on, the agent explores ~15% of the time. After seeing 100+ distinct
states, exploration drops to the 2% floor.

---

## Module Breakdown

| Module | Purpose | Key Classes/Functions |
|--------|---------|----------------------|
| `agent.py` | Q-learning agent, calibration, decision logging | `QLearningAgent`, `SyntheticFileEnv` |
| `state.py` | State discretization, content-kind bucketing | `size_bucket`, `age_bucket`, `ext_bucket`, `location_bucket` |
| `scanner.py` | Directory walk, decision pipeline, signal emission | `ScannerThread` |
| `protection.py` | Hardcoded protection, content sniffing, dpkg check | `sniff_file_kind`, `is_screenshot`, `is_dpkg_owned` |
| `minecraft.py` | Orphaned mod detection | `is_orphan_mod`, `get_in_use_mods` |
| `virtualmachines.py` | VM leftover detection | `is_vm_leftover`, `scan_vm_roots` |
| `rules.py` | User rule persistence and matching | `RulesManager` |
| `config.py` | Paths, constants, sentinel values | `HOME`, `CONFIG_DIR`, `CONFIDENCE_RULE` |
| `admin.py` | Admin-mode relaunch (sudo/pkexec/askpass) | `relaunch_as_admin`, `find_terminal` |
| `ui/wizard.py` | Main window, navigation, delete loop | `Wizard` |
| `ui/rule_editor.py` | Single-rule editor dialog | `RuleEditor` |
| `ui/rules_dialog.py` | Rule manager + settings | `RulesDialog` |
| `ui/training_dialog.py` | Training data import wizard | `TrainingDialog` |
| `training/` | External data pipeline (CSV/JSON/SQLite → Q-table) | `TrainingSession`, `train` |
| `tests/` | 60+ unit tests | `test_agent.py`, `test_protection.py`, etc. |

---

## Installation

### From source (recommended)

```bash
git clone https://github.com/logoali231-droid/cleanerapp
cd cleanerapp

# Install runtime dependency
sudo apt install python3-pyqt5

# Install to ~/.local/share/
./setup.sh
```

The installer:
1. Copies the package to `~/.local/share/ai-file-cleaner/`
2. Creates a launcher at `~/.local/bin/ai-file-cleaner`
3. Writes a desktop entry and icon
4. Refreshes the menu cache

### Flatpak

```bash
flatpak run --command=flathub-build org.flatpak.Builder \
    --install com.dipper.AIFileCleaner.json
```

### Build a `.deb`

```bash
./build-deb.sh
sudo apt install ./ai-file-cleaner_1.0.0_all.deb
```

---

## Usage

### First run

```bash
ai-file-cleaner
```

The agent bootstraps itself with 12,000 synthetic training episodes on first
launch (~2 seconds). After that, it learns exclusively from your decisions.

### Typical workflow

1. **Choose a folder** — start with `~/Downloads` or `~/.cache`
2. **Scan** — the agent flags candidates with reasons
3. **Review** — uncheck anything you want to keep
4. **Confirm** — files move to Trash; decisions are recorded
5. **Restore if needed** — the Done page has a one-click restore button

### Teaching the agent

Right-click any file in the review list to create a rule:

```
🛡  Always keep…
    This exact file
    Every file in this folder
    Every .jar file on the system
    Names containing "backup"

🗑  Always suggest deleting…
    (same options)
```

Rules override the AI. Extension rules also nudge the Q-table, so the agent
generalizes from a single correction.

### Orphan mod detection

If you use PrismLauncher, MultiMC, PolyMC, or vanilla Minecraft, the scanner
automatically compares every `.jar` in the target folder against the union of
all instance `mods/` directories. A jar that is structurally a mod
(contains `META-INF/mods.toml`, `fabric.mod.json`, or `mcmod.info`) but is not
loaded by any instance is flagged as an orphan.

```
Reason: "A mod you haven't used in 54 days — not loaded by any Minecraft instance"
```

Jars younger than 30 days are skipped — you may still be installing them.

### VM leftover detection

Files with VM extensions (`.vdi`, `.vmdk`, `.qcow2`, `.ova`, `.img`, `.iso`)
that are ≥500 MB, ≥90 days old, and not associated with a registered VM are
flagged. If VirtualBox is not installed, the entire `~/VirtualBox VMs` folder
is considered orphaned.

---

## Configuration

Config is stored at `~/.config/ai_file_cleaner/`:

| File | Purpose |
|------|---------|
| `qtable.pkl` | Q-table, counts, calibration data (pickle) |
| `rules.json` | User rules (JSON array) |
| `settings.json` | App settings (screenshot age, threshold, etc.) |
| `decisions.jsonl` | Append-only decision log |
| `.defaults_seeded` | Marker file for default rule seeding |

### Settings

| Key | Default | Description |
|-----|---------|-------------|
| `screenshot_min_age_days` | 30 | Flag screenshots older than this (0 = off) |
| `min_confidence` | -1 | -1 = AI-derived threshold; ≥0 = manual override |
| `skip_rule_confirmation` | false | Add rules without confirmation dialog |

### Inspecting learned state

```python
from ai_cleaner.agent import QLearningAgent
a = QLearningAgent(); a.load()
print(a.calibration_summary())
# "23 decisions, 87% accepted, threshold 1.50"
print(a.calibration_report())
# {"n": 23, "brier": 0.14, "global_buckets": 4,
#  "context_buckets": 7, "drift": False}
```

**Brier score** below 0.20 indicates well-calibrated confidence. Above 0.30
means the displayed confidence numbers are misleading.

---

## Testing

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run specific module
pytest src/ai_cleaner/tests/test_agent.py -v

# Syntax check
python3 -c "import ai_cleaner.scanner, ai_cleaner.agent; print('ok')"
```

The test suite covers:

| File | Tests | Coverage |
|------|-------|----------|
| `test_agent.py` | 10 | Q-learning, calibration, save/load |
| `test_state.py` | 7 | All bucket functions |
| `test_protection.py` | 20 | Sniffing, screenshots, path checks |
| `test_rules.py` | 8 | Rule matching, description |
| `test_training.py` | 25 | Preprocessing, schema detection, validation |
| `test_utils.py` | 4 | Formatting helpers |

---

## Design Decisions

### Why tabular Q-learning?

The state space is small (1,225 states) and the decision is single-step
(no sequential planning). A neural network would overfit on the sparse data
a single user generates. Tabular Q-learning is:
- **Interpretable** — each state-action pair has a readable Q-value
- **Adaptive** — updates in O(1) per decision
- **Debuggable** — the entire model is a pickled dictionary

This matches the conclusion of the Human-in-the-Loop RL framework for file
cleanup (Suryateja et al., 2026): tabular Q-learning with human oversight is
"safe, adaptive, interpretable, and practically deployable."

### Why structural detection for mods and VMs?

The AI cannot know whether a `.jar` is loaded by a Minecraft instance. That
information exists in the filesystem, not in the file's metadata. Structural
detection reads the instance directories directly and compares. This is a
**fail-closed** design: if no instance is found, nothing is flagged.

### Why Trash instead of delete?

`gio trash` is atomic, recoverable, and integrates with the desktop
environment. Every deletion is reversible until the user empties Trash. The
wizard also keeps a `_last_trashed` list for one-click batch restore.

### Why a JSONL decision log?

Append-only JSONL is:
- Crash-safe (partial writes don't corrupt existing entries)
- Streamable (can be read line-by-line without loading everything)
- Greppable (`grep '"accepted": false' decisions.jsonl`)

### Why two `os.walk()` passes?

The first pass counts files for the progress bar. The second pass does the
analysis. Without the first pass, the progress bar would have to guess the
denominator or use a spinner. The extra I/O is measurable (~200 ms for 100K
files) but the UX improvement is worth it.

---

## Extending the System

### Adding a new structural detector

1. Create a module (e.g., `docker.py`) with an `is_orphan_*` function
2. Add the check to `scanner.py` before the rules check
3. Use `CONFIDENCE_RULE` as the confidence value
4. Add the kind to `KIND_BUCKET` in `state.py`
5. Write tests following the `test_minecraft.py` pattern

### Adding a new state dimension

The state tuple is deliberately frozen at 4 dimensions. To add a fifth:

1. Create `extract_state_v2()` with the new dimension
2. Increment `QLearningAgent.SHAPE`
3. Add a migration path in `QLearningAgent.load()` that detects the old shape
4. Bump the Q-table format version

Without migration, every user's saved training is invalidated.

### Adding a training data loader

The `training/loader.py` module dispatches by file extension. To add a format:

1. Write a `load_<format>(path)` function returning `(rows, columns)`
2. Add the extension to `SUPPORTED_EXTS`
3. Add a dispatch line in `load_file()`

The rest of the pipeline (`preprocess`, `validate`, `train`) is format-agnostic.

### Adding a rule type

1. Add the type to `RulesManager._matches()`
2. Add it to `RulesManager.describe()`
3. Add it to `RuleEditor`'s type dropdown
4. If the type maps to a state dimension, add reinforcement logic to
   `reinforce_agent_from_rule()`

---

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

---

## Acknowledgements

- Q-learning formulation: Watkins & Dayan (1992)
- HITL-RL framework: Suryateja et al., "Human-in-the-Loop Reinforcement
  Learning for Intelligent File Cleanup in Personal Computing Systems" (ICIRCA 2026)
- Icon and UI design: original work
