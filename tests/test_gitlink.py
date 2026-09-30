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


class FakeGitLab:
    """Minimaler GitLab-Zustand: Admin `root`, Service Accounts, Keys, Tokens, Projekte, Meilensteine, Links."""

    ADMIN_TOKEN = "admin-secret"

    def __init__(self):
        self.users = {1: {"id": 1, "username": "root", "is_admin": True}}
        self.tokens = {self.ADMIN_TOKEN: {"id": 1, "user_id": 1, "name": "admin", "active": True}}
        self.keys, self.projects, self.members, self.milestones, self.links = {}, {}, {}, {}, {}
        self.groups = {"team": {"id": 50, "full_path": "team"}}
        self.next = 100

    def nid(self):
        self.next += 1
        return self.next

    def user_of(self, headers):
        tok = self.tokens.get(headers.get("PRIVATE-TOKEN"))
        return self.users[tok["user_id"]] if tok and tok["active"] else None

    def project(self, ident):
        if ident.isdigit():
            return self.projects.get(int(ident))
        return next((p for p in self.projects.values() if p["path_with_namespace"] == ident), None)

    def __call__(self, method, path, query, body, headers):
        if path == "/api/v4/version":
            return (200, {"version": "19.5.0", "revision": "x"}) if self.user_of(headers) else (401, {"message": "401 Unauthorized"})
        me = self.user_of(headers)
        if not me:
            return 401, {"message": "401 Unauthorized"}
        p = unquote(path[len("/api/v4"):])
        parts = [unquote(x) for x in path[len("/api/v4"):].strip("/").split("/")]
        if p == "/user":
            return 200, me
        if p == "/users" and method == "GET":
            return 200, [u for u in self.users.values() if u["username"] == query.get("username", [""])[0]]
        if p == "/service_accounts" and method == "POST":
            uid = self.nid()
            self.users[uid] = {"id": uid, "username": body["username"], "name": body["name"], "is_admin": False}
            return 201, self.users[uid]
        if parts[0] == "users" and parts[2:3] == ["keys"]:
            uid = int(parts[1])
            if method == "GET":
                return 200, [k for k in self.keys.values() if k["user_id"] == uid]
            if method == "POST":
                kid = self.nid()
                self.keys[kid] = {"id": kid, "user_id": uid, "title": body["title"], "key": body["key"] + " kommentar"}
                return 201, self.keys[kid]
            if method == "DELETE":
                return (204, None) if self.keys.pop(int(parts[3]), None) else (404, {"message": "404"})
        if parts[0] == "users" and parts[2:3] == ["personal_access_tokens"] and method == "POST":
            tid = self.nid()
            secret = f"tok-{tid}"
            self.tokens[secret] = {"id": tid, "user_id": int(parts[1]), "name": body["name"], "active": True,
                                   "expires_at": "2027-09-30"}
            return 201, {"id": tid, "name": body["name"], "token": secret, "expires_at": "2027-09-30"}
        if p == "/personal_access_tokens" and method == "GET":
            uid = int(query["user_id"][0])
            return 200, [{"id": v["id"], "name": v["name"]} for v in self.tokens.values() if v["user_id"] == uid and v["active"]]
        if parts[0] == "personal_access_tokens" and method == "DELETE":
            for v in self.tokens.values():
                if v["id"] == int(parts[1]):
                    v["active"] = False
                    return 204, None
            return 404, {"message": "404"}
        if p == "/groups" and method == "GET":
            return 200, list(self.groups.values())
        if parts[0] == "groups" and method == "GET":
            return 200, self.groups[parts[1]]
        if p == "/projects" and method == "GET":
            return 200, list(self.projects.values()) if query.get("page", ["1"])[0] == "1" else []
        if p == "/projects" and method == "POST":
            pid = self.nid()
            ns = next((g["full_path"] for g in self.groups.values() if g["id"] == body.get("namespace_id")), me["username"])
            self.projects[pid] = {"id": pid, "path_with_namespace": f"{ns}/{body['path']}", "visibility": body["visibility"],
                                  "web_url": f"http://gitlab/{ns}/{body['path']}", "archived": False,
                                  "ssh_url_to_repo": f"ssh://git@gitlab:2224/{ns}/{body['path']}.git", "marked": False}
            return 201, self.projects[pid]
        if parts[0] == "projects":
            proj = self.project(parts[1])
            if not proj:
                return 404, {"message": "404 Project Not Found"}
            rest = parts[2:]
            if not rest and method == "GET":
                return 200, proj
            if not rest and method == "DELETE":
                if "permanently_remove" in query:
                    del self.projects[proj["id"]]
                    return 202, {"message": "202 Accepted"}
                proj["marked"] = True
                return 202, {"message": "202 Accepted"}
            if rest in (["archive"], ["unarchive"]):
                proj["archived"] = rest == ["archive"]
                return 201, proj
            if rest == ["members"] and method == "POST":
                key = (proj["id"], body["user_id"])
                if key in self.members:
                    return 409, {"message": "Member already exists"}
                self.members[key] = body["access_level"]
                return 201, {"id": body["user_id"], "access_level": body["access_level"]}
            if rest[:1] == ["members"] and method == "PUT":
                self.members[(proj["id"], int(rest[1]))] = body["access_level"]
                return 200, {}
            if rest[:2] == ["members", "all"]:
                return (200, {"id": int(rest[2])}) if (proj["id"], int(rest[2])) in self.members else (404, {"message": "404"})
            if rest == ["milestones"] and method == "GET":
                return 200, [m for m in self.milestones.values() if m["project_id"] == proj["id"] and m["title"] == query.get("title", [None])[0]]
            if rest == ["milestones"] and method == "POST":
                mid = self.nid()
                self.milestones[mid] = {"id": mid, "title": body["title"], "project_id": proj["id"]}
                return 201, self.milestones[mid]
            if rest[:1] == ["issues"] and rest[2:3] == ["links"]:
                key = (proj["id"], int(rest[1]))
                if method == "GET":
                    return 200, self.links.get(key, [])
                if method == "POST":
                    link = {"iid": body["target_issue_iid"], "link_type": body["link_type"], "issue_link_id": self.nid()}
                    self.links.setdefault(key, []).append(link)
                    return 201, link
                if method == "DELETE":
                    self.links[key] = [x for x in self.links.get(key, []) if x["issue_link_id"] != int(rest[3])]
                    return 200, {}
        return 404, {"message": f"404 unbekannt {method} {p}"}


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


# --------------------------------------------------------------------------- GitLab-Adapter

class GitLabAdapter(SandboxHome):
    def setUp(self):
        super().setUp()
        self.gl = FakeGitLab()
        self.srv = FakeServer(self.gl)
        self.addCleanup(self.srv.close)
        self.cfg = {"url": self.srv.url, "platform": "gitlab", "instance": "gl", "client": "box", "ssh_port": 2224,
                    "ssh_alias": "gitlink-gl", "mcp_url": self.srv.url}
        original = gitlink.keyscan
        gitlink.keyscan = lambda host, name, port: ["ssh-ed25519 HOSTKEY"]
        self.addCleanup(setattr, gitlink, "keyscan", original)

    def store_admin_token(self):
        gitlink.write_private(gitlink.inst_dir("gl") / "admin-token", FakeGitLab.ADMIN_TOKEN + "\n")

    def test_missing_admin_token_names_path(self):
        with self.assertRaises(gitlink.Fail) as e:
            gitlink.adapter(self.cfg).__enter__()
        self.assertEqual(e.exception.code, "admin_token_required")
        self.assertTrue(e.exception.details["path"].endswith("/gl/admin-token"))

    def test_full_flow(self):
        self.store_admin_token()
        cfg = dict(self.cfg)
        with gitlink.adapter(cfg) as a:
            self.assertEqual(a.operator, "root")
            a.ensure_bot()
            a.ensure_bot()  # idempotent
            self.assertEqual(sum(u["username"] == gitlink.BOT for u in self.gl.users.values()), 1)
            gitlink.ensure_client_key(a, "gl", "box")
            gitlink.ensure_client_key(a, "gl", "box")
            self.assertEqual(len(a.bot_keys()), 1)
            expires = gitlink.ensure_client_token(a, "gl", cfg, "box")
            self.assertEqual(expires, "2027-09-30")
            self.assertIsNone(gitlink.ensure_client_token(a, "gl", cfg, "box"))  # gültig, bleibt
            self.assertEqual(a.bot_token_names(), ["gitlink-box"])
            self.assertEqual(a.owners(), ["team"])
            repo = a.create_repo("team", "demo", True)
            self.assertEqual(repo["path_with_namespace"], "team/demo")
            self.assertEqual(a.missing_repos(), ["team/demo"])
            a.grant("team/demo")
            a.grant("team/demo")  # 409 → PUT
            self.assertEqual(a.missing_repos(), [])
            self.assertEqual(self.gl.members[(repo["id"], a.bot_id())], gitlink.GITLAB_MAINTAINER)
            m1 = a.ensure_milestone("team/demo", "demo")
            self.assertEqual(a.ensure_milestone("team/demo", "demo"), m1)
            self.assertTrue(a.archive("team/demo", False))
            self.assertFalse(a.archive("team/demo", True))
            self.assertEqual(a.ssh_endpoint({}, self.srv.url)[1], 2224)
            self.assertEqual(a.board_url("team/demo"), f"{self.srv.url}/team/demo/-/boards")
            self.assertEqual(a.delete_repo("team/demo"), [])
            self.assertIsNone(a.get_repo("team/demo"))
        token = (gitlink.inst_dir("gl") / "token").read_text().strip()
        self.assertTrue(token.startswith("tok-"))

    def test_host_keys_scan_the_real_ssh_target(self):
        scanned = []
        gitlink.keyscan = lambda host, name, port: scanned.append((host.ssh_host, name, port)) or ["ssh-ed25519 K"]
        self.store_admin_token()
        with gitlink.adapter(dict(self.cfg)) as a:
            self.assertEqual(a.host_keys("gitlab.example.org", 22), ["ssh-ed25519 K"])
            self.assertEqual(len(a.warnings), 1)  # über das Netz: TOFU-Warnung
            self.assertIn("gitlab.example.org:22", a.warnings[0])
            a.host_keys("127.0.0.1", 2224)
            self.assertEqual(len(a.warnings), 1)  # Loopback: keine Warnung
        a = gitlink.adapter(dict(self.cfg, ssh_host="admin@forge"))
        a.host_keys("forge.example.org", 22)
        self.assertEqual(scanned, [(None, "gitlab.example.org", 22), (None, "127.0.0.1", 2224),
                                   ("admin@forge", "localhost", 22)])
        self.assertEqual(a.warnings, [])

    def test_ssh_endpoint_from_project_ssh_url(self):
        self.assertEqual(gitlink.parse_ssh_url("ssh://git@git.example.org:2224/g/p.git", "web"), ("git.example.org", 2224))
        self.assertEqual(gitlink.parse_ssh_url("ssh://git@git.example.org/g/p.git", "web"), ("git.example.org", 22))
        self.assertEqual(gitlink.parse_ssh_url("git@git.example.org:g/p.git", "web"), ("git.example.org", 22))
        self.assertEqual(gitlink.parse_ssh_url("", "web"), ("web", None))
        self.store_admin_token()
        cfg = dict(self.cfg)
        del cfg["ssh_port"]
        with gitlink.adapter(cfg) as a:
            self.assertEqual(a.ssh_endpoint({}, self.srv.url), ("127.0.0.1", 22))  # noch kein Projekt
            a.create_repo("root", "p", True)
            self.assertEqual(a.ssh_endpoint({}, self.srv.url), ("gitlab", 2224))

    def test_dependency_via_bot_token(self):
        self.store_admin_token()
        cfg = dict(self.cfg)
        with gitlink.adapter(cfg) as a:
            a.ensure_bot()
            gitlink.ensure_client_token(a, "gl", cfg, "box")
            a.create_repo("root", "p", False)
        api = gitlink.GitLab.bot_api(cfg, (gitlink.inst_dir("gl") / "token").read_text().strip())
        self.assertEqual(gitlink.GitLab.dependency(api, "root/p", 2, 1, False), [1])
        self.assertEqual(gitlink.GitLab.dependency(api, "root/p", 2, None, False), [1])
        self.assertEqual(gitlink.GitLab.dependency(api, "root/p", 2, 1, True), [])

    def test_revoke_via_cli(self):
        self.store_admin_token()
        cfg = dict(self.cfg)
        with gitlink.adapter(cfg) as a:
            a.ensure_bot()
            gitlink.ensure_client_key(a, "gl", "box")
            gitlink.ensure_client_token(a, "gl", cfg, "box")
        gitlink.save_config("gl", cfg)
        buf = io.StringIO()
        with redirect_stdout(buf):
            gitlink.main(["--lang", "de", "widerrufen"])
        out = json.loads(buf.getvalue())
        self.assertEqual((out["error"], out["details"]["clients"]), ("client_required", ["box"]))
        buf = io.StringIO()
        with redirect_stdout(buf):
            gitlink.main(["--lang", "de", "widerrufen", "--client", "box"])
        self.assertTrue(json.loads(buf.getvalue())["ok"])
        bot = next(u["id"] for u in self.gl.users.values() if u["username"] == gitlink.BOT)
        self.assertEqual([k for k in self.gl.keys.values() if k["user_id"] == bot], [])
        self.assertFalse(any(v["active"] for v in self.gl.tokens.values() if v["user_id"] == bot))


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
