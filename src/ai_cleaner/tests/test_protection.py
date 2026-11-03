from ai_cleaner.protection import (
    sniff_file_kind, is_screenshot, in_pseudo_fs, in_system_path,
    expand_user_path,
)
from ai_cleaner.config import HOME


def test_sniff_empty(tmp_bytes):
    p = tmp_bytes("empty.dat", b"")
    kind, _ = sniff_file_kind(p)
    assert kind == "empty"


def test_sniff_elf(tmp_bytes):
    p = tmp_bytes("bin", b"\x7fELF" + b"\x00" * 1000)
    kind, _ = sniff_file_kind(p)
    assert kind == "binary-exec"


def test_sniff_deb(tmp_bytes):
    p = tmp_bytes("foo.deb", b"!<arch>\n" + b"\x00" * 1000)
    kind, _ = sniff_file_kind(p)
    assert kind == "binary-archive"


def test_sniff_shell_script(tmp_bytes):
    p = tmp_bytes("script.sh", b"#!/bin/bash\necho hi\n")
    kind, _ = sniff_file_kind(p)
    assert kind == "text-code"


def test_sniff_python(tmp_bytes):
    p = tmp_bytes("foo.py", b"import os\nprint(os.name)\n")
    kind, _ = sniff_file_kind(p)
    assert kind == "text-code"


def test_sniff_json(tmp_bytes):
    p = tmp_bytes("config.json", b'{"a": 1, "b": 2}')
    kind, _ = sniff_file_kind(p)
    assert kind == "text-config"


def test_sniff_png(tmp_bytes):
    p = tmp_bytes("x.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000)
    kind, _ = sniff_file_kind(p)
    assert kind == "binary-magic"


def test_sniff_ssh_key_is_critical(tmp_bytes):
    p = tmp_bytes("id_rsa", b"-----BEGIN RSA PRIVATE KEY-----\nxxxx\n")
    kind, _ = sniff_file_kind(p)
    assert kind == "critical"


def test_sniff_env_is_critical(tmp_bytes):
    p = tmp_bytes(".env", b"API_KEY=secret\n")
    kind, _ = sniff_file_kind(p)
    assert kind == "critical"


def test_sniff_office_doc(tmp_bytes):
    p = tmp_bytes("letter.docx", b"PK\x03\x04" + b"\x00" * 1000)
    kind, _ = sniff_file_kind(p)
    assert kind == "office-doc"


def test_sniff_odt(tmp_bytes):
    p = tmp_bytes("notes.odt", b"PK\x03\x04" + b"\x00" * 1000)
    kind, _ = sniff_file_kind(p)
    assert kind == "office-doc"


def test_screenshot_gnome_en():
    assert is_screenshot(
        "/home/u/Pictures/Screenshots/Screenshot from 2026-01-01 12-00-00.png")


def test_screenshot_gnome_pt():
    assert is_screenshot(
        "/home/u/Imagens/Screenshots/Captura de tela de 2026-01-01 12-00-00.png")


def test_screenshot_kde():
    assert is_screenshot("/x/Screenshot_20260101_120000.png")


def test_screenshot_not_an_image():
    assert not is_screenshot("/x/Screenshot from 2026-01-01.txt")


def test_screenshot_normal_image():
    assert not is_screenshot("/home/u/Documents/chart.png")


def test_in_pseudo_fs():
    assert in_pseudo_fs("/proc/1/status")
    assert in_pseudo_fs("/sys/kernel")
    assert in_pseudo_fs("/dev/sda")
    assert not in_pseudo_fs("/home/u/foo")


def test_in_system_path():
    assert in_system_path("/usr/bin/ls")
    assert in_system_path("/etc/passwd")
    assert not in_system_path("/home/u/foo")


def test_expand_user_path():
    import os
    assert expand_user_path("~") == HOME
    assert expand_user_path("~/foo") == os.path.join(HOME, "foo")
    assert expand_user_path("/abs/path") == "/abs/path"
