# Wiring the improvements into `ui/wizard.py`

Everything below is additive. Existing code paths keep working.

## 1. Switch to the batched `files_found` signal (recommended)

`ScannerThread` emits both signals:

```python
files_found = pyqtSignal(list)   # batched — prefer this
file_found  = pyqtSignal(dict)   # legacy — still works
```

**Old:**

```python
self.scanner.file_found.connect(self._on_file_found)
```

**New:**

```python
self.scanner.files_found.connect(self._on_files_found)

def _on_files_found(self, items):
    for info in items:
        # ... same body as old _on_file_found(info) ...
```

Once switched, set `EMIT_LEGACY_FILE_SIGNAL = False` in `scanner.py`. Removes
one Qt signal dispatch per file. Big deal at 100k+ files.

## 2. Record every decision (this is the whole point)

Whenever the user resolves a file the AI suggested (i.e. `info["confidence"] < 900`),
call **both** `record_decision` (for calibration) and `reinforce_from_user`
(for Q-table learning):

```python
# when the user accepts a deletion
def _on_accept(self, info):
    state = info.get("state")
    conf = info.get("confidence")
    kind = info.get("kind")
    self.agent.record_decision(conf, accepted=True, state=state, kind=kind,
                               path=info.get("path"))
    self.agent.reinforce_from_user(state, action=1, accepted=True, kind=kind)

# when the user rejects / unchecks a suggestion
def _on_reject(self, info):
    state = info.get("state")
    conf = info.get("confidence")
    kind = info.get("kind")
    self.agent.record_decision(conf, accepted=False, state=state, kind=kind,
                               path=info.get("path"))
    self.agent.reinforce_from_user(state, action=1, accepted=False, kind=kind)
```

Then, at end of session (or after every N decisions):

```python
self.agent.save()
```

**Sanity check.** After a few sessions, in a debug REPL:

```python
print(self.agent.calibration_summary())
# → "23 decisions, 87% accepted, threshold 1.50"

print(self.agent.calibration_report())
# → {"n": 23, "brier": 0.14, "global_buckets": 4,
#    "context_buckets": 7, "drift": False}
```

Brier below ~0.20 is good. Above ~0.30 means the confidence numbers are
misleading and you should consider showing less of them in the UI.

## 3. Use `kind` in the "Why?" panel (optional)

The scanner now includes `info["kind"]` on every flagged file. Use it to
give the user a concrete explanation:

```python
kind = info.get("kind") or "unknown"
ext  = info["path"].rsplit(".", 1)[-1] if "." in info["path"] else "—"
size = human(info["size"])
age  = f"{info['age']} days"

why = f"{kind.replace('-', ' ')} · {ext} · {size} · {age}"
```

## 4. Handle calibration drift (optional but nice)

At scan start:

```python
if self.agent.calibration_drift():
    self.status_label.setText(
        "Calibration shifted — the AI is re-learning your taste")
```

This gives the user a reason to trust what they see when the threshold
suddenly moves.

## 5. Reinforce the Q-table when a rule is added (recommended)

When the user adds a rule in the Rules dialog, call:

```python
from ..agent import reinforce_agent_from_rule

def _on_rule_added(self, rule):
    reinforce_agent_from_rule(self.agent, rule, strength=30.0)
    self.agent.save()
```

This is the cold-start fix: a user who's never interacted with the AI can
add two or three rules and get useful suggestions immediately, because the
Q-table already knows what those rules mean.