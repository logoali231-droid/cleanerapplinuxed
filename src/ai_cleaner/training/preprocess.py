"""Turn raw rows into (state, label, weight) tuples."""
from ..state import (ext_bucket, size_bucket, age_bucket, location_bucket)

MIN_SIZE_BYTES = 0
MAX_SIZE_BYTES = 10 * 1024 ** 4   # 10 TB sanity cap
MAX_AGE_DAYS = 365 * 50           # 50 years sanity cap


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    # handle "1.5M" / "2 GB" style suffixes
    suffixes = {"k": 1e3, "kb": 1e3, "kib": 1024,
                "m": 1e6, "mb": 1e6, "mib": 1024 ** 2,
                "g": 1e9, "gb": 1e9, "gib": 1024 ** 3,
                "t": 1e12, "tb": 1e12, "tib": 1024 ** 4}
    for suf, mul in suffixes.items():
        if s.lower().endswith(suf):
            try:
                return float(s[:-len(suf)].strip()) * mul
            except ValueError:
                pass
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(v):
    f = _to_float(v)
    return int(f) if f is not None else None


def _parse_label(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "junk", "delete", "d", "trash",
             "remove", "delete_me", "deletable"):
        return 1
    if s in ("0", "false", "no", "n", "keep", "keeper", "k", "important",
             "protected", "safe", "retain"):
        return 0
    try:
        return 1 if int(float(s)) != 0 else 0
    except ValueError:
        return None


def _parse_ext(v):
    if v is None:
        return ""
    s = str(v).strip().lower()
    if not s:
        return ""
    if not s.startswith("."):
        s = "." + s
    return s


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def row_to_example(row, schema):
    """
    Convert a raw row (dict) using the schema mapping into
    (state, label, weight) or None if the row is unusable.
    """
    def get(field):
        col = schema.get(field)
        return row.get(col) if col else None

    label = _parse_label(get("label"))
    if label is None:
        return None

    weight = _to_float(get("weight")) or 1.0
    if weight <= 0:
        return None
    weight = min(weight, 100.0)  # cap absurd weights

    # --- pre-bucketed path ---
    if all(k in schema for k in
           ("ext_bucket", "size_bucket", "age_bucket", "loc_bucket")):
        try:
            e = _clamp(_to_int(get("ext_bucket")) or 0, 0, 6)
            s = _clamp(_to_int(get("size_bucket")) or 0, 0, 4)
            a = _clamp(_to_int(get("age_bucket")) or 0, 0, 4)
            l = _clamp(_to_int(get("loc_bucket")) or 0, 0, 6)
        except (TypeError, ValueError):
            return None
        return ((e, s, a, l), label, weight)

    # --- raw properties path ---
    size = _to_int(get("size_bytes"))
    age = _to_float(get("age_days"))
    ext = _parse_ext(get("extension"))
    loc = get("location")
    if size is None or age is None or loc is None:
        return None

    size = _clamp(size, MIN_SIZE_BYTES, MAX_SIZE_BYTES)
    age = _clamp(age, 0.0, MAX_AGE_DAYS)

    state = (
        ext_bucket(ext),
        size_bucket(size),
        age_bucket(age),
        location_bucket(str(loc)),
    )
    return (state, label, weight)


def dedupe(examples, mode="keep_first"):
    """
    Remove duplicate (state, label) pairs. Because Q-learning is
    order-dependent, duplicates aren't just noise — they double the
    effective weight of an example. We collapse them.

    Modes:
      'keep_first'   — keep the first occurrence
      'sum_weights'  — combine weights (capped)
      'vote'         — majority label wins per state
    """
    if mode == "keep_first":
        seen = set()
        out = []
        for ex in examples:
            key = (ex[0], ex[1])
            if key in seen:
                continue
            seen.add(key)
            out.append(ex)
        return out

    if mode == "sum_weights":
        buckets = {}
        for state, label, w in examples:
            key = (state, label)
            buckets[key] = min(buckets.get(key, 0.0) + w, 100.0)
        return [(s, l, w) for (s, l), w in buckets.items()]

    if mode == "vote":
        votes = {}
        for state, label, _ in examples:
            votes.setdefault(state, {0: 0, 1: 0})[label] += 1
        return [(state, 1 if c[1] > c[0] else 0, 1.0)
                for state, c in votes.items()]

    return examples


def detect_conflicts(examples):
    """Return states that have both KEEP and DELETE labels."""
    per_state = {}
    for state, label, _ in examples:
        per_state.setdefault(state, set()).add(label)
    return {s for s, labels in per_state.items() if len(labels) > 1}


def balance(examples, strategy="class_weights"):
    """
    Handle class imbalance.

    'none'          — leave as-is
    'class_weights' — scale row weights so both classes have equal total
    'undersample'   — drop majority-class rows randomly
    'oversample'    — duplicate minority-class rows
    """
    if strategy == "none":
        return examples

    pos = [e for e in examples if e[1] == 1]
    neg = [e for e in examples if e[1] == 0]
    if not pos or not neg:
        return examples

    if strategy == "class_weights":
        w_pos = sum(e[2] for e in pos)
        w_neg = sum(e[2] for e in neg)
        if w_pos == 0 or w_neg == 0:
            return examples
        target = (w_pos + w_neg) / 2
        scale_pos = target / w_pos
        scale_neg = target / w_neg
        return ([(s, l, w * scale_pos) for s, l, w in pos]
                + [(s, l, w * scale_neg) for s, l, w in neg])

    if strategy == "undersample":
        n = min(len(pos), len(neg))
        return pos[:n] + neg[:n]

    if strategy == "oversample":
        n = max(len(pos), len(neg))

        def _rep(lst):
            if not lst:
                return []
            out = []
            while len(out) < n:
                out.extend(lst)
            return out[:n]

        return _rep(pos) + _rep(neg)

    return examples


def preprocess(rows, schema, options):
    """
    Pipeline: row → example → filter → dedupe → balance → cap.
    Returns (examples, stats_dict).
    """
    examples = []
    bad_rows = 0
    for row in rows:
        ex = row_to_example(row, schema)
        if ex is None:
            bad_rows += 1
        else:
            examples.append(ex)

    n_before = len(examples)
    conflicts = detect_conflicts(examples)

    if options.dedupe:
        examples = dedupe(examples, mode=options.dedupe_mode)

    if options.drop_conflicts and conflicts:
        examples = [e for e in examples if e[0] not in conflicts]

    n_dedup = len(examples)

    if options.balance != "none":
        examples = balance(examples, options.balance)

    if options.max_examples > 0 and len(examples) > options.max_examples:
        # stratify: keep proportional split of labels
        pos = [e for e in examples if e[1] == 1]
        neg = [e for e in examples if e[1] == 0]
        ratio = len(pos) / max(1, len(examples))
        cap_pos = int(options.max_examples * ratio)
        cap_neg = options.max_examples - cap_pos
        examples = pos[:cap_pos] + neg[:cap_neg]

    stats = {
        "rows_in": len(rows),
        "bad_rows": bad_rows,
        "examples_after_parse": n_before,
        "examples_after_dedupe": n_dedup,
        "examples_final": len(examples),
        "conflicts": len(conflicts),
        "n_delete": sum(1 for _, l, _ in examples if l == 1),
        "n_keep": sum(1 for _, l, _ in examples if l == 0),
    }
    return examples, stats