from ai_cleaner.utils import human, age, duration, short_path


def test_human():
    assert human(0) == "0 B"
    assert human(512) == "512 B"
    assert human(1024) == "1.0 KB"
    assert human(1536) == "1.5 KB"
    assert human(1048576) == "1.0 MB"
    assert human(1073741824) == "1.0 GB"


def test_age():
    assert age(0) == "today"
    assert age(0.5) == "today"
    assert age(1) == "1d old"
    assert age(29) == "29d old"
    assert age(30) == "1mo old"
    assert age(60) == "2mo old"
    assert age(365) == "1y old"


def test_duration():
    assert duration(0) == "a few seconds"
    assert duration(3) == "a few seconds"
    assert duration(10) == "10 seconds"
    assert duration(45) == "45 seconds"
    assert duration(60) == "1 min"
    assert duration(90) == "1 min 30 sec"
    assert duration(120) == "2 min"
    assert duration(1500) == "25 min"
    assert duration(3600) == "1 h"
    assert duration(5400) == "1 h 30 min"


def test_short_path():
    assert short_path("/short", 80) == "/short"
    long = "/a" * 100
    out = short_path(long, 20)
    assert len(out) <= 20
    assert out.startswith("…")
