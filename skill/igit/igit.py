#!/usr/bin/env python3
"""igit: deterministischer Teil des Skills `igit` (Ersteinrichtung Forgejo + Claude).

Jeder Unterbefehl gibt genau ein JSON-Objekt auf stdout aus:
  {"ok": true,  "result": {...}, "warnings": [...]}
  {"ok": false, "error": "<code>", "message": "<text>", "details": {...}}
Fortschrittsmeldungen gehen nach stderr. Geheimnisse erscheinen nie in der Ausgabe.

Spezifikation: docs/spec-igit-skill.md
"""
import argparse
import hashlib
import io
import ipaddress
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BOT = "claude-bot"
BOT_FULLNAME = "Claude (Bot)"
RUN_TOKEN_PREFIX = "igit-lauf-"
CLIENT_TOKEN_PREFIX = "igit-"
CLIENT_SCOPES = ["write:repository", "write:issue", "read:user"]
ADMIN_SCOPES = "write:admin,write:repository,write:user,write:issue,write:organization"
FORGEJO_IMAGE = "codeberg.org/forgejo/forgejo:16"
MCP_RELEASES = "https://git.b4mad.industries/api/v1/repos/agentic-forges/forgejo-mcp/releases/latest"
HOSTKEY_TYPES = ("ed25519", "ecdsa", "rsa")

LANG = "de"

MSG = {
    "no_docker": {
        "de": "Docker ist nicht erreichbar (weder direkt noch per `sudo -n`).",
        "en": "Docker is not reachable (neither directly nor via `sudo -n`).",
    },
    "no_compose": {
        "de": "Weder `docker compose` noch `docker-compose` ist verfügbar.",
        "en": "Neither `docker compose` nor `docker-compose` is available.",
    },
    "port_busy": {
        "de": "Port {port} ist belegt. Freie Vorschläge: {free}.",
        "en": "Port {port} is in use. Free suggestions: {free}.",
    },
    "dir_exists": {
        "de": "Das Verzeichnis {dir} enthält bereits eine Installation.",
        "en": "The directory {dir} already contains an installation.",
    },
    "container_exists": {
        "de": "Ein Container namens {name} existiert bereits.",
        "en": "A container named {name} already exists.",
    },
    "start_timeout": {
        "de": "Forgejo ist nach {sec} Sekunden unter {url} nicht erreichbar.",
        "en": "Forgejo is not reachable at {url} after {sec} seconds.",
    },
    "not_forgejo": {
        "de": "Unter {url} antwortet keine Forgejo-Instanz.",
        "en": "No Forgejo instance answers at {url}.",
    },
    "insecure_url": {
        "de": "{url} ist unverschlüsseltes HTTP und nicht Loopback. Tokens gehen so nicht über das Netz; `--ssh-host` (Tunnel) oder HTTPS verwenden.",
        "en": "{url} is plain HTTP and not loopback. Tokens will not be sent that way; use `--ssh-host` (tunnel) or HTTPS.",
    },
    "no_admin_access": {
        "de": "Kein Admin-Zugang zur Instanz gefunden: kein passender Forgejo-Container. Mit `--container` oder `--admin-exec` angeben.",
        "en": "No admin access to the instance found: no matching Forgejo container. Specify `--container` or `--admin-exec`.",
    },
    "operator_ambiguous": {
        "de": "Mehrere Admin-Konten gefunden: {admins}. Mit `--operator` wählen.",
        "en": "Several admin accounts found: {admins}. Choose one with `--operator`.",
    },
    "no_admin_user": {
        "de": "Die Instanz hat kein Admin-Konto.",
        "en": "The instance has no admin account.",
    },
    "api_error": {
        "de": "API-Fehler {status} bei {method} {path}: {body}",
        "en": "API error {status} on {method} {path}: {body}",
    },
    "cmd_error": {
        "de": "Befehl fehlgeschlagen ({cmd}): {err}",
        "en": "Command failed ({cmd}): {err}",
    },
    "no_instance": {
        "de": "Keine eingerichtete Instanz gefunden. Zuerst `einrichten` ausführen.",
        "en": "No set-up instance found. Run `setup` first.",
    },
    "instance_ambiguous": {
        "de": "Mehrere eingerichtete Instanzen: {names}. Mit `--instanz` wählen.",
        "en": "Several set-up instances: {names}. Choose one with `--instance`.",
    },
    "owner_required": {
        "de": "Der Betreiber hat Organisationen ({orgs}). Mit `--owner` den Eigentümer wählen.",
        "en": "The operator has organizations ({orgs}). Choose the owner with `--owner`.",
    },
    "repo_exists": {
        "de": "Das Repository {repo} existiert bereits. Mit `--existing-ok` trotzdem einrichten.",
        "en": "The repository {repo} already exists. Use `--existing-ok` to set it up anyway.",
    },
    "client_required": {
        "de": "Welcher Client? Bekannte Clients: {clients}.",
        "en": "Which client? Known clients: {clients}.",
    },
    "client_unknown": {
        "de": "Der Client {client} ist auf der Instanz nicht bekannt.",
        "en": "The client {client} is not known on the instance.",
    },
    "bad_name": {
        "de": "Ungültiger Name {name}: erlaubt sind a-z, 0-9 und Bindestrich; nicht mit `lauf-` beginnend.",
        "en": "Invalid name {name}: allowed are a-z, 0-9 and hyphen; must not start with `lauf-`.",
    },
    "mcp_download": {
        "de": "forgejo-mcp konnte nicht installiert werden: {err}",
        "en": "forgejo-mcp could not be installed: {err}",
    },
    "w_secret_key": {
        "de": "SECRET_KEY der Instanz ist leer. Forgejo verwendet dann still einen öffentlich bekannten Standardschlüssel für verschlüsselte Daten (z. B. 2FA-Geheimnisse). Nachträgliches Setzen macht bereits verschlüsselte Daten unlesbar; der Skill ändert daher nichts.",
        "en": "The instance's SECRET_KEY is empty. Forgejo then silently uses a publicly known default key for encrypted data (e.g. 2FA secrets). Setting it afterwards makes already encrypted data unreadable, so the skill changes nothing.",
    },
    "w_health_skipped": {
        "de": "Gesundheitsprüfung übersprungen: app.ini nicht lesbar.",
        "en": "Health check skipped: app.ini not readable.",
    },
    "w_run_token_left": {
        "de": "Der Admin-Token {name} des Betreibers konnte nicht gelöscht werden; der nächste Lauf entfernt ihn.",
        "en": "The operator's admin token {name} could not be deleted; the next run removes it.",
    },
    "w_remote_conflict": {
        "de": "`origin` zeigt bereits auf {current}; nicht geändert. Gewünscht wäre {wanted}.",
        "en": "`origin` already points to {current}; left unchanged. Wanted: {wanted}.",
    },
    "w_mcp_checksum_only": {
        "de": "forgejo-mcp {version} installiert und per SHA-256 geprüft. Die Prüfsummendatei stammt vom selben Server; eine cosign-Signaturprüfung fand nicht statt.",
        "en": "forgejo-mcp {version} installed and checked via SHA-256. The checksum file comes from the same server; no cosign signature check was done.",
    },
    "w_restart": {
        "de": "Der MCP-Server `{server}` steht erst nach einem Neustart von Claude Code zur Verfügung.",
        "en": "The MCP server `{server}` is only available after restarting Claude Code.",
    },
    "board_hint": {
        "de": "Lege in Forgejo ein Projektboard an ({url}) und übernimm die Issues des Meilensteins „{milestone}“. Forgejo hat dafür keine API.",
        "en": "Create a project board in Forgejo ({url}) and add the issues of the milestone \"{milestone}\". Forgejo has no API for this.",
    },
    "claude_md": {
        "de": "Dieses Verzeichnis gehört zum Forgejo-Repository `{repo}` auf der Instanz `{inst}` (MCP-Server `{server}`). Ordne jedes neu angelegte Issue dem Meilenstein „{milestone}“ (ID {mid}) zu.",
        "en": "This directory belongs to the Forgejo repository `{repo}` on the instance `{inst}` (MCP server `{server}`). Assign every newly created issue to the milestone \"{milestone}\" (ID {mid}).",
    },
}


def t(key, **kw):
    return MSG[key][LANG].format(**kw)


class Fail(Exception):
    def __init__(self, code, details=None, **kw):
        self.code = code
        self.message = t(code, **kw) if code in MSG else code
        self.details = details or {}
        super().__init__(self.message)


def log(text):
    print(f"igit: {text}", file=sys.stderr)


# --------------------------------------------------------------------------- Dateien

def home():
    return Path(os.environ.get("HOME") or Path.home())


def config_root():
    return home() / ".config" / "igit"


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def write_private(path, content, mode=0o600):
    private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    path.chmod(mode)


def replace_block(text, begin, end, block, prepend=False):
    """Ersetzt den Abschnitt zwischen begin/end (inklusive) oder fügt ihn ein."""
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n*", re.S)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1)
    if not block:
        return text
    if prepend:
        return block + ("\n" if text and not block.endswith("\n\n") else "") + text
    sep = "" if not text or text.endswith("\n") else "\n"
    return text + sep + ("\n" if text else "") + block


def ssh_block(inst, hostname, port, keyfile):
    begin, end = f"# igit:{inst} begin", f"# igit:{inst} end"
    body = (
        f"{begin}\n"
        f"Host igit-{inst}\n"
        f"    HostName {hostname}\n"
        f"    Port {port}\n"
        f"    User git\n"
        f"    IdentityFile {keyfile}\n"
        f"    IdentitiesOnly yes\n"
        f"    HostKeyAlias igit-{inst}\n"
        f"    StrictHostKeyChecking yes\n"
        f"{end}\n"
    )
    return begin, end, body


def update_ssh_config(inst, hostname, port, keyfile, remove=False):
    ssh_dir = private_dir(home() / ".ssh")
    cfg = ssh_dir / "config"
    text = cfg.read_text() if cfg.exists() else ""
    begin, end, body = ssh_block(inst, hostname, port, keyfile)
    # Vorn einfügen: In ssh_config gewinnt der erste Wert, ein späteres `Host *` überschreibt so nichts.
    new = replace_block(text, begin, end, "" if remove else body + "\n", prepend=True)
    write_private(cfg, new)


def update_known_hosts(inst, keys, remove=False):
    kh = private_dir(home() / ".ssh") / "known_hosts"
    alias = f"igit-{inst}"
    lines = kh.read_text().splitlines() if kh.exists() else []
    lines = [l for l in lines if not l.startswith(alias + " ")]
    if not remove:
        lines += [f"{alias} {k}" for k in keys]
    write_private(kh, "\n".join(lines) + ("\n" if lines else ""), mode=0o644 if not kh.exists() else kh.stat().st_mode & 0o777)


def inst_dir(inst):
    return config_root() / inst


def load_config(inst):
    p = inst_dir(inst) / "config.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_config(inst, cfg):
    write_private(inst_dir(inst) / "config.json", json.dumps(cfg, indent=2) + "\n")


def all_configs():
    root = config_root()
    out = {}
    if root.is_dir():
        for p in sorted(root.glob("*/config.json")):
            try:
                out[p.parent.name] = json.loads(p.read_text())
            except ValueError:
                pass
    return out


def pick_instance(name):
    cfgs = all_configs()
    if name:
        if name not in cfgs:
            raise Fail("no_instance")
        return name, cfgs[name]
    if not cfgs:
        raise Fail("no_instance")
    if len(cfgs) > 1:
        raise Fail("instance_ambiguous", {"instances": list(cfgs)}, names=", ".join(cfgs))
    return next(iter(cfgs.items()))


def valid_name(name):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", name or "") or name.startswith("lauf-"):
        raise Fail("bad_name", name=name)
    return name


def slug(text):
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-") or "client"


# --------------------------------------------------------------------------- Prozesse

def run(cmd, check=True, input=None, timeout=120):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, input=input, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        if check:
            raise Fail("cmd_error", cmd=shlex.join(cmd[:4]), err=str(e))
        return subprocess.CompletedProcess(cmd, 127, "", str(e))
    if check and p.returncode != 0:
        raise Fail("cmd_error", cmd=shlex.join(cmd[:4]), err=(p.stderr or p.stdout).strip()[-400:])
    return p


class Host:
    """Führt Befehle auf dem Rechner der Instanz aus: lokal oder per SSH."""

    def __init__(self, ssh_host=None):
        self.ssh_host = ssh_host
        self._docker = None

    def cmd(self, argv):
        if self.ssh_host:
            return ["ssh", "-o", "BatchMode=yes", self.ssh_host, shlex.join(argv)]
        return argv

    def run(self, argv, **kw):
        return run(self.cmd(argv), **kw)

    def docker(self):
        if self._docker is None:
            for prefix in (["docker"], ["sudo", "-n", "docker"]):
                if self.run(prefix + ["ps", "-q"], check=False).returncode == 0:
                    self._docker = prefix
                    break
            else:
                raise Fail("no_docker")
        return self._docker

    def compose(self):
        d = self.docker()
        if self.run(d + ["compose", "version"], check=False).returncode == 0:
            return d + ["compose"]
        prefix = d[:-1] + ["docker-compose"]
        if self.run(prefix + ["version"], check=False).returncode == 0:
            return prefix
        raise Fail("no_compose")

    def containers(self):
        out = self.run(self.docker() + ["ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Ports}}"]).stdout
        res = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and "forgejo" in parts[1]:
                ports = {}
                for m in re.finditer(r"(?:[\d.]+|\[::\]):(\d+)->(\d+)/tcp", parts[2]):
                    ports[int(m.group(2))] = int(m.group(1))
                res.append({"name": parts[0], "image": parts[1], "ports": ports})
        return res


class Admin:
    """Admin-Zugang zur Instanz über die Forgejo-CLI."""

    def __init__(self, host, container=None, admin_exec=None):
        self.host = host
        self.container = container
        self.admin_exec = admin_exec

    def forgejo(self, args):
        if self.admin_exec:
            return self.host.run(shlex.split(self.admin_exec) + args)
        return self.host.run(self.host.docker() + ["exec", "-u", "git", self.container, "forgejo"] + args)

    def read_file(self, path):
        if not self.container:
            return None
        p = self.host.run(self.host.docker() + ["exec", self.container, "cat", path], check=False)
        return p.stdout if p.returncode == 0 else None

    def admins(self):
        out = self.forgejo(["admin", "user", "list", "--admin"]).stdout
        names = []
        for line in out.splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 2 and cols[0].isdigit():
                names.append(cols[1])
        return names

    def run_token(self, operator):
        name = RUN_TOKEN_PREFIX + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(2)
        out = self.forgejo(["admin", "user", "generate-access-token", "-u", operator, "-t", name,
                            "--scopes", ADMIN_SCOPES, "--raw"]).stdout.strip()
        return name, out.splitlines()[-1].strip()


# --------------------------------------------------------------------------- API

def is_loopback(hostname):
    try:
        return all(ipaddress.ip_address(info[4][0]).is_loopback
                   for info in socket.getaddrinfo(hostname, None))
    except (socket.gaierror, ValueError):
        return False


def check_transport(url):
    u = urllib.parse.urlparse(url)
    if u.scheme == "http" and not is_loopback(u.hostname or ""):
        raise Fail("insecure_url", url=url)


class Api:
    def __init__(self, base, token=None):
        self.base = base.rstrip("/")
        self.token = token
        if token:
            check_transport(self.base)

    def call(self, method, path, body=None, ok=(200, 201, 204), soft=()):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + "/api/v1" + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "token " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except (urllib.error.URLError, OSError) as e:
            raise Fail("api_error", status="-", method=method, path=path, body=str(e))
        payload = None
        if raw:
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw.decode(errors="replace")[:200]
        if status in ok or status in soft:
            return status, payload
        raise Fail("api_error", status=status, method=method, path=path, body=str(payload)[:300])

    def paged(self, path):
        page, out = 1, []
        sep = "&" if "?" in path else "?"
        while True:
            _, items = self.call("GET", f"{path}{sep}limit=50&page={page}")
            if not items:
                return out
            out += items
            page += 1


def forgejo_version(url):
    """Liefert die Forgejo-Version oder None, wenn unter url kein Forgejo antwortet."""
    for path in ("/api/forgejo/v1/version", "/api/v1/version"):
        try:
            with urllib.request.urlopen(url.rstrip("/") + path, timeout=5) as r:
                v = json.loads(r.read()).get("version", "")
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if path.startswith("/api/forgejo") or "gitea" in v:
            return v
    return None


# --------------------------------------------------------------------------- SSH-Tunnel

def free_port(preferred=None):
    for port in ([preferred] if preferred else []) + [0]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("kein freier Port")


def port_free(port):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


class Tunnel:
    def __init__(self, ssh_host, remote_port, local_port=None):
        self.ssh_host = ssh_host
        self.remote_port = remote_port
        self.local_port = local_port or free_port()
        self.sock = Path(tempfile.mkdtemp(prefix="igit-")) / "tunnel.sock"

    def __enter__(self):
        run(["ssh", "-f", "-N", "-M", "-S", str(self.sock), "-o", "BatchMode=yes",
             "-o", "ExitOnForwardFailure=yes",
             "-L", f"127.0.0.1:{self.local_port}:localhost:{self.remote_port}", self.ssh_host])
        return f"http://127.0.0.1:{self.local_port}"

    def __exit__(self, *exc):
        run(["ssh", "-S", str(self.sock), "-O", "exit", self.ssh_host], check=False)
        shutil.rmtree(self.sock.parent, ignore_errors=True)


def ssh_resolved(ssh_host):
    out = run(["ssh", "-G", ssh_host]).stdout
    vals = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
    return vals.get("hostname", ssh_host)


# --------------------------------------------------------------------------- Sitzung

class Session:
    """Ein Lauf mit vorübergehendem Admin-Token; der Token wird am Ende immer gelöscht."""

    def __init__(self, cfg, operator=None):
        self.cfg = cfg
        self.host = Host(cfg.get("ssh_host"))
        self.admin = Admin(self.host, cfg.get("container"), cfg.get("admin_exec"))
        self.operator = operator or cfg.get("operator")
        self.warnings = []
        self._tunnel = None

    def __enter__(self):
        if not self.operator:
            admins = self.admin.admins()
            if not admins:
                raise Fail("no_admin_user")
            if len(admins) > 1:
                raise Fail("operator_ambiguous", {"admins": admins}, admins=", ".join(admins))
            self.operator = admins[0]
        self.api = None
        try:
            if self.cfg.get("ssh_host"):
                self._tunnel = Tunnel(self.cfg["ssh_host"], self.cfg["web_port"])
                self.base = self._tunnel.__enter__()
            else:
                self.base = self.cfg["url"]
            self.token_name, token = self.admin.run_token(self.operator)
            self.api = Api(self.base, token)
            self._cleanup_stale_run_tokens()
        except BaseException:
            self.__exit__()
            raise
        return self

    def _cleanup_stale_run_tokens(self):
        _, tokens = self.api.call("GET", f"/admin/users/{self.operator}/tokens")
        for tok in tokens or []:
            if tok["name"].startswith(RUN_TOKEN_PREFIX) and tok["name"] != self.token_name:
                self.api.call("DELETE", f"/admin/users/{self.operator}/tokens/{tok['id']}", soft=(404,))

    def __exit__(self, *exc):
        try:
            if self.api:
                self.api.call("DELETE", f"/admin/users/{self.operator}/tokens/{self.token_name}", soft=(404,))
        except Fail:
            self.warnings.append(t("w_run_token_left", name=self.token_name))
        finally:
            if self._tunnel:
                self._tunnel.__exit__()


# --------------------------------------------------------------------------- forgejo-mcp

def mcp_binary():
    for cand in (shutil.which("forgejo-mcp"), home() / ".local" / "bin" / "forgejo-mcp"):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            return str(cand), None
    return install_mcp()


def install_mcp():
    osname = platform.system().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    try:
        with urllib.request.urlopen(MCP_RELEASES, timeout=30) as r:
            rel = json.loads(r.read())
        assets = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
        version = rel["tag_name"].lstrip("v")
        archive = f"forgejo-mcp_{version}_{osname}_{arch}.tar.gz"
        sums_name = f"forgejo-mcp_{version}_checksums.txt"
        if archive not in assets or sums_name not in assets:
            raise RuntimeError(f"kein Release-Archiv {archive}")
        with urllib.request.urlopen(assets[sums_name], timeout=30) as r:
            sums = dict(reversed(line.split()) for line in r.read().decode().splitlines() if line.strip())
        with urllib.request.urlopen(assets[archive], timeout=120) as r:
            blob = r.read()
        if hashlib.sha256(blob).hexdigest() != sums.get(archive):
            raise RuntimeError("SHA-256 stimmt nicht")
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            member = next(m for m in tar.getmembers() if Path(m.name).name == "forgejo-mcp" and m.isfile())
            data = tar.extractfile(member).read()
    except Exception as e:  # noqa: BLE001 – jeder Fehler wird als mcp_download gemeldet
        raise Fail("mcp_download", err=str(e))
    target = home() / ".local" / "bin" / "forgejo-mcp"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.chmod(0o755)
    tmp.replace(target)
    return str(target), t("w_mcp_checksum_only", version=version)


STARTER = """#!/bin/sh
# Erzeugt von igit. Startet forgejo-mcp für die Instanz {inst}; der Token wird aus der Datei gelesen.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
FORGEJO_ACCESS_TOKEN="$(cat "$DIR/token")"
export FORGEJO_ACCESS_TOKEN
{tunnel}exec {binary} --transport stdio --url {url}
"""

TUNNEL = """SOCK="$DIR/tunnel.sock"
if ! ssh -S "$SOCK" -O check {host} 2>/dev/null; then
  ssh -f -N -M -S "$SOCK" -o BatchMode=yes -o ExitOnForwardFailure=yes -L 127.0.0.1:{lport}:localhost:{rport} {host}
fi
"""


def write_starter(inst, cfg, binary):
    tunnel = ""
    if cfg.get("ssh_host"):
        tunnel = TUNNEL.format(host=shlex.quote(cfg["ssh_host"]), lport=cfg["mcp_port"], rport=cfg["web_port"])
    path = inst_dir(inst) / "start-mcp"
    content = STARTER.format(inst=inst, tunnel=tunnel, binary=shlex.quote(binary), url=shlex.quote(cfg["mcp_url"]))
    changed = not path.exists() or path.read_text() != content
    if changed:
        write_private(path, content, mode=0o700)
    return path, changed


def mcp_registered(server, starter):
    """True, wenn `server` im Benutzer-Scope genau mit `starter` ohne Argumente registriert ist."""
    out = run(["claude", "mcp", "get", server], check=False)
    if out.returncode != 0:
        return False
    fields = dict(line.strip().split(":", 1) for line in out.stdout.splitlines() if ":" in line)
    return (fields.get("Scope", "").strip().startswith("User config")
            and fields.get("Command", "").strip() == str(starter)
            and not fields.get("Args", "").strip())


def register_mcp(inst, starter):
    """Registriert den MCP-Server nur, wenn er fehlt oder abweicht; liefert (name, geändert)."""
    server = f"forgejo-{inst}"
    if mcp_registered(server, starter):
        return server, False
    run(["claude", "mcp", "remove", server, "-s", "user"], check=False)
    run(["claude", "mcp", "add", "-s", "user", server, "--", str(starter)])
    return server, True


# --------------------------------------------------------------------------- Unterbefehle

def cmd_discover(args):
    cands = {}

    def add(url, source, **extra):
        url = url.rstrip("/")
        c = cands.setdefault(url, {"url": url, "sources": []})
        if source not in c["sources"]:
            c["sources"].append(source)
        c.update(extra)

    for name, cfg in all_configs().items():
        add(cfg["url"], "config", instance=name)
    git = run(["git", "-C", args.dir, "remote", "-v"], check=False)
    for line in git.stdout.splitlines():
        remote = line.split()[1] if len(line.split()) > 1 else ""
        m = re.match(r"(https?://[^/]+)", remote)
        if m:
            add(m.group(1), "git-remote")
        m = re.match(r"igit-([a-z0-9-]+):", remote)
        if m and load_config(m.group(1)):
            add(load_config(m.group(1))["url"], "git-remote", instance=m.group(1))
    try:
        for c in Host().containers():
            if 3000 in c["ports"]:
                add(f"http://localhost:{c['ports'][3000]}", "docker", container=c["name"])
    except Fail:
        pass
    add("http://localhost:3000", "default-port")
    found = []
    for c in cands.values():
        v = forgejo_version(c["url"])
        if v:
            c["version"] = v
            found.append(c)
    return {"instances": found}


def cmd_install(args):
    host = Host()
    compose = host.compose()
    target = Path(args.dir).expanduser()
    if (target / "docker-compose.yml").exists():
        raise Fail("dir_exists", dir=str(target))
    if any(c["name"] == args.container for c in host.containers()) or \
            host.run(host.docker() + ["inspect", args.container], check=False).returncode == 0:
        raise Fail("container_exists", name=args.container)
    for port in (args.web_port, args.ssh_port):
        if not port_free(port):
            free = [p for p in range(port + 1, port + 200) if port_free(p)][:3]
            raise Fail("port_busy", {"port": port, "free": free}, port=port, free=", ".join(map(str, free)))
    inst = valid_name(args.instanz or f"localhost-{args.web_port}")
    url = f"http://localhost:{args.web_port}"
    # Eigener Projektname: Compose leitet ihn sonst aus dem Verzeichnisnamen ab und würde fremde
    # Container desselben Projekts (z. B. ein anderes Verzeichnis namens `forgejo`) neu erzeugen.
    project = f"igit-{inst}"
    labelled = host.run(host.docker() + ["ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"]).stdout
    if labelled.strip():
        raise Fail("container_exists", name=project)
    compose_yml = f"""version: "3"
services:
  server:
    image: {FORGEJO_IMAGE}
    container_name: {args.container}
    restart: always
    environment:
      - USER_UID={os.getuid()}
      - USER_GID={os.getgid()}
      - FORGEJO__security__INSTALL_LOCK=true
      - FORGEJO__security__SECRET_KEY={secrets.token_hex(32)}
      - FORGEJO__server__ROOT_URL={url}/
      - FORGEJO__server__SSH_DOMAIN=localhost
      - FORGEJO__server__SSH_PORT={args.ssh_port}
      - FORGEJO__service__DISABLE_REGISTRATION=true
    volumes:
      - ./data:/data
    ports:
      - "{args.web_port}:3000"
      - "{args.ssh_port}:22"
"""
    private_dir(target)
    write_private(target / "docker-compose.yml", compose_yml)
    log(f"starte Forgejo in {target}")
    run(compose + ["-p", project, "-f", str(target / "docker-compose.yml"), "up", "-d"], timeout=600)
    deadline = time.time() + args.timeout
    while not forgejo_version(url):
        if time.time() > deadline:
            raise Fail("start_timeout", sec=args.timeout, url=url)
        time.sleep(2)
    password = secrets.token_urlsafe(24)
    admin = Admin(host, args.container)
    for _ in range(15):  # die Datenbank-Migration kann den ersten Aufruf noch ablehnen
        p = admin.host.run(host.docker() + ["exec", "-u", "git", args.container, "forgejo", "admin", "user", "create",
                                            "--admin", "--username", args.operator, "--email", args.email,
                                            "--password", password, "--must-change-password=false"], check=False)
        if p.returncode == 0 or "already exists" in (p.stderr + p.stdout):
            break
        time.sleep(2)
    else:
        raise Fail("cmd_error", cmd="forgejo admin user create", err=(p.stderr or p.stdout).strip()[-400:])
    pw_file = inst_dir(inst) / "betreiber-passwort"
    write_private(pw_file, password + "\n")
    save_config(inst, {"url": url, "container": args.container, "compose_dir": str(target),
                       "compose_project": project,
                       "web_port": args.web_port, "operator": args.operator})
    return {"instance": inst, "url": url, "operator": args.operator, "password_file": str(pw_file),
            "compose_file": str(target / "docker-compose.yml")}


def parse_ini(text):
    section, out = "", {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
        elif "=" in line and not line.startswith(("#", ";")):
            k, v = line.split("=", 1)
            out[(section, k.strip())] = v.strip().strip('"').strip("`")
    return out


def host_keys(admin, host, ssh_port):
    keys = []
    for typ in HOSTKEY_TYPES:
        txt = admin.read_file(f"/data/ssh/ssh_host_{typ}_key.pub")
        if txt:
            keys.append(" ".join(txt.split()[:2]))
    if not keys:
        out = host.run(["ssh-keyscan", "-p", str(ssh_port), "localhost"], check=False).stdout
        keys = [" ".join(l.split()[1:3]) for l in out.splitlines() if l and not l.startswith("#")]
    return keys


def ensure_bot(api):
    status, _ = api.call("GET", f"/users/{BOT}", soft=(404,))
    if status == 404:
        api.call("POST", "/admin/users", {
            "username": BOT, "email": f"{BOT}@noreply.localhost", "full_name": BOT_FULLNAME,
            "password": secrets.token_urlsafe(32), "must_change_password": False,
            "restricted": True, "send_notify": False})
    api.call("PATCH", f"/admin/users/{BOT}", {
        "login_name": BOT, "source_id": 0, "restricted": True,
        "max_repo_creation": 0, "allow_create_organization": False, "full_name": BOT_FULLNAME})


def ensure_client_key(api, inst, client):
    keyfile = home() / ".ssh" / f"igit_{inst}"
    private_dir(keyfile.parent)
    if not keyfile.exists():
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"igit-{client}@{inst}", "-f", str(keyfile)])
    pub = " ".join(Path(str(keyfile) + ".pub").read_text().split()[:2])
    _, keys = api.call("GET", f"/users/{BOT}/keys")
    for k in keys or []:
        if " ".join(k["key"].split()[:2]) == pub:
            return keyfile
    for k in keys or []:
        if k["title"] == client:
            api.call("DELETE", f"/admin/users/{BOT}/keys/{k['id']}", soft=(404,))
    api.call("POST", f"/admin/users/{BOT}/keys", {"title": client, "key": pub, "read_only": False})
    return keyfile


def ensure_client_token(api, token_base, inst, client):
    path = inst_dir(inst) / "token"
    if path.exists():
        status, me = Api(token_base, path.read_text().strip()).call("GET", "/user", soft=(401, 403))
        if status == 200 and me.get("login") == BOT:
            return path
    name = CLIENT_TOKEN_PREFIX + client
    api.call("DELETE", f"/admin/users/{BOT}/tokens/{name}", soft=(404,))
    _, tok = api.call("POST", f"/admin/users/{BOT}/tokens", {"name": name, "scopes": CLIENT_SCOPES})
    write_private(path, tok["sha1"] + "\n")
    return path


def operator_orgs(api):
    return [o["username"] for o in api.paged("/user/orgs")]


def missing_repos(api, operator):
    owners = {operator, *operator_orgs(api)}
    missing = []
    for repo in api.paged("/user/repos"):
        if repo["owner"]["login"] not in owners:
            continue
        status, _ = api.call("GET", f"/repos/{repo['full_name']}/collaborators/{BOT}", soft=(404,))
        if status == 404:
            missing.append(repo["full_name"])
    return missing


def cmd_setup(args):
    client = valid_name(args.client or slug(socket.gethostname()))
    url = args.url.rstrip("/")
    u = urllib.parse.urlparse(url)
    web_port = u.port or (443 if u.scheme == "https" else 80)
    remote = args.ssh_host
    inst = valid_name(args.instanz or slug(f"{remote.split('@')[-1] if remote else u.hostname}-{web_port}"))
    if not remote:
        check_transport(url)
        if not forgejo_version(url):
            raise Fail("not_forgejo", url=url)
    host = Host(remote)
    container, admin_exec = args.container, args.admin_exec
    if not container and not admin_exec:
        for c in host.containers():
            if c["ports"].get(3000) == web_port:
                container = c["name"]
        if not container:
            raise Fail("no_admin_access")
    old = load_config(inst) or {}
    cfg = {**old, "url": url, "container": container, "admin_exec": admin_exec, "ssh_host": remote,
           "web_port": web_port, "client": client, "bot": BOT}
    if args.operator:
        cfg["operator"] = args.operator
    warnings = []
    with Session(cfg, args.operator) as s:
        cfg["operator"] = s.operator
        ini_text = s.admin.read_file("/data/gitea/conf/app.ini")
        ini = parse_ini(ini_text) if ini_text else {}
        if ini_text is None:
            warnings.append(t("w_health_skipped"))
        elif not ini.get(("security", "SECRET_KEY")):
            warnings.append(t("w_secret_key"))
        ssh_port = int(ini.get(("server", "SSH_PORT")) or 22)
        ssh_hostname = ssh_resolved(remote) if remote else (ini.get(("server", "SSH_DOMAIN")) or u.hostname)
        ensure_bot(s.api)
        keyfile = ensure_client_key(s.api, inst, client)
        keys = host_keys(s.admin, host, ssh_port)
        update_known_hosts(inst, keys)
        update_ssh_config(inst, ssh_hostname, ssh_port, keyfile)
        cfg.update({"ssh_alias": f"igit-{inst}", "ssh_hostname": ssh_hostname, "ssh_port": ssh_port})
        if remote:
            cfg["mcp_port"] = old.get("mcp_port") or free_port()
            cfg["mcp_url"] = f"http://127.0.0.1:{cfg['mcp_port']}"
        else:
            cfg["mcp_url"] = url
        ensure_client_token(s.api, s.base, inst, client)
        missing = missing_repos(s.api, s.operator)
    warnings += s.warnings
    server = None
    if not args.no_mcp:
        binary, note = mcp_binary()
        if note:
            warnings.append(note)
        starter, starter_changed = write_starter(inst, cfg, binary)
        server, registration_changed = register_mcp(inst, starter)
        cfg["mcp_server"] = server
        if starter_changed or registration_changed or note:
            warnings.append(t("w_restart", server=server))
    save_config(inst, cfg)
    return {"instance": inst, "url": url, "operator": cfg["operator"], "bot": BOT, "client": client,
            "ssh_alias": cfg["ssh_alias"], "host_keys_pinned": len(keys), "mcp_server": server,
            "missing_repos": missing}, warnings


def cmd_grant(args):
    inst, cfg = pick_instance(args.instanz)
    done = []
    with Session(cfg) as s:
        for full in args.repos:
            s.api.call("PUT", f"/repos/{full}/collaborators/{BOT}", {"permission": "write"})
            done.append(full)
    return {"instance": inst, "granted": done}, s.warnings


def cmd_orgs(args):
    inst, cfg = pick_instance(args.instanz)
    with Session(cfg) as s:
        orgs = operator_orgs(s.api)
    return {"instance": inst, "operator": s.operator, "orgs": orgs}, s.warnings


def cmd_repo(args):
    inst, cfg = pick_instance(args.instanz)
    workdir = Path(args.dir).resolve()
    warnings = []
    with Session(cfg) as s:
        orgs = operator_orgs(s.api)
        owner = args.owner
        if not owner:
            if orgs:
                raise Fail("owner_required", {"orgs": orgs, "operator": s.operator},
                           orgs=", ".join(orgs))
            owner = s.operator
        full = f"{owner}/{args.name}"
        status, repo = s.api.call("GET", f"/repos/{full}", soft=(404,))
        created = status == 404
        if not created and not args.existing_ok:
            raise Fail("repo_exists", repo=full)
        if created:
            body = {"name": args.name, "private": args.private, "auto_init": False, "default_branch": "main"}
            path = "/user/repos" if owner == s.operator else f"/orgs/{owner}/repos"
            _, repo = s.api.call("POST", path, body)
        s.api.call("PUT", f"/repos/{full}/collaborators/{BOT}", {"permission": "write"})
        _, milestones = s.api.call("GET", f"/repos/{full}/milestones?state=all&limit=50")
        milestone = next((m for m in milestones or [] if m["title"] == args.name), None)
        if not milestone:
            _, milestone = s.api.call("POST", f"/repos/{full}/milestones", {"title": args.name})
    warnings += s.warnings
    remote = f"{cfg['ssh_alias']}:{full}.git"
    if run(["git", "-C", str(workdir), "rev-parse", "--git-dir"], check=False).returncode != 0:
        workdir.mkdir(parents=True, exist_ok=True)
        run(["git", "-C", str(workdir), "init", "-q", "-b", "main"])
    current = run(["git", "-C", str(workdir), "remote", "get-url", "origin"], check=False)
    if current.returncode != 0:
        run(["git", "-C", str(workdir), "remote", "add", "origin", remote])
    elif current.stdout.strip() != remote:
        warnings.append(t("w_remote_conflict", current=current.stdout.strip(), wanted=remote))
    server = cfg.get("mcp_server") or f"forgejo-{inst}"
    note = t("claude_md", repo=full, inst=inst, server=server, milestone=milestone["title"], mid=milestone["id"])
    md = workdir / "CLAUDE.md"
    text = md.read_text() if md.exists() else ""
    md.write_text(replace_block(text, "<!-- igit:begin -->", "<!-- igit:end -->",
                                f"<!-- igit:begin -->\n{note}\n<!-- igit:end -->\n"))
    board = f"{cfg['url']}/{full}/projects/new"
    return {"instance": inst, "repo": full, "created": created, "private": repo.get("private"),
            "html_url": repo.get("html_url"), "ssh_remote": remote, "milestone": milestone["title"],
            "milestone_id": milestone["id"], "claude_md": str(md),
            "board_instruction": t("board_hint", url=board, milestone=milestone["title"])}, warnings


def cmd_revoke(args):
    inst, cfg = pick_instance(args.instanz)
    with Session(cfg) as s:
        _, tokens = s.api.call("GET", f"/admin/users/{BOT}/tokens")
        _, keys = s.api.call("GET", f"/users/{BOT}/keys")
        clients = sorted({tk["name"][len(CLIENT_TOKEN_PREFIX):] for tk in tokens or []
                          if tk["name"].startswith(CLIENT_TOKEN_PREFIX)} | {k["title"] for k in keys or []})
        if not args.client:
            raise Fail("client_required", {"clients": clients, "this_client": cfg.get("client")},
                       clients=", ".join(clients) or "-")
        if args.client not in clients:
            raise Fail("client_unknown", {"clients": clients}, client=args.client)
        s.api.call("DELETE", f"/admin/users/{BOT}/tokens/{CLIENT_TOKEN_PREFIX}{args.client}", soft=(404,))
        for k in keys or []:
            if k["title"] == args.client:
                s.api.call("DELETE", f"/admin/users/{BOT}/keys/{k['id']}", soft=(404,))
    local = args.local and args.client == cfg.get("client")
    if local:
        if cfg.get("mcp_server"):
            run(["claude", "mcp", "remove", cfg["mcp_server"], "-s", "user"], check=False)
        update_ssh_config(inst, "", 0, "", remove=True)
        update_known_hosts(inst, [], remove=True)
        for p in (home() / ".ssh" / f"igit_{inst}", home() / ".ssh" / f"igit_{inst}.pub"):
            p.unlink(missing_ok=True)
        for name in ("token", "start-mcp", "config.json"):
            (inst_dir(inst) / name).unlink(missing_ok=True)
    return {"instance": inst, "revoked": args.client, "local_cleanup": local}, s.warnings


# --------------------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog="igit", description="Ersteinrichtung Forgejo + Claude / Forgejo + Claude setup")
    p.add_argument("--lang", choices=["de", "en"], help="Sprache der Meldungen / message language")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("finden", aliases=["discover"], help="laufende Instanzen suchen / find running instances")
    d.add_argument("--dir", default=".")
    d.set_defaults(fn=cmd_discover)

    i = sub.add_parser("installieren", aliases=["install"], help="Forgejo per Docker Compose installieren / install Forgejo")
    i.add_argument("--operator", required=True)
    i.add_argument("--email", required=True)
    i.add_argument("--dir", default=str(home() / "forgejo"))
    i.add_argument("--web-port", type=int, default=3000)
    i.add_argument("--ssh-port", type=int, default=2222)
    i.add_argument("--container", default="forgejo")
    i.add_argument("--instanz", "--instance", dest="instanz")
    i.add_argument("--timeout", type=int, default=180)
    i.set_defaults(fn=cmd_install)

    s = sub.add_parser("einrichten", aliases=["setup"], help="Bot-Konto, Schlüssel, Token, MCP einrichten / set up")
    s.add_argument("--url", required=True)
    s.add_argument("--ssh-host")
    s.add_argument("--container")
    s.add_argument("--admin-exec")
    s.add_argument("--operator")
    s.add_argument("--client")
    s.add_argument("--instanz", "--instance", dest="instanz")
    s.add_argument("--no-mcp", action="store_true")
    s.set_defaults(fn=cmd_setup)

    g = sub.add_parser("freigeben", aliases=["grant"], help="Bot-Konto in Repos eintragen / grant bot access")
    g.add_argument("repos", nargs="+")
    g.add_argument("--instanz", "--instance", dest="instanz")
    g.set_defaults(fn=cmd_grant)

    o = sub.add_parser("orgs", help="Organisationen des Betreibers / operator's organizations")
    o.add_argument("--instanz", "--instance", dest="instanz")
    o.set_defaults(fn=cmd_orgs)

    r = sub.add_parser("repo", help="Repository anlegen / create repository")
    r.add_argument("--name", required=True)
    vis = r.add_mutually_exclusive_group(required=True)
    vis.add_argument("--privat", "--private", dest="private", action="store_true")
    vis.add_argument("--oeffentlich", "--public", dest="private", action="store_false")
    r.add_argument("--owner")
    r.add_argument("--dir", default=".")
    r.add_argument("--existing-ok", action="store_true")
    r.add_argument("--instanz", "--instance", dest="instanz")
    r.set_defaults(fn=cmd_repo)

    w = sub.add_parser("widerrufen", aliases=["revoke"], help="Claude-Client widerrufen / revoke client")
    w.add_argument("--client")
    w.add_argument("--lokal", "--local", dest="local", action="store_true")
    w.add_argument("--instanz", "--instance", dest="instanz")
    w.set_defaults(fn=cmd_revoke)
    return p


def main(argv=None):
    global LANG
    args = build_parser().parse_args(argv)
    LANG = args.lang or ("de" if os.environ.get("LANG", "").startswith("de") else "en")
    try:
        res = args.fn(args)
        result, warnings = res if isinstance(res, tuple) else (res, [])
        print(json.dumps({"ok": True, "result": result, "warnings": warnings}, ensure_ascii=False, indent=2))
        return 0
    except Fail as e:
        print(json.dumps({"ok": False, "error": e.code, "message": e.message, "details": e.details},
                         ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
