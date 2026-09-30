"""Unit-Tests für gitlink.py. Laufen ohne Docker und ohne echte Forge.

GitLab wird durch einen nachgebauten API-Server im Prozess ersetzt; er bildet nur die Endpunkte ab,
die der Adapter nutzt, im Format der GitLab-Dokumentation.
"""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill" / "gitlink"))
import gitlink  # noqa: E402


class SandboxHome(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name
        self.home = Path(self._tmp.name)

    def tearDown(self):
        os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def git(self, workdir, *args):
        gitlink.run(["git", "-C", str(workdir), "-c", "user.name=t", "-c", "user.email=t@t"] + list(args))


# --------------------------------------------------------------------------- nachgebaute Server

class FakeServer:
    """Startet einen HTTP-Server im Prozess; `routes` bildet (METHODE, Pfad) auf eine Funktion ab."""

    def __init__(self, handler):
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _do(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                u = urlparse(self.path)
                status, payload = handler(self.command, u.path, parse_qs(u.query), body, self.headers)
                raw = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _do

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        outer.calls = []

    def close(self):
        self.server.shutdown()
        self.server.server_close()


# --------------------------------------------------------------------------- Kern

class ReplaceBlock(unittest.TestCase):
    B, E = "# a begin", "# a end"

    def test_inserts_at_end(self):
        self.assertEqual(gitlink.replace_block("x\n", self.B, self.E, "# a begin\ny\n# a end\n"),
                         "x\n\n# a begin\ny\n# a end\n")

    def test_replaces_existing(self):
        self.assertEqual(gitlink.replace_block("x\n# a begin\nalt\n# a end\nz\n", self.B, self.E, "# a begin\nneu\n# a end\n"),
                         "x\n# a begin\nneu\n# a end\nz\n")

    def test_removes_with_empty_block(self):
        self.assertEqual(gitlink.replace_block("x\n# a begin\nalt\n# a end\nz\n", self.B, self.E, ""), "x\nz\n")


class SshFiles(SandboxHome):
    def test_block_is_prepended_before_wildcard_and_idempotent(self):
        cfg = self.home / ".ssh" / "config"
        cfg.parent.mkdir()
        cfg.write_text("Host *\n    StrictHostKeyChecking no\n")
        for _ in range(2):
            gitlink.update_ssh_config("localhost-3000", "localhost", 2222, "/k/gitlink_localhost-3000")
        text = cfg.read_text()
        self.assertTrue(text.startswith("# gitlink:localhost-3000 begin\nHost gitlink-localhost-3000\n"))
        self.assertEqual(text.count("Host gitlink-localhost-3000"), 1)
        self.assertIn("HostKeyAlias gitlink-localhost-3000", text)
        self.assertTrue(text.rstrip().endswith("StrictHostKeyChecking no"))
        self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)
        gitlink.update_ssh_config("localhost-3000", "", 0, "", remove=True)
        self.assertEqual(cfg.read_text(), "Host *\n    StrictHostKeyChecking no\n")

    def test_known_hosts_replaces_only_own_alias(self):
        kh = self.home / ".ssh" / "known_hosts"
        kh.parent.mkdir()
        kh.write_text("other ssh-ed25519 AAA\ngitlink-x ssh-rsa OLD\n")
        gitlink.update_known_hosts("x", ["ssh-ed25519 NEW"])
        self.assertEqual(kh.read_text(), "other ssh-ed25519 AAA\ngitlink-x ssh-ed25519 NEW\n")
        gitlink.update_known_hosts("x", [], remove=True)
        self.assertEqual(kh.read_text(), "other ssh-ed25519 AAA\n")


class Config(SandboxHome):
    def test_pick_instance(self):
        with self.assertRaises(gitlink.Fail) as e:
            gitlink.pick_instance(None)
        self.assertEqual(e.exception.code, "no_instance")
        gitlink.save_config("a", {"url": "http://localhost:1"})
        self.assertEqual(gitlink.pick_instance(None)[0], "a")
        gitlink.save_config("b", {"url": "http://localhost:2"})
        with self.assertRaises(gitlink.Fail) as e:
            gitlink.pick_instance(None)
        self.assertEqual(e.exception.details["instances"], ["a", "b"])
        self.assertEqual((gitlink.inst_dir("a") / "config.json").stat().st_mode & 0o777, 0o600)


class McpRegistration(SandboxHome):
    GET_OUTPUT = ("gitlink-x:\n  Scope: User config (available in all your projects)\n  Status: ✔ Connected\n"
                  "  Type: stdio\n  Command: {cmd}\n  Args: {args}\n  Environment:\n")

    def fake_claude(self, get_code, get_stdout):
        calls = []

        def fake_run(cmd, check=True, **kw):
            calls.append(cmd[2])
            code = get_code if cmd[2] == "get" else 0
            return gitlink.subprocess.CompletedProcess(cmd, code, get_stdout if cmd[2] == "get" else "", "")

        original = gitlink.run
        gitlink.run = fake_run
        self.addCleanup(setattr, gitlink, "run", original)
        return calls

    def test_unchanged_registration_is_left_alone(self):
        calls = self.fake_claude(0, self.GET_OUTPUT.format(cmd="/s/start-mcp", args=""))
        self.assertEqual(gitlink.register_mcp("gitlink-x", "/s/start-mcp"), ("gitlink-x", False))
        self.assertEqual(calls, ["get"])

    def test_missing_or_different_registration_is_replaced(self):
        for code, out in ((1, ""), (0, self.GET_OUTPUT.format(cmd="/alt/start-mcp", args="")),
                          (0, self.GET_OUTPUT.format(cmd="/s/start-mcp", args="--x"))):
            calls = self.fake_claude(code, out)
            self.assertEqual(gitlink.register_mcp("gitlink-x", "/s/start-mcp"), ("gitlink-x", True))
            self.assertEqual(calls, ["get", "remove", "add"])

    def test_starter_reports_change_only_when_content_differs(self):
        cfg = {"mcp_url": "http://localhost:3000"}
        self.assertTrue(gitlink.write_starter("x", cfg, "exec /bin/a")[1])
        self.assertFalse(gitlink.write_starter("x", cfg, "exec /bin/a")[1])
        self.assertTrue(gitlink.write_starter("x", cfg, "exec /bin/b")[1])


class LocalDirBlockers(SandboxHome):
    REMOTE = "gitlink-x:dreamer/probe.git"

    def setUp(self):
        super().setUp()
        self.dir = self.home / "probe"
        self.dir.mkdir()
        self.git(self.dir, "init", "-q", "-b", "main")
        self.git(self.dir, "remote", "add", "origin", self.REMOTE)

    def test_fresh_repo_with_only_note_is_deletable(self):
        for begin, end in ((gitlink.MD_BEGIN, gitlink.MD_END), gitlink.LEGACY_MD):
            (self.dir / "CLAUDE.md").write_text(f"{begin}\nHinweis\n{end}\n")
            self.assertEqual(gitlink.local_dir_blockers(self.dir, self.REMOTE), [])

    def test_own_content_in_claude_md_blocks(self):
        (self.dir / "CLAUDE.md").write_text(f"Eigene Notiz\n{gitlink.MD_BEGIN}\nHinweis\n{gitlink.MD_END}\n")
        self.assertEqual(gitlink.local_dir_blockers(self.dir, self.REMOTE), [gitlink.t("r_dirty")])

    def test_unpushed_commit_and_other_origin_block(self):
        (self.dir / "a.txt").write_text("x")
        self.git(self.dir, "add", "a.txt")
        self.git(self.dir, "commit", "-qm", "a")
        self.assertEqual(gitlink.local_dir_blockers(self.dir, "gitlink-x:dreamer/anders.git"),
                         [gitlink.t("r_other_origin"), gitlink.t("r_unpushed")])

    def test_non_git_directory_blocks(self):
        plain = self.home / "plain"
        plain.mkdir()
        self.assertEqual(gitlink.local_dir_blockers(plain, self.REMOTE), [gitlink.t("r_not_git")])


class Validation(unittest.TestCase):
    def test_names(self):
        self.assertEqual(gitlink.valid_name("localhost-3000"), "localhost-3000")
        for bad in ("", "Gross", "a b", "lauf-1", "-x"):
            with self.assertRaises(gitlink.Fail):
                gitlink.valid_name(bad)

    def test_transport(self):
        gitlink.check_transport("http://localhost:3000")
        gitlink.check_transport("https://forge.example.org")
        with self.assertRaises(gitlink.Fail) as e:
            gitlink.check_transport("http://192.0.2.10:3000")
        self.assertEqual(e.exception.code, "insecure_url")

    def test_parse_ini_detects_empty_secret(self):
        ini = gitlink.parse_ini("[server]\nSSH_PORT = 2222\n[security]\nSECRET_KEY =\n")
        self.assertEqual(ini[("server", "SSH_PORT")], "2222")
        self.assertEqual(ini[("security", "SECRET_KEY")], "")

    def test_client_of_ignores_run_tokens_and_knows_legacy_names(self):
        self.assertEqual(gitlink.client_of("gitlink-box"), "box")
        self.assertEqual(gitlink.client_of("igit-box"), "box")
        self.assertIsNone(gitlink.client_of("gitlink-lauf-20260930-ab12"))
        self.assertIsNone(gitlink.client_of("igit-lauf-20260930-ab12"))
        self.assertIsNone(gitlink.client_of("anderer-token"))


class Cli(SandboxHome):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gitlink.main(list(argv))
        return code, json.loads(buf.getvalue())

    def test_german_and_english_names_and_messages(self):
        code, out = self.run_cli("--lang", "de", "widerrufen")
        self.assertEqual((code, out["error"]), (1, "no_instance"))
        self.assertIn("Keine eingerichtete Instanz", out["message"])
        code, out = self.run_cli("--lang", "en", "revoke")
        self.assertIn("No set-up instance", out["message"])

    def test_every_message_has_both_languages(self):
        for key, texts in gitlink.MSG.items():
            self.assertEqual(set(texts), {"de", "en"}, key)

    def test_parser_flags(self):
        p = gitlink.build_parser()
        self.assertTrue(p.parse_args(["repo", "--name", "x", "--privat"]).private)
        self.assertFalse(p.parse_args(["repo", "--name", "x", "--public"]).private)
        a = p.parse_args(["abhaengigkeit", "--repo", "o/r", "--issue", "5", "--blockiert-durch", "3"])
        self.assertEqual((a.issue, a.blocker, a.remove), (5, 3, False))
        a = p.parse_args(["dependency", "--repo", "o/r", "--issue", "5", "--blocked-by", "3", "--remove"])
        self.assertTrue(a.remove)


# --------------------------------------------------------------------------- Plattform-Erkennung

class Detection(unittest.TestCase):
    def serve(self, table):
        srv = FakeServer(lambda m, path, q, b, h: table.get(path, (404, {"message": "404 Not Found"})))
        self.addCleanup(srv.close)
        return srv.url

    def test_auth_proxy_redirect_is_reported_not_parsed(self):
        login = self.serve({})  # steht für login.microsoftonline.com

        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", login + "/oauth2/authorize")
                self.end_headers()

        from http.server import ThreadingHTTPServer as S
        srv = S(("127.0.0.1", 0), Redirect)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        url = f"http://localhost:{srv.server_address[1]}"
        with self.assertRaises(gitlink.Fail) as e:
            gitlink.detect_platform(url)
        self.assertEqual(e.exception.code, "auth_proxy")
        self.assertEqual(e.exception.details["redirect_host"], "127.0.0.1")
        with self.assertRaises(gitlink.Fail) as e:
            gitlink.Api(url, ("private", "t"), "/api/v4").call("GET", "/user")
        self.assertEqual(e.exception.code, "auth_proxy")

    def test_connect_on_forgejo_grants_bot_first(self):
        calls = []

        class FakeAdapter:
            warnings = []

            def __enter__(self):
                return self

            def __exit__(self, *e):
                pass

            def get_repo(self, full):
                calls.append(("get", full))
                return {"full_name": full}

            def grant(self, full):
                calls.append(("grant", full))

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_home = os.environ["HOME"]
        os.environ["HOME"] = tmp.name
        self.addCleanup(os.environ.__setitem__, "HOME", old_home)
        for name, fn in {"adapter": lambda cfg, op=None: FakeAdapter(),
                         "remote_access": lambda remote: (("grant", "d/r") in calls, "denied")}.items():
            self.addCleanup(setattr, gitlink, name, getattr(gitlink, name))
            setattr(gitlink, name, fn)
        gitlink.save_config("fj", {"url": "http://localhost:3000", "platform": "forgejo", "ssh_alias": "gitlink-fj"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            gitlink.main(["--lang", "de", "verbinden", "--repo", "d/r", "--dir", str(Path(tmp.name) / "w")])
        out = json.loads(buf.getvalue())
        self.assertTrue(out["result"]["bot_granted"])
        self.assertEqual(calls, [("get", "d/r"), ("grant", "d/r")])

    def test_forgejo_gitea_gitlab_and_unknown(self):
        forgejo = self.serve({"/api/forgejo/v1/version": (200, {"version": "16.0.5+gitea-1.22.0"}),
                              "/api/v1/version": (200, {"version": "16.0.5+gitea-1.22.0"})})
        gitea = self.serve({"/api/v1/version": (200, {"version": "28.0.0"})})
        gitlab = self.serve({"/api/v4/version": (401, {"message": "401 Unauthorized"})})
        other = self.serve({})
        self.assertEqual(gitlink.detect_platform(forgejo), ("forgejo", "16.0.5+gitea-1.22.0"))
        self.assertEqual(gitlink.detect_platform(gitea), ("gitea", "28.0.0"))
        self.assertEqual(gitlink.detect_platform(gitlab), ("gitlab", None))
        self.assertEqual(gitlink.detect_platform(other), (None, None))


class InternalCa(SandboxHome):
    """HTTPS mit einem Zertifikat einer eigenen Zertifizierungsstelle, wie bei einer Firmen-PKI."""

    def make_pki(self):
        d = self.home / "pki"
        d.mkdir()
        o = ["openssl"]
        gitlink.run(o + ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=Test Root CA",
                         "-keyout", str(d / "ca.key"), "-out", str(d / "ca.pem")])
        gitlink.run(o + ["req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost",
                         "-keyout", str(d / "srv.key"), "-out", str(d / "srv.csr")])
        (d / "ext").write_text("subjectAltName=DNS:localhost\n")
        gitlink.run(o + ["x509", "-req", "-in", str(d / "srv.csr"), "-CA", str(d / "ca.pem"), "-CAkey", str(d / "ca.key"),
                         "-CAcreateserial", "-days", "2", "-extfile", str(d / "ext"), "-out", str(d / "srv.pem")])
        return d

    def test_ca_cert_makes_internal_https_trusted(self):
        import ssl
        d = self.make_pki()
        srv = FakeServer(lambda m, path, q, b, h: (401, {"message": "401 Unauthorized"}) if path == "/api/v4/version"
                         else (404, {"message": "404"}))
        self.addCleanup(srv.close)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(d / "srv.pem"), str(d / "srv.key"))
        srv.server.socket = ctx.wrap_socket(srv.server.socket, server_side=True)
        url = srv.url.replace("http://127.0.0.1", "https://localhost")
        self.addCleanup(gitlink.use_ca, None)
        gitlink.use_ca(None)
        self.assertEqual(gitlink.detect_platform(url), (None, None))  # unbekannte Stelle: kein Vertrauen
        gitlink.use_ca(d / "ca.pem")
        self.assertEqual(gitlink.detect_platform(url), ("gitlab", None))

    def test_starter_exports_ca_for_mcp_servers(self):
        path, _ = gitlink.write_starter("x", {"mcp_url": "https://g", "ca_cert": "/c/ca.pem"}, "exec /bin/a")
        self.assertIn("export NODE_EXTRA_CA_CERTS=/c/ca.pem SSL_CERT_FILE=/c/ca.pem\n", path.read_text())


# --------------------------------------------------------------------------- GitLab-Adapter

class GitLabAccount(SandboxHome):
    """GitLab ohne Token: nur SSH-Schlüssel, Host-Key und Alias für das Konto des Betreibers."""

    def setUp(self):
        super().setUp()
        self.user = None
        self.scans = []
        patches = {"keyscan": lambda host, name, port: self.scans.append((name, port)) or ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"],
                   "gitlab_ssh_user": lambda a, h, p: self.user,
                   "remote_access": lambda remote: (self.user is not None, "denied")}
        for name, fn in patches.items():
            self.addCleanup(setattr, gitlink, name, getattr(gitlink, name))
            setattr(gitlink, name, fn)

    def cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            gitlink.main(["--lang", "de"] + list(argv))
        return json.loads(buf.getvalue())

    def setup(self):
        return self.cli("einrichten", "--url", "https://gitlab.example.org", "--plattform", "gitlab",
                        "--ssh-hostname", "10.0.0.5", "--client", "box")

    def test_setup_asks_for_key_then_confirms_account(self):
        out = self.setup()
        self.assertEqual(out["error"], "ssh_key_required")
        d = out["details"]
        self.assertEqual(d["add_key_url"], "https://gitlab.example.org/-/user_settings/ssh_keys")
        self.assertEqual(d["title"], "gitlink-box")
        self.assertTrue(d["public_key"].startswith("ssh-ed25519 "))
        self.assertTrue(d["host_key_fingerprints"][0].startswith("SHA256:"))
        self.assertEqual(self.scans, [("10.0.0.5", 22)])
        conf = (self.home / ".ssh" / "config").read_text()
        self.assertIn("HostName 10.0.0.5", conf)
        self.user = "tmueter"
        out = self.setup()
        self.assertTrue(out["ok"])
        self.assertEqual((out["result"]["account"], out["result"]["mode"]), ("tmueter", "konto"))
        self.assertEqual(self.scans, [("10.0.0.5", 22)])  # Host-Key bleibt gepinnt, kein zweiter Scan
        self.cli("einrichten", "--url", "https://gitlab.example.org", "--plattform", "gitlab",
                 "--ssh-hostname", "10.0.0.5", "--ssh-port", "10022", "--client", "box")
        self.assertEqual(self.scans, [("10.0.0.5", 22), ("10.0.0.5", 10022)])  # neuer Port: neu pinnen
        self.assertFalse((gitlink.inst_dir("gitlab-example-org-443") / "token").exists())  # kein Token

    def test_connect_writes_commit_rule_and_origin(self):
        self.user = "tmueter"
        self.setup()
        work = self.home / "work"
        out = self.cli("verbinden", "--repo", "team/app", "--dir", str(work))
        self.assertTrue(out["ok"])
        self.assertEqual(gitlink.run(["git", "-C", str(work), "remote", "get-url", "origin"]).stdout.strip(),
                         "gitlink-gitlab-example-org-443:team/app.git")
        md = (work / "CLAUDE.md").read_text()
        self.assertIn("nur auf ausdrückliche Anforderung", md)
        self.assertIn("@tmueter", md)

    def test_discover_lists_configured_gitlab_even_without_http(self):
        self.user = "tmueter"
        self.setup()
        out = self.cli("finden", "--dir", str(self.home))
        gl = [i for i in out["result"]["instances"] if i.get("instance") == "gitlab-example-org-443"]
        self.assertEqual((gl[0]["platform"], gl[0]["http_detected"]), ("gitlab", False))

    def test_overview_offers_only_possible_commands(self):
        self.user = "tmueter"
        self.setup()
        gitlink.save_config("fj", {"url": "http://localhost:3000", "platform": "forgejo", "operator": "dreamer"})
        subcommands = set(gitlink.build_parser()._subparsers._group_actions[0].choices)
        for lang in ("de", "en"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                gitlink.main(["--lang", lang, "uebersicht"])
            res = json.loads(buf.getvalue())["result"]
            by = {i["instance"]: [c["command"] for c in i["commands"]] for i in res["instances"]}
            self.assertEqual(len(by["gitlab-example-org-443"]), 3)
            self.assertEqual(len(by["fj"]), 8)
            for cmds in by.values():
                self.assertTrue(set(cmds) <= subcommands, cmds)
            self.assertTrue(all(c["description"] for i in res["instances"] for c in i["commands"]))

    def test_gitlab_accepts_plain_http_url_because_no_token_is_sent(self):
        out = self.cli("einrichten", "--url", "http://gitlab.intern.example", "--plattform", "gitlab",
                       "--ssh-hostname", "10.0.0.5", "--client", "box")
        self.assertEqual(out["error"], "ssh_key_required")  # nicht insecure_url

    def test_connect_without_access_fails_clearly(self):
        self.user = "tmueter"
        self.setup()
        self.user = None
        out = self.cli("verbinden", "--repo", "team/app", "--dir", str(self.home / "w"))
        self.assertEqual(out["error"], "repo_no_access")

    def test_other_commands_are_refused_and_revoke_is_local(self):
        self.user = "tmueter"
        self.setup()
        for argv in (["repo", "--name", "x", "--privat"], ["archivieren", "--repo", "a/b"], ["freigeben", "a/b"],
                     ["abhaengigkeit", "--repo", "a/b", "--issue", "1"]):
            self.assertEqual(self.cli(*argv)["error"], "gitlab_unsupported", argv)
        out = self.cli("widerrufen", "--client", "box", "--lokal")
        self.assertTrue(out["ok"])
        self.assertIn("/-/user_settings/ssh_keys", out["warnings"][-1])
        self.assertFalse((self.home / ".ssh" / "gitlink_gitlab-example-org-443").exists())


# --------------------------------------------------------------------------- Migration

class Migration(SandboxHome):
    def test_legacy_setup_is_moved_and_relinked(self):
        old = self.home / ".config" / "igit"
        (old / "localhost-3000").mkdir(parents=True)
        (old / "forgejo-token").write_text("fremde Datei\n")
        cfg = {"url": "http://localhost:3000", "client": "box", "ssh_alias": "igit-localhost-3000",
               "ssh_hostname": "localhost", "ssh_port": 2222, "mcp_url": "http://localhost:3000"}
        (old / "localhost-3000" / "config.json").write_text(json.dumps(cfg))
        (old / "localhost-3000" / "token").write_text("t\n")
        ssh = self.home / ".ssh"
        ssh.mkdir()
        (ssh / "igit_localhost-3000").write_text("priv")
        (ssh / "igit_localhost-3000.pub").write_text("ssh-ed25519 AAA c")
        (ssh / "known_hosts").write_text("other k\nigit-localhost-3000 ssh-ed25519 HOST\n")
        gitlink.update_ssh_config("localhost-3000", "localhost", 2222, str(ssh / "igit_localhost-3000"), name="igit")
        work = self.home / "work"
        work.mkdir()
        self.git(work, "init", "-q", "-b", "main")
        self.git(work, "remote", "add", "origin", "igit-localhost-3000:dreamer/igit.git")
        (work / "CLAUDE.md").write_text("Oben\n<!-- igit:begin -->\nMCP-Server `igit-localhost-3000`\n<!-- igit:end -->\n")
        cwd = os.getcwd()
        os.chdir(work)
        try:
            notes = gitlink.migrate_legacy()
            self.assertEqual(gitlink.migrate_legacy(), [])  # idempotent
        finally:
            os.chdir(cwd)
        self.assertEqual(len(notes), 3)
        new = gitlink.load_config("localhost-3000")
        self.assertEqual((new["platform"], new["ssh_alias"], new["token_name"]), ("forgejo", "gitlink-localhost-3000", "igit-box"))
        self.assertEqual((old / "forgejo-token").read_text(), "fremde Datei\n")  # fremde Dateien bleiben
        self.assertTrue((ssh / "gitlink_localhost-3000").exists())
        self.assertFalse((ssh / "igit_localhost-3000").exists())
        self.assertEqual((ssh / "known_hosts").read_text(), "other k\ngitlink-localhost-3000 ssh-ed25519 HOST\n")
        conf = (ssh / "config").read_text()
        self.assertNotIn("igit", conf)
        self.assertIn("Host gitlink-localhost-3000", conf)
        self.assertEqual(gitlink.run(["git", "-C", str(work), "remote", "get-url", "origin"]).stdout.strip(),
                         "gitlink-localhost-3000:dreamer/igit.git")
        self.assertEqual((work / "CLAUDE.md").read_text(),
                         "Oben\n<!-- gitlink:begin -->\nMCP-Server `gitlink-localhost-3000`\n<!-- gitlink:end -->\n")


if __name__ == "__main__":
    unittest.main()
