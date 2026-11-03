"""Tests for the orphaned-Minecraft-mod detector."""
import zipfile

from ai_cleaner import minecraft


def _make_mod_jar(path, marker="META-INF/mods.toml"):
    """Create a valid mod jar with the given marker file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr(marker, "modLoader = \"javafml\"\n")
        z.writestr("pack.mcmeta", '{"pack":{"pack_format":15}}')
    return path


def _make_plain_jar(path):
    """A jar with no mod markers — e.g. a shaded library."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("README.txt", "not a mod")
    return path


def test_is_minecraft_jar_forge(tmp_path):
    p = _make_mod_jar(tmp_path / "forge_mod.jar")
    assert minecraft.is_minecraft_jar(p) is True


def test_is_minecraft_jar_fabric(tmp_path):
    p = _make_mod_jar(tmp_path / "fabric_mod.jar", "fabric.mod.json")
    assert minecraft.is_minecraft_jar(p) is True


def test_is_minecraft_jar_neoforge(tmp_path):
    p = _make_mod_jar(tmp_path / "neo_mod.jar",
                      "META-INF/neoforge.mods.toml")
    assert minecraft.is_minecraft_jar(p) is True


def test_is_minecraft_jar_plain(tmp_path):
    p = _make_plain_jar(tmp_path / "lib.jar")
    assert minecraft.is_minecraft_jar(p) is False


def test_is_minecraft_jar_not_a_jar(tmp_path):
    p = tmp_path / "not_a_jar.txt"
    p.write_text("hello")
    assert minecraft.is_minecraft_jar(p) is False


def test_is_minecraft_jar_corrupt(tmp_path):
    p = tmp_path / "broken.jar"
    p.write_bytes(b"\x00\x01\x02 garbage")
    assert minecraft.is_minecraft_jar(p) is False


def test_orphan_mods_against_instance(tmp_path, monkeypatch):
    # Fake a PrismLauncher install under a temp root
    inst_root = tmp_path / "instances"
    moddir = inst_root / "MyPack" / "minecraft" / "mods"
    moddir.mkdir(parents=True)

    loaded = _make_mod_jar(moddir / "loaded_mod.jar")
    orphan = _make_mod_jar(tmp_path / "downloads" / "orphan_mod.jar")

    # Point the module at our fake instance
    monkeypatch.setattr(minecraft, "INSTANCE_ROOTS", [str(inst_root)])
    minecraft._CACHE = None
    minecraft._CACHE_TIME = 0.0

    assert minecraft.has_any_instance() is True
    assert minecraft.is_orphan_mod(orphan) is True
    assert minecraft.is_orphan_mod(loaded) is False


def test_no_instances_means_no_orphans(tmp_path, monkeypatch):
    """Fail closed: no instances → nothing is an orphan."""
    orphan = _make_mod_jar(tmp_path / "some_mod.jar")
    monkeypatch.setattr(minecraft, "INSTANCE_ROOTS",
                        [str(tmp_path / "nonexistent")])
    minecraft._CACHE = None
    minecraft._CACHE_TIME = 0.0
    assert minecraft.has_any_instance() is False
    assert minecraft.is_orphan_mod(orphan) is False


def test_orphan_summary(tmp_path, monkeypatch):
    inst_root = tmp_path / "instances"
    moddir = inst_root / "Pack" / "minecraft" / "mods"
    moddir.mkdir(parents=True)
    _make_mod_jar(moddir / "used.jar")

    d = tmp_path / "downloads"
    o1 = _make_mod_jar(d / "orphan_a.jar")
    o2 = _make_mod_jar(d / "orphan_b.jar")
    _make_plain_jar(d / "not_a_mod.jar")

    monkeypatch.setattr(minecraft, "INSTANCE_ROOTS", [str(inst_root)])
    minecraft._CACHE = None
    minecraft._CACHE_TIME = 0.0

    orphans, safe, total = minecraft.orphan_summary([o1, o2])  # noqa: RUF059
    assert len(orphans) == 2
    assert total > 0
    """Tests for the orphaned-Minecraft-mod detector."""
import zipfile

import pytest
from ai_cleaner import minecraft


def _make_mod_jar(path, marker="META-INF/mods.toml"):
    """Create a valid mod jar with the given marker file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr(marker, "modLoader = \"javafml\"\n")
        z.writestr("pack.mcmeta", '{"pack":{"pack_format":15}}')
    return path


def _make_plain_jar(path):
    """A jar with no mod markers — e.g. a shaded library."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("README.txt", "not a mod")
    return path


def test_is_minecraft_jar_forge(tmp_path):
    p = _make_mod_jar(tmp_path / "forge_mod.jar")
    assert minecraft.is_minecraft_jar(p) is True


def test_is_minecraft_jar_fabric(tmp_path):
    p = _make_mod_jar(tmp_path / "fabric_mod.jar", "fabric.mod.json")
    assert minecraft.is_minecraft_jar(p) is True


def test_is_minecraft_jar_neoforge(tmp_path):
    p = _make_mod_jar(tmp_path / "neo_mod.jar",
                      "META-INF/neoforge.mods.toml")
    assert minecraft.is_minecraft_jar(p) is True


def test_is_minecraft_jar_plain(tmp_path):
    p = _make_plain_jar(tmp_path / "lib.jar")
    assert minecraft.is_minecraft_jar(p) is False


def test_is_minecraft_jar_not_a_jar(tmp_path):
    p = tmp_path / "not_a_jar.txt"
    p.write_text("hello")
    assert minecraft.is_minecraft_jar(p) is False


def test_is_minecraft_jar_corrupt(tmp_path):
    p = tmp_path / "broken.jar"
    p.write_bytes(b"\x00\x01\x02 garbage")
    assert minecraft.is_minecraft_jar(p) is False


def test_orphan_mods_against_instance(tmp_path, monkeypatch):
    # Fake a PrismLauncher install under a temp root
    inst_root = tmp_path / "instances"
    moddir = inst_root / "MyPack" / "minecraft" / "mods"
    moddir.mkdir(parents=True)

    loaded = _make_mod_jar(moddir / "loaded_mod.jar")
    orphan = _make_mod_jar(tmp_path / "downloads" / "orphan_mod.jar")

    # Point the module at our fake instance
    monkeypatch.setattr(minecraft, "INSTANCE_ROOTS", [str(inst_root)])
    minecraft._CACHE = None
    minecraft._CACHE_TIME = 0.0

    assert minecraft.has_any_instance() is True
    assert minecraft.is_orphan_mod(orphan) is True
    assert minecraft.is_orphan_mod(loaded) is False


def test_no_instances_means_no_orphans(tmp_path, monkeypatch):
    """Fail closed: no instances → nothing is an orphan."""
    orphan = _make_mod_jar(tmp_path / "some_mod.jar")
    monkeypatch.setattr(minecraft, "INSTANCE_ROOTS",
                        [str(tmp_path / "nonexistent")])
    minecraft._CACHE = None
    minecraft._CACHE_TIME = 0.0
    assert minecraft.has_any_instance() is False
    assert minecraft.is_orphan_mod(orphan) is False


def test_orphan_summary(tmp_path, monkeypatch):
    inst_root = tmp_path / "instances"
    moddir = inst_root / "Pack" / "minecraft" / "mods"
    moddir.mkdir(parents=True)
    _make_mod_jar(moddir / "used.jar")

    d = tmp_path / "downloads"
    o1 = _make_mod_jar(d / "orphan_a.jar")
    o2 = _make_mod_jar(d / "orphan_b.jar")
    _make_plain_jar(d / "not_a_mod.jar")

    monkeypatch.setattr(minecraft, "INSTANCE_ROOTS", [str(inst_root)])
    minecraft._CACHE = None
    minecraft._CACHE_TIME = 0.0

    orphans, safe, total = minecraft.orphan_summary([o1, o2])
    assert len(orphans) == 2
    assert total > 0