"""Tabular Q-learning agent + synthetic training environment."""

import json
import math
import os
import pickle
import random
import time

from .config import CONFIDENCE_RULE_THRESHOLD, DECISIONS_PATH, QTABLE_PATH
from .state import ext_bucket, kind_bucket, location_bucket


class SyntheticFileEnv:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def sample(self):
        loc = self.rng.choices(
            [0, 1, 2, 3, 4, 5, 6], weights=[15, 20, 15, 8, 10, 5, 27]
        )[0]
        if loc == 3:
            ext = 3
        elif loc == 5:
            ext = self.rng.choice([4, 5, 6])
        else:
            ext = self.rng.choices(
                [0, 1, 2, 3, 4, 5, 6], weights=[15, 15, 15, 3, 10, 15, 27]
            )[0]
        size = self.rng.choices([0, 1, 2, 3, 4], weights=[15, 25, 30, 20, 10])[0]
        age = self.rng.choices([0, 1, 2, 3, 4], weights=[15, 20, 20, 25, 20])[0]

        d = 0
        if ext == 0 and loc in (0, 1) and age >= 2 or ext == 2 and loc in (0, 2) and age >= 1 or ext == 1 and loc == 1 and age >= 3 or loc == 4:
            d = 1
        elif loc == 5 or ext == 3 or loc == 3:
            d = 0
        if self.rng.random() < 0.05:
            d = 1 - d
        return (ext, size, age, loc), d

    @staticmethod
    def reward(s, a, t):
        ext, _, _, loc = s
        if ext == 3 or loc == 3:
            return +1.0 if a == 0 else -1000.0
        if a == 1:
            return +10.0 if t == 1 else -100.0
        return -1.0 if t == 1 else +1.0


class QLearningAgent:
    """
    Tabular Q-learning agent. Pure Python (no numpy).

    Also tracks how well its own confidence predicts user acceptance — both
    globally and per context — so the display threshold adapts to taste
    without losing the safety of a global fallback.
    """

    SHAPE = (7, 5, 5, 7, 2)          # (ext, size, age, loc, action)
    CONTEXT_AXES = (0, 3)            # which state axes to condition on
    DRIFT_WINDOW = 50                # how many recent rates to check
    DRIFT_MIN_SAMPLES = 20           # don't fire drift until we have data
    DRIFT_SIGMA = 2.0                # how many std-devs counts as "drift"

    def __init__(self, alpha=0.15, epsilon=0.15):
        self.alpha = alpha
        self.epsilon = epsilon
        self.Q = self._build(self.SHAPE, 0.0)
        self.counts = self._build(self.SHAPE[:-1], 0)

        # Global confidence calibration: bucket (0.5 precision) -> [shown, accepted]
        self.conf_stats = {}
        # Per-context calibration: (bucket, ext, loc) -> [shown, accepted]
        self.conf_stats_ctx = {}
        # Rolling window of recent acceptance booleans (as 0/1 floats) for drift.
        self.conf_history = []

    # --------------------------------------------------------------- shape
    @staticmethod
    def _build(shape, default):
        if len(shape) == 1:
            return [default] * shape[0]
        return [QLearningAgent._build(shape[1:], default) for _ in range(shape[0])]

    def _q(self, s):
        return self.Q[s[0]][s[1]][s[2]][s[3]]

    def _c(self, s):
        return self.counts[s[0]][s[1]][s[2]][s[3]]

    # --------------------------------------------------------------- acting
    def current_epsilon(self):
        """
        Explore early, exploit late.

        Synthetic training runs ~20k episodes so the initial 0.15 is fine
        there, but real-user learning is much slower. We key off *visited
        states* rather than episodes: once the agent has seen 100+ distinct
        states, exploration is mainly a source of bad suggestions, so we
        decay it down to a 2% floor.
        """
        visited = self.visited_states()
        decay = 0.995 ** max(0, visited - 50)
        return max(0.02, self.epsilon * decay)

    def act(self, s, explore=False):
        if explore and random.random() < self.current_epsilon():
            return random.randint(0, 1)
        q = self._q(s)
        if q[0] == q[1]:
            return 0
        return 0 if q[0] > q[1] else 1

    def learn(self, s, a, r):
        q = self._q(s)
        q[a] += self.alpha * (r - q[a])
        self.counts[s[0]][s[1]][s[2]][s[3]] += 1

    def confidence(self, s):
        """
        Effective confidence = raw Q-gap, discounted for how well-explored
        the state is. A state seen 10 times is trusted ~63% as much as one
        seen 100 times. Trust hits ~95% around 30 visits.
        """
        raw = abs(self._q(s)[1] - self._q(s)[0])
        visits = self._c(s)
        trust = 1.0 - math.exp(-visits / 10.0)
        return raw * trust

    # --------------------------------------------------- user-feedback loop
    def record_decision(self, conf, accepted, state=None, kind=None, path=None):
        """
        Log one user decision about an AI-flagged file.

        - conf   : the confidence the AI showed (sentinel rules are ignored)
        - accepted : True if the user agreed with the AI's suggestion
        - state  : the 4-tuple (ext, size, age, loc), optional
        - kind   : sniff_file_kind() string, optional
        - path   : source file path (for the decision log), optional

        We update:
          * global histogram `conf_stats[bucket] = [shown, accepted]`
          * per-context histogram `conf_stats_ctx[(bucket, ext, loc)]`
          * rolling acceptance window `conf_history`
          * append-only decision log at DECISIONS_PATH
        """
        if conf is None or conf >= CONFIDENCE_RULE_THRESHOLD:
            return

        bucket = round(conf * 2) / 2.0

        # Global
        s = self.conf_stats.setdefault(bucket, [0, 0])
        s[0] += 1
        if accepted:
            s[1] += 1

        # Per-context (ext + loc). The size/age axes are too sparse to
        # calibrate against; they mostly affect the AI's *decision*, not the
        # user's *acceptance* of that decision.
        if state is not None:
            ext = state[0]
            loc = state[3]
            key = (bucket, ext, loc)
            cs = self.conf_stats_ctx.setdefault(key, [0, 0])
            cs[0] += 1
            if accepted:
                cs[1] += 1

        # Rolling window for drift detection
        self.conf_history.append(1.0 if accepted else 0.0)
        if len(self.conf_history) > 500:
            self.conf_history = self.conf_history[-500:]

        # Append-only log
        self._log_decision(state, kind, conf, accepted, path)

    def _log_decision(self, state, kind, conf, accepted, path):
        entry = {
            "t": int(time.time()),
            "state": list(state) if state else None,
            "kind": kind,
            "kind_b": kind_bucket(kind) if kind else None,
            "conf": float(conf),
            "accepted": bool(accepted),
            "path": path,
        }
        try:
            with open(DECISIONS_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:  # noqa: BLE001, S110
            pass

    def reinforce_from_user(self, state, action, accepted, kind=None):
        """
        Nudge the Q-table from a real user decision.

        action    : 1 = AI suggested delete, 0 = AI suggested keep
        accepted  : True = user agreed, False = user overrode
        kind      : sniff kind, used to decide how far to generalize

        Why asymmetric:
          * Confirming a delete is weak evidence — the user might have been
            in a hurry.
          * Overriding the AI is strong evidence — the user cared enough to
            intervene. We punish the wrong action *and* reward the correct
            one, so the next encounter goes right.
        """
        if state is None:
            return

        ext, _size, _age, loc = state

        if accepted:
            r = +12.0 if action == 1 else +4.0
            self.learn(state, action, r)
        else:
            r = -30.0 if action == 1 else -8.0
            self.learn(state, action, r)
            self.learn(state, 1 - action, -r / 2)

        # Generalize to neighbours that share the same ext + loc.
        # How far we generalize depends on the content kind:
        #   - text-config files (e.g. a .conf that's actually a shell script)
        #     deserve cautious generalization, because "old config" is a
        #     weaker signal than "old installer".
        #   - archive / binary content generalizes confidently.
        kb = kind_bucket(kind) if kind else 0
        spread = 0.15
        if kb in (2, 6):        # text-config, office-doc — be cautious
            spread = 0.05
        elif kb in (4, 5):      # archive, binary-magic — trust the lesson
            spread = 0.25

        for s_b in range(5):
            for a_b in range(5):
                nb = (ext, s_b, a_b, loc)
                if nb == state:
                    continue
                self.learn(nb, action, r * spread)
                if not accepted:
                    self.learn(nb, 1 - action, -r * spread / 2)

    # ------------------------------------------------------- calibration
    def _aggregate(self, table, floor_bucket):
        """Sum shown/accepted over buckets >= floor_bucket."""
        shown = 0
        accepted = 0
        for b, (sh, ac) in table.items():
            if b >= floor_bucket:
                shown += sh
                accepted += ac
        return shown, accepted

    def dynamic_threshold(self, state=None, target_acceptance=0.5, min_samples=15):
        """
        Return the lowest confidence at which the user historically accepts
        at least `target_acceptance` of flags.

        If `state` is given, prefer the per-context histogram when it has
        enough data; otherwise fall back to the global one. Returns 0.0 when
        there isn't enough data anywhere — fail open.
        """
        if state is not None:
            ext, _s, _a, loc = state
            ctx = {b: v for (b, e, l), v in self.conf_stats_ctx.items()
                   if e == ext and l == loc}
            if ctx:
                for b in sorted(ctx.keys()):
                    shown, accepted = self._aggregate(ctx, b)
                    if shown < min_samples:
                        continue
                    if accepted / shown >= target_acceptance:
                        return float(b)

        if not self.conf_stats:
            return 0.0
        for b in sorted(self.conf_stats.keys()):
            shown, accepted = self._aggregate(self.conf_stats, b)
            if shown < min_samples:
                continue
            if accepted / shown >= target_acceptance:
                return float(b)
        return 0.0

    def calibration_drift(self):
        """
        True if recent acceptance rate is more than DRIFT_SIGMA standard
        deviations from the window mean — i.e. the user's taste has shifted
        and the calibration is stale.
        """
        if len(self.conf_history) < self.DRIFT_MIN_SAMPLES:
            return False
        window = self.conf_history[-self.DRIFT_WINDOW:]
        n = len(window)
        mean = sum(window) / n
        var = sum((x - mean) ** 2 for x in window) / n
        sigma = math.sqrt(var) or 1e-6
        recent_n = min(10, n // 2)
        recent = sum(window[-recent_n:]) / recent_n
        return abs(recent - mean) > self.DRIFT_SIGMA * sigma

    def reset_calibration(self):
        self.conf_stats = {}
        self.conf_stats_ctx = {}
        self.conf_history = []

    def calibration_summary(self, state=None):
        """Human-readable summary of what the agent has learned."""
        if not self.conf_stats and not self.conf_stats_ctx:
            return "no decisions recorded yet"
        total = sum(s[0] for s in self.conf_stats.values())
        accepted = sum(s[1] for s in self.conf_stats.values())
        rate = (accepted / total) if total else 0
        thr = self.dynamic_threshold(state=state)
        drift = " (drifting)" if self.calibration_drift() else ""
        return (f"{total} decisions, {rate * 100:.0f}% accepted, "
                f"threshold {thr:.2f}{drift}")

    def calibration_report(self):
        if not self.conf_stats:
            return {"n": 0}
        # Normalize against the largest bucket we've actually seen, floored
        # at 1.0 so a single low-confidence decision doesn't zero out.
        max_b = max((b for b in self.conf_stats if b > 0), default=1.0)
        norm = max(1.0, max_b)
        n = 0
        brier = 0.0
        for b, (shown, accepted) in self.conf_stats.items():
            pred = min(1.0, b / norm)
            for _ in range(accepted):
                brier += (pred - 1.0) ** 2
                n += 1
            for _ in range(shown - accepted):
                brier += (pred - 0.0) ** 2
                n += 1
        return {
            "n": n,
            "brier": (brier / n) if n else None,
            "global_buckets": len(self.conf_stats),
            "context_buckets": len(self.conf_stats_ctx),
            "drift": self.calibration_drift(),
        }

    # ------------------------------------------------------- persistence
    def visited_states(self):
        n = 0
        for a in range(self.SHAPE[0]):
            for b in range(self.SHAPE[1]):
                for c in range(self.SHAPE[2]):
                    for d in range(self.SHAPE[3]):
                        if self.counts[a][b][c][d] > 0:
                            n += 1
        return n

    def save(self, path=QTABLE_PATH):
        try:
            with open(path, "wb") as f:
                pickle.dump(
                    {
                        "Q": self.Q,
                        "counts": self.counts,
                        "conf_stats": self.conf_stats,
                        "conf_stats_ctx": self.conf_stats_ctx,
                        "conf_history": self.conf_history,
                    },
                    f,
                )
        except Exception:  # noqa: BLE001, S110
            pass

    def load(self, path=QTABLE_PATH):
        if not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                d = pickle.load(f)
            Q = d["Q"]
            counts = d["counts"]
            if hasattr(Q, "tolist"):
                Q = Q.tolist()
            if hasattr(counts, "tolist"):
                counts = counts.tolist()
            self.Q = Q
            self.counts = counts
            self.conf_stats = d.get("conf_stats", {})
            self.conf_stats_ctx = d.get("conf_stats_ctx", {})
            self.conf_history = d.get("conf_history", [])
            return True
        except Exception:  # noqa: BLE001
            return False

    def reset(self):
        self.Q = self._build(self.SHAPE, 0.0)
        self.counts = self._build(self.SHAPE[:-1], 0)
        self.reset_calibration()


def train_agent(agent, episodes=20000, seed=None):
    env = SyntheticFileEnv(seed=seed)
    for _ in range(episodes):
        s, t = env.sample()
        a = agent.act(s, explore=True)
        agent.learn(s, a, env.reward(s, a, t))


def reinforce_agent_from_rule(agent, rule, strength=30.0):
    """
    Nudge the Q-table so the AI generalizes from a user rule.

    Extension rules spread across the ext axis (the strongest signal).
    Folder rules spread across the location axis. Name rules are skipped —
    we don't have a state axis for filenames, and pretending we do would
    spread wrong lessons.
    """
    t = rule.get("type")
    action = 0 if rule.get("action") == "protect" else 1
    other = 1 - action
    reward = strength if action == 0 else strength * 0.6

    if t == "extension":
        v = rule.get("value", "")
        if not v:
            return
        if not v.startswith("."):
            v = "." + v
        eb = ext_bucket(v)
        for s in range(5):
            for a in range(5):
                for l in range(7):
                    st = (eb, s, a, l)
                    for _ in range(30):
                        agent.learn(st, action, +reward)
                        agent.learn(st, other, -reward)
        return

    if t == "folder":
        v = rule.get("value", "")
        if not v:
            return
        lb = location_bucket(v)
        for e in range(7):
            for s in range(5):
                for a in range(5):
                    st = (e, s, a, lb)
                    for _ in range(10):
                        agent.learn(st, action, +reward)
                        agent.learn(st, other, -reward)
        return

    # name_contains / glob — no meaningful state axis, skip.
    return