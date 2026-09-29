from ai_cleaner.training.preprocess import (
    row_to_example, dedupe, balance, detect_conflicts,
    _parse_label, _parse_ext, _to_float,
)
from ai_cleaner.training.schema import (
    detect_schema, is_prebucketed, is_raw_properties,
    can_classify, missing_for_classification,
)
from ai_cleaner.training.validator import validate, state_space_size


# ---------------------------------------------------------------- preprocess

def test_parse_label():
    assert _parse_label("junk") == 1
    assert _parse_label("delete") == 1
    assert _parse_label("true") == 1
    assert _parse_label("1") == 1
    assert _parse_label("keep") == 0
    assert _parse_label("false") == 0
    assert _parse_label("0") == 0
    assert _parse_label(None) is None
    assert _parse_label("garbage") is None


def test_parse_ext():
    assert _parse_ext("deb") == ".deb"
    assert _parse_ext(".deb") == ".deb"
    assert _parse_ext("DEB") == ".deb"
    assert _parse_ext(None) == ""
    assert _parse_ext("") == ""


def test_to_float():
    assert _to_float(5) == 5.0
    assert _to_float("5") == 5.0
    assert _to_float("1.5M") == 1.5e6
    assert _to_float("2 GB") == 2e9
    assert _to_float("2gb") == 2e9
    assert _to_float("") is None
    assert _to_float(None) is None


def test_row_to_example_raw():
    schema = {"extension": "ext", "size_bytes": "size",
              "age_days": "age", "location": "loc", "label": "y"}
    row = {"ext": ".deb", "size": "1048576", "age": 200,
           "loc": "/tmp/x", "y": "junk"}
    ex = row_to_example(row, schema)
    assert ex is not None
    state, label, weight = ex
    assert label == 1
    assert len(state) == 4
    assert weight == 1.0


def test_row_to_example_missing_label():
    schema = {"extension": "ext", "size_bytes": "size",
              "age_days": "age", "location": "loc", "label": "y"}
    row = {"ext": ".deb", "size": "1048576", "age": 200, "loc": "/tmp/x"}
    assert row_to_example(row, schema) is None


def test_row_to_example_prebucketed():
    schema = {"ext_bucket": "e", "size_bucket": "s",
              "age_bucket": "a", "loc_bucket": "l", "label": "y"}
    row = {"e": 0, "s": 2, "a": 2, "l": 0, "y": 1}
    ex = row_to_example(row, schema)
    assert ex[0] == (0, 2, 2, 0)
    assert ex[1] == 1


def test_dedupe_keep_first():
    examples = [((0, 0, 0, 0), 1, 1.0),
                ((0, 0, 0, 0), 1, 2.0),
                ((1, 1, 1, 1), 0, 1.0)]
    assert len(dedupe(examples, mode="keep_first")) == 2


def test_dedupe_sum_weights():
    examples = [((0, 0, 0, 0), 1, 1.0), ((0, 0, 0, 0), 1, 2.0)]
    out = dedupe(examples, mode="sum_weights")
    assert len(out) == 1
    assert out[0][2] == 3.0


def test_dedupe_vote():
    examples = [((0, 0, 0, 0), 1, 1.0),
                ((0, 0, 0, 0), 1, 1.0),
                ((0, 0, 0, 0), 0, 1.0)]
    out = dedupe(examples, mode="vote")
    assert out[0][1] == 1


def test_detect_conflicts():
    examples = [((0, 0, 0, 0), 1, 1.0),
                ((0, 0, 0, 0), 0, 1.0),
                ((1, 1, 1, 1), 1, 1.0)]
    conflicts = detect_conflicts(examples)
    assert (0, 0, 0, 0) in conflicts
    assert (1, 1, 1, 1) not in conflicts


def test_balance_none():
    examples = [((0, 0, 0, 0), 1, 1.0), ((1, 1, 1, 1), 0, 1.0)]
    assert balance(examples, "none") == examples


def test_balance_oversample():
    examples = [((0, 0, 0, 0), 1, 1.0)] * 3 + [((1, 1, 1, 1), 0, 1.0)]
    out = balance(examples, "oversample")
    assert len(out) == 6
    assert sum(1 for _, l, _ in out if l == 0) == 3
    assert sum(1 for _, l, _ in out if l == 1) == 3


def test_balance_class_weights():
    examples = [((0, 0, 0, 0), 1, 1.0)] * 3 + [((1, 1, 1, 1), 0, 1.0)]
    out = balance(examples, "class_weights")
    w_pos = sum(w for _, l, w in out if l == 1)
    w_neg = sum(w for _, l, w in out if l == 0)
    assert abs(w_pos - w_neg) < 1e-9


# ------------------------------------------------------------------ schema

def test_detect_schema_exact():
    cols = ["extension", "size_bytes", "age_days", "location", "label"]
    s = detect_schema(cols)
    assert s["extension"] == "extension"
    assert s["size_bytes"] == "size_bytes"
    assert s["label"] == "label"


def test_detect_schema_alias():
    cols = ["ext", "size", "age", "path", "junk"]
    s = detect_schema(cols)
    assert s["extension"] == "ext"
    assert s["size_bytes"] == "size"
    assert s["age_days"] == "age"
    assert s["location"] == "path"
    assert s["label"] == "junk"


def test_detect_schema_case_insensitive():
    cols = ["EXT", "SIZE", "AGE", "LOCATION", "LABEL"]
    s = detect_schema(cols)
    assert s["extension"] == "EXT"
    assert s["label"] == "LABEL"


def test_can_classify_raw():
    schema = {"extension": "e", "size_bytes": "s",
              "age_days": "a", "location": "l", "label": "y"}
    assert can_classify(schema)


def test_can_classify_prebucketed():
    schema = {"ext_bucket": "e", "size_bucket": "s",
              "age_bucket": "a", "loc_bucket": "l", "label": "y"}
    assert can_classify(schema)


def test_can_classify_missing():
    assert not can_classify({"extension": "e", "label": "y"})


def test_missing_for_classification():
    missing = missing_for_classification({"label": "y"})
    assert "label" not in missing
    for f in ("extension", "size_bytes", "age_days", "location"):
        assert f in missing


def test_is_prebucketed():
    assert is_prebucketed({"ext_bucket": "a", "size_bucket": "b",
                           "age_bucket": "c", "loc_bucket": "d"})
    assert not is_prebucketed({"ext_bucket": "a"})


def test_is_raw_properties():
    assert is_raw_properties({"extension": "a", "size_bytes": "b",
                              "age_days": "c", "location": "d"})
    assert not is_raw_properties({"extension": "a"})


# ----------------------------------------------------------------- validator

def test_state_space_size():
    assert state_space_size() == 7 * 5 * 5 * 7
    assert state_space_size() == 1225


def test_validate_empty():
    r = validate([])
    assert r["risk"] == "high"
    assert r["coverage"] == 0.0


def test_validate_simple():
    examples = [((0, 0, 0, 0), 1, 1.0)] * 50 + [((1, 1, 1, 1), 0, 1.0)] * 50
    r = validate(examples)
    assert r["total"] == 100
    assert r["unique_states"] == 2
    assert r["class_balance"] == 0.5
    assert r["coverage"] == 2 / 1225
    assert r["conflicts"] == 0


def test_validate_conflicts():
    examples = [((0, 0, 0, 0), 1, 1.0), ((0, 0, 0, 0), 0, 1.0)]
    r = validate(examples)
    assert r["conflicts"] == 1
