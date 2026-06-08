"""Тесты разграничения доступа к пространствам (access profiles)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confluence_mcp.config import Config, WILDCARD_SPACE, _load_access_profiles  # noqa: E402
from confluence_mcp import identity  # noqa: E402
from confluence_mcp import server  # noqa: E402


def make_config(profiles, default="guest", secret="sek"):
    return Config(
        base_url="x",
        username="u",
        api_token="t",
        app_secret=secret,
        default_profile=default,
        profiles=profiles,
    )


class TestAllowedSpacesFor(unittest.TestCase):
    def setUp(self):
        self.c = make_config({"guest": ["KB1C"], "support": ["KB1C", "DNBS"], "admin": [WILDCARD_SPACE]})

    def test_known_user(self):
        self.assertEqual(self.c.allowed_spaces_for("support"), ["KB1C", "DNBS"])

    def test_admin_wildcard(self):
        self.assertEqual(self.c.allowed_spaces_for("admin"), [WILDCARD_SPACE])

    def test_unknown_falls_back_to_default(self):
        self.assertEqual(self.c.allowed_spaces_for("nobody"), ["KB1C"])

    def test_empty_and_none(self):
        self.assertEqual(self.c.allowed_spaces_for(""), ["KB1C"])
        self.assertEqual(self.c.allowed_spaces_for(None), ["KB1C"])


class TestLoadAccessProfiles(unittest.TestCase):
    def setUp(self):
        self._orig_env = os.environ.get("ACCESS_PROFILES_PATH")

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("ACCESS_PROFILES_PATH", None)
        else:
            os.environ["ACCESS_PROFILES_PATH"] = self._orig_env

    def test_load_from_file(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "ap.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "app_secret": "S",
                    "default_profile": "guest",
                    "profiles": {"guest": {"spaces": ["KB1C"]}, "admin": {"spaces": ["*"]}},
                },
                fh,
            )
        os.environ["ACCESS_PROFILES_PATH"] = p
        secret, default, profiles = _load_access_profiles()
        self.assertEqual(secret, "S")
        self.assertEqual(default, "guest")
        self.assertEqual(profiles["guest"], ["KB1C"])
        self.assertEqual(profiles["admin"], ["*"])

    def test_fallback_when_missing(self):
        os.environ["ACCESS_PROFILES_PATH"] = os.path.join(tempfile.mkdtemp(), "nope.json")
        secret, default, profiles = _load_access_profiles()
        self.assertEqual(profiles, {"default": [WILDCARD_SPACE]})
        self.assertEqual(default, "default")

    def test_default_pointing_to_missing_profile_is_empty(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "ap.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"default_profile": "ghost", "profiles": {"guest": {"spaces": ["KB1C"]}}}, fh)
        os.environ["ACCESS_PROFILES_PATH"] = p
        _, default, profiles = _load_access_profiles()
        self.assertEqual(default, "ghost")
        self.assertEqual(profiles["ghost"], [])  # безопасный пустой доступ


class _IdentityTestBase(unittest.TestCase):
    """Подменяет глобальный _config в identity на тестовый и чистит contextvar."""

    profiles = {"guest": ["KB1C"], "support": ["KB1C", "DNBS"], "admin": [WILDCARD_SPACE]}
    default = "guest"
    secret = "S"

    def setUp(self):
        self._orig = identity._config
        identity._config = make_config(self.profiles, default=self.default, secret=self.secret)

    def tearDown(self):
        identity._config = self._orig
        identity.current_profile.set(None)


class TestResolveProfile(_IdentityTestBase):
    def test_correct_secret(self):
        self.assertEqual(identity.resolve_profile("admin", "S"), "admin")

    def test_wrong_secret_falls_back(self):
        self.assertEqual(identity.resolve_profile("admin", "bad"), "guest")

    def test_missing_secret_falls_back(self):
        self.assertEqual(identity.resolve_profile("admin", None), "guest")

    def test_unknown_user_falls_back(self):
        self.assertEqual(identity.resolve_profile("nobody", "S"), "guest")

    def test_empty_user_uses_default(self):
        self.assertEqual(identity.resolve_profile("", "S"), "guest")
        self.assertEqual(identity.resolve_profile(None, "S"), "guest")

    def test_secret_disabled_skips_check(self):
        identity._config = make_config(self.profiles, default="guest", secret="")
        self.assertEqual(identity.resolve_profile("admin", None), "admin")


class TestGetAllowedSpaces(_IdentityTestBase):
    def test_reads_from_contextvar(self):
        identity.current_profile.set("support")
        self.assertEqual(set(identity.get_allowed_spaces()), {"KB1C", "DNBS"})

    def test_none_uses_default(self):
        identity.current_profile.set(None)
        self.assertEqual(identity.get_allowed_spaces(), ["KB1C"])

    def test_has_full_access(self):
        identity.current_profile.set("admin")
        self.assertTrue(identity.has_full_access())
        identity.current_profile.set("guest")
        self.assertFalse(identity.has_full_access())


class TestSpaceFilterHelpers(_IdentityTestBase):
    def test_default_no_request_uses_all_allowed(self):
        identity.current_profile.set("support")
        eff, denied = server._resolve_space_filter(None, None)
        self.assertEqual(set(eff), {"KB1C", "DNBS"})
        self.assertFalse(denied)

    def test_request_narrows_within_allowed(self):
        identity.current_profile.set("support")
        eff, denied = server._resolve_space_filter(None, ["DNBS"])
        self.assertEqual(eff, ["DNBS"])
        self.assertFalse(denied)

    def test_request_only_forbidden_is_denied(self):
        identity.current_profile.set("guest")
        eff, denied = server._resolve_space_filter(None, ["DNBS"])
        self.assertEqual(eff, [])
        self.assertTrue(denied)

    def test_wildcard_passes_request_through(self):
        identity.current_profile.set("admin")
        eff, denied = server._resolve_space_filter(None, ["DNBS"])
        self.assertEqual(eff, ["DNBS"])
        self.assertFalse(denied)
        eff, denied = server._resolve_space_filter(None, None)
        self.assertIsNone(eff)
        self.assertFalse(denied)

    def test_filter_results_by_space(self):
        identity.current_profile.set("guest")
        res = [{"id": "1", "space": {"key": "KB1C"}}, {"id": "2", "space": {"key": "DNBS"}}]
        out = server._filter_results_by_space(res)
        self.assertEqual([r["id"] for r in out], ["1"])

    def test_filter_results_wildcard_keeps_all(self):
        identity.current_profile.set("admin")
        res = [{"id": "1", "space": {"key": "KB1C"}}, {"id": "2", "space": {"key": "DNBS"}}]
        self.assertEqual(server._filter_results_by_space(res), res)

    def test_space_allowed(self):
        identity.current_profile.set("support")
        self.assertTrue(server._space_allowed("DNBS"))
        self.assertFalse(server._space_allowed("SECRET"))
        self.assertFalse(server._space_allowed(None))

    def test_cql_space_keys_clause(self):
        self.assertEqual(server._cql_space_keys_clause(["A", "B"]), 'space in ("A", "B")')


class TestApplyCqlAccess(_IdentityTestBase):
    def test_limited_profile_wraps_cql(self):
        identity.current_profile.set("guest")
        cql, denied = server._apply_cql_access('text ~ "x"')
        self.assertFalse(denied)
        self.assertIn('space in ("KB1C")', cql)
        self.assertIn('(text ~ "x")', cql)

    def test_admin_does_not_wrap(self):
        identity.current_profile.set("admin")
        cql, denied = server._apply_cql_access('text ~ "x"')
        self.assertFalse(denied)
        self.assertEqual(cql, 'text ~ "x"')

    def test_empty_allowed_is_denied(self):
        identity._config = make_config({"guest": []}, default="guest", secret="S")
        identity.current_profile.set("guest")
        cql, denied = server._apply_cql_access('text ~ "x"')
        self.assertTrue(denied)
        self.assertIsNone(cql)


if __name__ == "__main__":
    unittest.main()
