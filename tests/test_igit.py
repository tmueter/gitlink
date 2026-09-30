"""Unit-Tests für die Teile von igit.py, die ohne Docker und ohne Forgejo laufen."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill" / "igit"))
import igit  # noqa: E402


class SandboxHome(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name
        self.home = Path(self._tmp.name)

    def tearDown(self):
        os.environ["HOME"] = self._old_home
        self._tmp.cleanup()


class ReplaceBlock(unittest.TestCase):
    B, E = "# a begin", "# a end"

    def test_inserts_at_end(self):
        self.assertEqual(igit.replace_block("x\n", self.B, self.E, "# a begin\ny\n# a end\n"),
                         "x\n\n# a begin\ny\n# a end\n")

    def test_replaces_existing(self):
        text = "x\n# a begin\nalt\n# a end\nz\n"
        self.assertEqual(igit.replace_block(text, self.B, self.E, "# a begin\nneu\n# a end\n"),
                         "x\n# a begin\nneu\n# a end\nz\n")

    def test_removes_with_empty_block(self):
        self.assertEqual(igit.replace_block("x\n# a begin\nalt\n# a end\nz\n", self.B, self.E, ""), "x\nz\n")


class SshFiles(SandboxHome):
    def test_block_is_prepended_before_wildcard_and_idempotent(self):
        cfg = self.home / ".ssh" / "config"
        cfg.parent.mkdir()
        cfg.write_text("Host *\n    StrictHostKeyChecking no\n")
        for _ in range(2):
            igit.update_ssh_config("localhost-3000", "localhost", 2222, "/k/igit_localhost-3000")
        text = cfg.read_text()
        self.assertTrue(text.startswith("# igit:localhost-3000 begin\nHost igit-localhost-3000\n"))
        self.assertEqual(text.count("Host igit-localhost-3000"), 1)
        self.assertIn("HostKeyAlias igit-localhost-3000", text)
        self.assertTrue(text.rstrip().endswith("StrictHostKeyChecking no"))
        self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)
        igit.update_ssh_config("localhost-3000", "", 0, "", remove=True)
        self.assertEqual(cfg.read_text(), "Host *\n    StrictHostKeyChecking no\n")

    def test_known_hosts_replaces_only_own_alias(self):
        kh = self.home / ".ssh" / "known_hosts"
        kh.parent.mkdir()
        kh.write_text("other ssh-ed25519 AAA\nigit-x ssh-rsa OLD\n")
        igit.update_known_hosts("x", ["ssh-ed25519 NEW"])
        self.assertEqual(kh.read_text(), "other ssh-ed25519 AAA\nigit-x ssh-ed25519 NEW\n")
        igit.update_known_hosts("x", [], remove=True)
        self.assertEqual(kh.read_text(), "other ssh-ed25519 AAA\n")


class Config(SandboxHome):
    def test_pick_instance(self):
        with self.assertRaises(igit.Fail) as e:
            igit.pick_instance(None)
        self.assertEqual(e.exception.code, "no_instance")
        igit.save_config("a", {"url": "http://localhost:1"})
        self.assertEqual(igit.pick_instance(None)[0], "a")
        igit.save_config("b", {"url": "http://localhost:2"})
        with self.assertRaises(igit.Fail) as e:
            igit.pick_instance(None)
        self.assertEqual(e.exception.details["instances"], ["a", "b"])
        self.assertEqual((igit.inst_dir("a") / "config.json").stat().st_mode & 0o777, 0o600)


class McpRegistration(SandboxHome):
    GET_OUTPUT = ("forgejo-x:\n  Scope: User config (available in all your projects)\n  Status: ✔ Connected\n"
                  "  Type: stdio\n  Command: {cmd}\n  Args: {args}\n  Environment:\n")

    def fake_claude(self, get_code, get_stdout):
        calls = []

        def fake_run(cmd, check=True, **kw):
            calls.append(cmd[2])
            if cmd[2] == "get":
                return igit.subprocess.CompletedProcess(cmd, get_code, get_stdout, "")
            return igit.subprocess.CompletedProcess(cmd, 0, "", "")

        original = igit.run
        igit.run = fake_run
        self.addCleanup(setattr, igit, "run", original)
        return calls

    def test_unchanged_registration_is_left_alone(self):
        calls = self.fake_claude(0, self.GET_OUTPUT.format(cmd="/s/start-mcp", args=""))
        self.assertEqual(igit.register_mcp("x", "/s/start-mcp"), ("forgejo-x", False))
        self.assertEqual(calls, ["get"])

    def test_missing_or_different_registration_is_replaced(self):
        for code, out in ((1, ""), (0, self.GET_OUTPUT.format(cmd="/alt/start-mcp", args="")),
                          (0, self.GET_OUTPUT.format(cmd="/s/start-mcp", args="--x"))):
            calls = self.fake_claude(code, out)
            self.assertEqual(igit.register_mcp("x", "/s/start-mcp"), ("forgejo-x", True))
            self.assertEqual(calls, ["get", "remove", "add"])

    def test_starter_reports_change_only_when_content_differs(self):
        cfg = {"mcp_url": "http://localhost:3000"}
        self.assertTrue(igit.write_starter("x", cfg, "/bin/forgejo-mcp")[1])
        self.assertFalse(igit.write_starter("x", cfg, "/bin/forgejo-mcp")[1])
        self.assertTrue(igit.write_starter("x", cfg, "/opt/forgejo-mcp")[1])


class LocalDirBlockers(SandboxHome):
    REMOTE = "igit-x:dreamer/probe.git"

    def git(self, *args):
        igit.run(["git", "-C", str(self.dir), "-c", "user.name=t", "-c", "user.email=t@t"] + list(args))

    def setUp(self):
        super().setUp()
        self.dir = self.home / "probe"
        self.dir.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", self.REMOTE)

    def test_fresh_repo_with_only_igit_note_is_deletable(self):
        (self.dir / "CLAUDE.md").write_text("<!-- igit:begin -->\nHinweis\n<!-- igit:end -->\n")
        self.assertEqual(igit.local_dir_blockers(self.dir, self.REMOTE), [])

    def test_own_content_in_claude_md_blocks(self):
        (self.dir / "CLAUDE.md").write_text("Eigene Notiz\n<!-- igit:begin -->\nHinweis\n<!-- igit:end -->\n")
        self.assertEqual(igit.local_dir_blockers(self.dir, self.REMOTE), [igit.t("r_dirty")])

    def test_unpushed_commit_and_other_origin_block(self):
        (self.dir / "a.txt").write_text("x")
        self.git("add", "a.txt")
        self.git("commit", "-qm", "a")
        self.assertEqual(igit.local_dir_blockers(self.dir, "igit-x:dreamer/anders.git"),
                         [igit.t("r_other_origin"), igit.t("r_unpushed")])

    def test_non_git_directory_blocks(self):
        plain = self.home / "plain"
        plain.mkdir()
        self.assertEqual(igit.local_dir_blockers(plain, self.REMOTE), [igit.t("r_not_git")])


class Validation(unittest.TestCase):
    def test_names(self):
        self.assertEqual(igit.valid_name("localhost-3000"), "localhost-3000")
        for bad in ("", "Gross", "a b", "lauf-1", "-x"):
            with self.assertRaises(igit.Fail):
                igit.valid_name(bad)

    def test_transport(self):
        igit.check_transport("http://localhost:3000")
        igit.check_transport("http://127.0.0.1:3000")
        igit.check_transport("https://forge.example.org")
        with self.assertRaises(igit.Fail) as e:
            igit.check_transport("http://192.0.2.10:3000")
        self.assertEqual(e.exception.code, "insecure_url")

    def test_parse_ini_detects_empty_secret(self):
        ini = igit.parse_ini("[server]\nSSH_PORT = 2222\n[security]\nINSTALL_LOCK = true\nSECRET_KEY =\n")
        self.assertEqual(ini[("server", "SSH_PORT")], "2222")
        self.assertEqual(ini[("security", "SECRET_KEY")], "")


class Cli(SandboxHome):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = igit.main(list(argv))
        return code, json.loads(buf.getvalue())

    def test_german_and_english_names_and_messages(self):
        code, out = self.run_cli("--lang", "de", "widerrufen")
        self.assertEqual((code, out["error"]), (1, "no_instance"))
        self.assertIn("Keine eingerichtete Instanz", out["message"])
        code, out = self.run_cli("--lang", "en", "revoke")
        self.assertEqual(out["error"], "no_instance")
        self.assertIn("No set-up instance", out["message"])

    def test_every_message_has_both_languages(self):
        for key, texts in igit.MSG.items():
            self.assertEqual(set(texts), {"de", "en"}, key)

    def test_visibility_flags(self):
        p = igit.build_parser()
        self.assertTrue(p.parse_args(["repo", "--name", "x", "--privat"]).private)
        self.assertFalse(p.parse_args(["repo", "--name", "x", "--public"]).private)


if __name__ == "__main__":
    unittest.main()
