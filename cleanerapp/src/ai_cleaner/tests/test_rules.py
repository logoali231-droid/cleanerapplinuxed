from ai_cleaner.rules import RulesManager


def _rule(**kw):
    d = {"type": "folder", "value": "/x", "action": "protect", "enabled": True}
    d.update(kw)
    return d


def test_match_folder():
    r = _rule(type="folder", value="/tmp/protected")
    assert RulesManager._matches(r, "/tmp/protected/a.txt")
    assert RulesManager._matches(r, "/tmp/protected/sub/deep.txt")
    assert not RulesManager._matches(r, "/tmp/protected2/a.txt")


def test_match_extension():
    r = _rule(type="extension", value=".deb")
    assert RulesManager._matches(r, "/x/y.deb")
    assert RulesManager._matches(r, "/x/y.DEB")
    assert not RulesManager._matches(r, "/x/y.zip")


def test_match_extension_adds_dot():
    r = _rule(type="extension", value="deb")
    assert RulesManager._matches(r, "/x/y.deb")


def test_match_name_contains():
    r = _rule(type="name_contains", value="backup")
    assert RulesManager._matches(r, "/x/my_backup_file.txt")
    assert RulesManager._matches(r, "/x/BACKUP.tar")
    assert not RulesManager._matches(r, "/x/normal.txt")


def test_match_glob():
    r = _rule(type="glob", value="*.bak")
    assert RulesManager._matches(r, "/x/y.bak")
    assert not RulesManager._matches(r, "/x/y.txt")


def test_match_disabled_rule():
    r = _rule(enabled=False)
    # _matches itself doesn't check enabled — the caller does.
    # But it should still return True for a matching path.
    assert RulesManager._matches(r, "/x/y")


def test_describe_keep():
    d = RulesManager.describe({"type": "folder", "value": "/x",
                               "action": "protect"})
    assert d.startswith("Keep")


def test_describe_flag():
    d = RulesManager.describe({"type": "extension", "value": ".deb",
                               "action": "flag"})
    assert "deleting" in d.lower()
