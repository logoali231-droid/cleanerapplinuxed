from ai_cleaner.agent import QLearningAgent, SyntheticFileEnv


def test_agent_act_returns_binary():
    a = QLearningAgent()
    for s in [(0, 0, 0, 0), (3, 2, 1, 4), (6, 4, 4, 6)]:
        assert a.act(s, explore=False) in (0, 1)


def test_agent_learn_updates_q():
    a = QLearningAgent()
    s = (0, 1, 2, 3)
    before = a.Q[0][1][2][3][1]
    a.learn(s, 1, +10.0)
    assert a.Q[0][1][2][3][1] > before
    assert a.counts[0][1][2][3] == 1


def test_confidence_grows_with_visits():
    a = QLearningAgent()
    s = (2, 2, 2, 2)
    for _ in range(50):
        a.learn(s, 1, +10.0)
    c1 = a.confidence(s)
    for _ in range(100):
        a.learn(s, 1, +10.0)
    c2 = a.confidence(s)
    assert c2 >= c1


def test_record_decision_skips_rule_confidences():
    a = QLearningAgent()
    a.record_decision(999.0, True)
    a.record_decision(950.0, False)
    assert a.conf_stats == {}


def test_record_decision_buckets():
    a = QLearningAgent()
    a.record_decision(2.3, True)
    a.record_decision(2.4, False)
    a.record_decision(0.3, True)
    assert a.conf_stats[2.5] == [2, 1]
    assert a.conf_stats[0.5] == [1, 1]


def test_dynamic_threshold_empty():
    a = QLearningAgent()
    assert a.dynamic_threshold() == 0.0


def test_dynamic_threshold_finds_floor():
    a = QLearningAgent()
    for _ in range(18):
        a.record_decision(2.5, True)
    for _ in range(2):
        a.record_decision(2.5, False)
    t = a.dynamic_threshold(target_acceptance=0.5, min_samples=15)
    assert t == 2.5


def test_save_load_roundtrip(tmp_path):
    a = QLearningAgent()
    s = (1, 1, 1, 1)
    for _ in range(20):
        a.learn(s, 1, +5.0)
    a.record_decision(2.5, True)
    path = tmp_path / "q.json"
    assert a.save(str(path))

    b = QLearningAgent()
    assert b.load(str(path))
    assert b.Q == a.Q
    assert b.counts == a.counts
    assert b.conf_stats == a.conf_stats


def test_synthetic_env_shapes():
    env = SyntheticFileEnv(seed=42)
    for _ in range(200):
        s, label = env.sample()
        assert label in (0, 1)
        assert 0 <= s[0] <= 6
        assert 0 <= s[1] <= 4
        assert 0 <= s[2] <= 4
        assert 0 <= s[3] <= 6


def test_reset_calibration():
    a = QLearningAgent()
    a.record_decision(2.5, True)
    assert a.conf_stats
    a.reset_calibration()
    assert a.conf_stats == {}


def test_rejected_suggestion_teaches_agent_to_keep():
    agent = QLearningAgent()

    state = (0, 1, 2, 1)

    agent.reinforce_from_user(
        state,
        action=1,
        accepted=False,
        kind="binary-archive",
    )

    keep_value = agent.Q[0][1][2][1][0]
    delete_value = agent.Q[0][1][2][1][1]

    assert keep_value > delete_value


def test_json_qtable_roundtrip(tmp_path):

    a = QLearningAgent()

    state = (2, 3, 1, 2)

    a.learn(state, 1, 10.0)
    a.record_decision(2.5, True, state=state)

    path = tmp_path / "qtable.json"

    assert a.save(str(path))

    b = QLearningAgent()

    assert b.load(str(path))

    assert b.Q == a.Q
    assert b.counts == a.counts
    assert b.conf_stats == a.conf_stats
    assert b.conf_stats_ctx == a.conf_stats_ctx


def test_invalid_json_qtable_is_rejected(tmp_path):

    path = tmp_path / "invalid.json"

    path.write_text('{"version": 1, "Q": []}')

    agent = QLearningAgent()

    assert not agent.load(str(path))