"""
Minecraft / PrismLauncher integration.

The problem this solves:
  When you install a mod manually (because a modpack's launcher blocked it),
  you drop the jar in ~/Downloads, copy it into the instance's mods/ folder,
  then forget to delete the original. When you change modpacks later, the
  manual jar stays in ~/Downloads forever.

  This module finds the mods that ARE loaded by some instance, so the
  scanner can safely flag the leftovers.
"""
import os
import time
import zipfile
from pathlib import Path

from .config import HOME

# Roots that may contain instance directories.
# PrismLauncher (native + flatpak), MultiMC, PolyMC — same layout.
INSTANCE_ROOTS = [
    f"{HOME}/.local/share/PrismLauncher/instances",
    f"{HOME}/.var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher/instances",
    f"{HOME}/.local/share/multimc/instances",
    f"{HOME}/.local/share/multimc5/instances",
    f"{HOME}/.local/share/PolyMC/instances",
    f"{HOME}/.minecraft",                                       # vanilla
    f"{HOME}/.var/app/com.mojang.Minecraft/.minecraft",         # vanilla flatpak
]

# Subpaths under an instance (or under INSTANCE_ROOTS itself) that hold jars
MOD_SUBDIRS = ("minecraft/mods", ".minecraft/mods", "mods")

# Structural markers — presence of any of these means "this is a mod jar"
MOD_MARKERS = (
    "META-INF/mods.toml",              # Forge / NeoForge
    "META-INF/neoforge.mods.toml",     # NeoForge
    "fabric.mod.json",                 # Fabric
    "mcmod.info",                      # older Forge
)

_CACHE = None
_CACHE_TIME = 0.0
_CACHE_TTL = 60.0


def list_instance_mod_dirs():
    """Return every directory that could contain active mod jars."""
    dirs = []
    for root in INSTANCE_ROOTS:
        if not os.path.isdir(root):
            continue
        # Root itself might be a mods folder (e.g. ~/.minecraft/mods)
        for sub in MOD_SUBDIRS:
            p = os.path.join(root, sub)
            if os.path.isdir(p):
                dirs.append(p)
        # Or it may contain per-instance subdirectories
        try:
            for name in os.listdir(root):
                inst = os.path.join(root, name)
                if not os.path.isdir(inst):
                    continue
                for sub in MOD_SUBDIRS:
                    p = os.path.join(inst, sub)
                    if os.path.isdir(p):
                        dirs.append(p)
        except OSError:
            continue
    return dirs


def get_in_use_mods(force=False):
    """
    Return a set of (filename_lower, size) tuples for every mod jar
    installed in any known launcher instance.

    Also includes (filename_lower, -1) so a mod that's been byte-identical
    but re-exported (rare) still counts as "in use" by name alone.
    Cached for 60 seconds — enough for a single scan pass.
    """
    global _CACHE, _CACHE_TIME
    now = time.time()
    if not force and _CACHE is not None and (now - _CACHE_TIME) < _CACHE_TTL:
        return _CACHE

    in_use = set()
    for moddir in list_instance_mod_dirs():
        try:
            for fname in os.listdir(moddir):
                if not fname.lower().endswith(".jar"):
                    continue
                fp = os.path.join(moddir, fname)
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    size = -1
                in_use.add((fname.lower(), size))
                in_use.add((fname.lower(), -1))
        except OSError:
            continue

    _CACHE = in_use
    _CACHE_TIME = now
    return in_use


def has_any_instance():
    """True if this machine has at least one Minecraft instance."""
    return bool(list_instance_mod_dirs())


def is_minecraft_jar(path):
    """
    Structural check: does this .jar look like a Minecraft mod?
    We peek at the zip's file list — no decompression needed.
    """
    p = Path(path)
    if p.suffix.lower() != ".jar":
        return False
    try:
        with zipfile.ZipFile(str(p), "r") as z:
            names = set(z.namelist())
            return any(m in names for m in MOD_MARKERS)
    except (zipfile.BadZipFile, OSError, PermissionError):
        return False


def is_orphan_mod(path):
    """
    True if this is a Minecraft mod jar not loaded by any instance.
    Fails closed (returns False) if no instances exist to compare against.
    """
    if not is_minecraft_jar(path):
        return False
    if not has_any_instance():
        return False
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError:
        return False
    in_use = get_in_use_mods()
    name = p.name.lower()
    return (name, size) not in in_use and (name, -1) not in in_use


def orphan_summary(paths):
    """Return (orphans, safe_count, total_bytes) for a list of candidate paths."""
    orphans = []
    safe = 0
    total = 0
    for p in paths:
        pp = Path(p)
        if is_orphan_mod(pp):
            orphans.append(pp)
            try:
                total += pp.stat().st_size
            except OSError:
                pass
        else:
            safe += 1
    return orphans, safe, total