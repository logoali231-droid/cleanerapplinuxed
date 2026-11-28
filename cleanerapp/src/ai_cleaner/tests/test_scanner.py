from pathlib import Path

import ai_cleaner.scanner as scanner_module
from ai_cleaner.scanner import ScannerThread


class FakeRules:
    settings = {
        "screenshot_min_age_days": 30,
        "min_confidence": -1,
    }

    def match(self, path):
        if Path(path).name == "node_modules":
            return "protect", {
                "type": "name_contains",
                "value": "node_modules",
                "action": "protect",
            }
        return None, None


class FakeAgent:
    def __init__(self):
        self.act_calls = []

    def dynamic_threshold(self):
        return 0.0

    def calibration_summary(self):
        return "no decisions recorded yet"

    def act(self, state, explore=False):
        self.act_calls.append((state, explore))
        return 0

    def confidence(self, state):
        return 0.0


def test_protected_rules_prune_directories(tmp_path):
    scanner = ScannerThread(tmp_path, FakeAgent(), FakeRules())

    assert scanner._should_prune_dir(tmp_path, "node_modules")


def test_scan_walks_once_and_uses_q_learning_for_eligible_files(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "ordinary.txt").write_text("ordinary text")
    package_dir = tmp_path / "node_modules" / "example"
    package_dir.mkdir(parents=True)
    (package_dir / "dependency.js").write_text("const dependency = true;")

    monkeypatch.setattr(
        scanner_module,
        "is_hard_protected_path",
        lambda _path: False,
    )
    monkeypatch.setattr(
        scanner_module,
        "is_hard_protected_file",
        lambda _path, **_kwargs: False,
    )
    monkeypatch.setattr(scanner_module, "is_dpkg_owned", lambda _path: False)
    monkeypatch.setattr(
        scanner_module,
        "sniff_file_kind",
        lambda _path: ("text-data", "test content"),
    )
    monkeypatch.setattr(
        scanner_module,
        "is_screenshot",
        lambda _path: False,
    )

    real_walk = scanner_module.os.walk
    walk_calls = []

    def counted_walk(*args, **kwargs):
        walk_calls.append(args[0])
        yield from real_walk(*args, **kwargs)

    monkeypatch.setattr(scanner_module.os, "walk", counted_walk)

    agent = FakeAgent()
    scanner = ScannerThread(tmp_path, agent, FakeRules())
    scanner.run()

    assert len(walk_calls) == 1
    assert len(agent.act_calls) == 1
    assert agent.act_calls[0][1] is False
