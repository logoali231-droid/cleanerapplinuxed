from pathlib import Path

from ai_cleaner.state import (
    size_bucket, age_bucket, ext_bucket, location_bucket,
    extract_state, plain_reason,
)


def test_size_bucket():
    assert size_bucket(0) == 0
    assert size_bucket(50_000) == 0
    assert size_bucket(500_000) == 1
    assert size_bucket(5 * 1048576) == 2
    assert size_bucket(50 * 1048576) == 3
    assert size_bucket(500 * 1048576) == 4


def test_age_bucket():
    assert age_bucket(0) == 0
    assert age_bucket(6) == 0
    assert age_bucket(7) == 1
    assert age_bucket(29) == 1
    assert age_bucket(30) == 2
    assert age_bucket(89) == 2
    assert age_bucket(90) == 3
    assert age_bucket(364) == 3
    assert age_bucket(365) == 4


def test_ext_bucket():
    assert ext_bucket(".deb") == 0
    assert ext_bucket(".zip") == 1
    assert ext_bucket(".log") == 2
    assert ext_bucket(".jar") == 3
    assert ext_bucket(".py") == 4
    assert ext_bucket(".png") == 5
    assert ext_bucket(".xyz") == 6
    assert ext_bucket(".DEB") == 0


def test_location_bucket():
    assert location_bucket("/tmp/foo") == 0
    assert location_bucket("/home/u/Downloads/x") == 1
    assert location_bucket("/home/u/.cache/x") == 2
    assert location_bucket("/home/u/steamapps/x") == 3
    assert location_bucket("/home/u/.local/share/Trash/x") == 4
    assert location_bucket("/usr/lib/x") == 5
    assert location_bucket("/home/u/random") == 6


def test_extract_state():
    s = extract_state(Path("/tmp/installer.deb"), 5 * 1048576, 45)
    assert s == (0, 2, 2, 0)


def test_plain_reason_installer():
    assert "installer" in plain_reason(Path("/x/y.deb"), 1000, 200).lower()


def test_plain_reason_archive():
    assert "download" in plain_reason(Path("/x/y.zip"), 1000, 200).lower()


def test_plain_reason_cache():
    assert "cache" in plain_reason(Path("/var/cache/x"), 1000, 200).lower()
