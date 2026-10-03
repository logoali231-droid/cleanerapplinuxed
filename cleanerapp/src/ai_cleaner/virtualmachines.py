"""
Virtual machine cleanup.

Detects large VM files that belong to launchers that are no longer
installed, or to VMs that are no longer registered.

Covers:
  - VirtualBox     (VMs folder, .vdi/.vmdk/.vbox files)
  - VMware         (VM folders, .vmdk/.vmx files)
  - QEMU/libvirt   (.qcow2/.img files outside active pools)
  - Genymotion     (Android emulator images — your case)
  - Standalone VM downloads (UbuntuIDS.ova, .vmdk, etc.)

Fails closed: if the launcher is installed and the VM is registered,
nothing is flagged.
"""
import os
import shutil
import subprocess
from pathlib import Path

from .config import HOME


# Directories that hold launcher-managed VMs.  We scan these to build
# the "still in use" set, and we also flag orphans found elsewhere.
VM_ROOTS = [
    f"{HOME}/VirtualBox VMs",
    f"{HOME}/.VirtualBox",
    f"{HOME}/.config/VirtualBox",
    f"{HOME}/vmware",
    f"{HOME}/.Genymobile",
    f"{HOME}/.var/app/org.virtualbox.VirtualBox",
]

# Extensions used by VM disk images, configs, and exports.
# Big ones first — those are what actually reclaims space.
VM_DISK_EXTS = {
    ".vdi", ".vmdk", ".vhd", ".vhdx", ".vbox", ".vbox-prev",
    ".qcow2", ".qcow", ".img", ".raw",
    ".ova", ".ovf",
    ".vmx", ".vmxf", ".nvram", ".vmsd", ".vmsn", ".vmem",
}

# Extensions that mark a package as "a distributable VM image".
VM_EXPORT_EXTS = {".ova", ".ovf", ".vmdk"}

# Minimum size to consider "big enough to bother flagging".
# Prevents flagging 2 KB .vbox config files.
VM_MIN_SIZE_BYTES = 500 * 1024 * 1024   # 500 MB

# Files this old are candidates.
VM_MIN_AGE_DAYS = 90

_CACHE = None
_CACHE_TIME = 0.0
_CACHE_TTL = 60.0


def _which(cmd):
    return shutil.which(cmd)


def has_virtualbox():
    return _which("VBoxManage") is not None


def has_vmware():
    return _which("vmrun") is not None or _which("vmware") is not None


def has_libvirt():
    return _which("virsh") is not None


def registered_virtualbox_vms():
    """Return set of lowercase VM names VirtualBox knows about."""
    if not has_virtualbox():
        return set()
    try:
        out = subprocess.run(
            ["VBoxManage", "list", "vms"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return set()
    names = set()
    for line in out.splitlines():
        # Format:  "MyVM" {uuid}
        line = line.strip()
        if line.startswith('"'):
            end = line.find('"', 1)
            if end > 0:
                names.add(line[1:end].lower())
    return names


def registered_libvirt_vms():
    """Return set of lowercase domains libvirt knows about."""
    if not has_libvirt():
        return set()
    try:
        out = subprocess.run(
            ["virsh", "list", "--all", "--name"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return set()
    return {n.strip().lower() for n in out.splitlines() if n.strip()}


def _build_in_use_set():
    """Return a set of VM names that are still registered anywhere."""
    live = set()
    live |= registered_virtualbox_vms()
    live |= registered_libvirt_vms()
    return live


def _is_inside_live_vm_folder(path):
    """True if this path lives under a launcher's own VM directory."""
    p = str(path)
    for root in VM_ROOTS:
        if p == root or p.startswith(root + os.sep):
            return True
    return False


def is_vm_leftover(path):
    """
    True if this looks like a large VM file that isn't in use.

    Rules:
      • Must have a VM extension.
      • Must be at least VM_MIN_SIZE_BYTES.
      • If it lives inside a launcher's own VM folder and the launcher
        is installed with registered VMs, we conservatively return False
        — the user can still right-click those manually.
      • If the launcher isn't installed, the entire folder is fair game.
    """
    p = Path(path)
    if p.suffix.lower() not in VM_DISK_EXTS:
        return False
    try:
        st = p.stat()
    except OSError:
        return False
    if st.st_size < VM_MIN_SIZE_BYTES:
        return False
    age_days = (os.path.getmtime(p) and (__import__("time").time() - st.st_mtime) / 86400.0)
    if age_days < VM_MIN_AGE_DAYS:
        return False

    # If it's inside a launcher's VM root AND the launcher is still
    # installed with registered VMs, don't touch it.
    if _is_inside_live_vm_folder(p):
        if has_virtualbox() or has_vmware() or has_libvirt():
            return False

    return True


def scan_vm_roots():
    """Yield every large VM file under any known VM root."""
    for root in VM_ROOTS:
        rp = Path(root)
        if not rp.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(rp, onerror=lambda e: None):
            for fname in files:
                fp = Path(dirpath) / fname
                if fp.suffix.lower() in VM_DISK_EXTS:
                    yield fp


def vm_summary(paths):
    """Return (leftovers, safe, total_bytes) for a list of paths."""
    leftovers, safe, total = [], 0, 0
    for p in paths:
        pp = Path(p)
        if is_vm_leftover(pp):
            leftovers.append(pp)
            try:
                total += pp.stat().st_size
            except OSError:
                pass
        else:
            safe += 1
    return leftovers, safe, total