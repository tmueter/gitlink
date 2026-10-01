#!/usr/bin/env python3
"""gitlink: deterministischer Teil des Skills `gitlink` (Ersteinrichtung Forgejo/Gitea/GitLab + Claude).

Jeder Unterbefehl gibt genau ein JSON-Objekt auf stdout aus:
  {"ok": true,  "result": {...}, "warnings": [...]}
  {"ok": false, "error": "<code>", "message": "<text>", "details": {...}}
Fortschrittsmeldungen gehen nach stderr. Geheimnisse erscheinen nie in der Ausgabe.

Aufbau: gemeinsamer Kern (Dateien, SSH, MCP-Registrierung, Migration, CLI) und je Plattform ein
Adapter. Forgejo und Gitea teilen sich `GiteaFamily`. GitLab läuft ohne Token und ohne Bot: nur das Konto
des Betreibers per SSH (`setup_gitlab`, `cmd_connect`).

Spezifikation: docs/spec-gitlink-skill.md
"""
import argparse
import base64
import hashlib
import io
import ipaddress
import json
import os
import platform
import queue
import re
import secrets
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NAME = "gitlink"
LEGACY = "igit"
BOT = "claude-bot"
BOT_FULLNAME = "Claude (Bot)"
RUN_TOKEN_PREFIX = f"{NAME}-lauf-"
CLIENT_TOKEN_PREFIX = f"{NAME}-"
LEGACY_PREFIXES = (f"{LEGACY}-lauf-", f"{LEGACY}-")
FORGEJO_IMAGE = "codeberg.org/forgejo/forgejo:16"
HOSTKEY_TYPES = ("ed25519", "ecdsa", "rsa")
MD_BEGIN, MD_END = f"<!-- {NAME}:begin -->", f"<!-- {NAME}:end -->"
LEGACY_MD = (f"<!-- {LEGACY}:begin -->", f"<!-- {LEGACY}:end -->")

LANG = "de"
SSL_CTX = None  # gesetzt durch use_ca(), wenn eine Instanz eine interne Zertifizierungsstelle nutzt

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
        "de": "Ein Container bzw. Compose-Projekt namens {name} existiert bereits.",
        "en": "A container or Compose project named {name} already exists.",
    },
    "start_timeout": {
        "de": "Forgejo ist nach {sec} Sekunden unter {url} nicht erreichbar.",
        "en": "Forgejo is not reachable at {url} after {sec} seconds.",
    },
    "unsupported_platform": {
        "de": "Unter {url} antwortet weder Forgejo noch Gitea noch GitLab.",
        "en": "Neither Forgejo nor Gitea nor GitLab answers at {url}.",
    },
    "insecure_url": {
        "de": "{url} ist unverschlüsseltes HTTP und nicht Loopback. Tokens gehen so nicht über das Netz; `--ssh-host` (Tunnel) oder HTTPS verwenden.",
        "en": "{url} is plain HTTP and not loopback. Tokens will not be sent that way; use `--ssh-host` (tunnel) or HTTPS.",
    },
    "no_admin_access": {
        "de": "Kein Admin-Zugang zur Instanz gefunden: kein passender {platform}-Container. Mit `--container` oder `--admin-exec` angeben.",
        "en": "No admin access to the instance found: no matching {platform} container. Specify `--container` or `--admin-exec`.",
    },
    "auth_proxy": {
        "de": "{url} leitet auf {host} um: Vor der Instanz steht ein Anmelde-Proxy (z. B. Microsoft Entra Application Proxy). Programme kommen ohne Anmeldung im Browser nicht durch, auch nicht mit Token. Nötig ist ein Zugang ohne Proxy (VPN, Sprungrechner per `--ssh-host`) oder eine Ausnahme für `/api/v4` am Proxy.",
        "en": "{url} redirects to {host}: an authentication proxy (e.g. Microsoft Entra Application Proxy) sits in front of the instance. Programs cannot pass without a browser login, not even with a token. Needed: access without the proxy (VPN, jump host via `--ssh-host`) or an exception for `/api/v4` at the proxy.",
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
    "instance_data_missing": {
        "de": "Der Container {container} läuft, aber Konfiguration und Daten der Instanz fehlen ({path} gibt es nicht). Vermutlich wurde der Datenordner {source} gelöscht oder verschoben, während der Container lief. Lösung: Daten aus einem Backup zurückspielen und den Container neu starten, oder den Container entfernen und Forgejo neu installieren.",
        "en": "The container {container} is running, but the instance's configuration and data are missing ({path} does not exist). The data folder {source} was probably deleted or moved while the container was running. Fix: restore the data from a backup and restart the container, or remove the container and install Forgejo again.",
    },
    "config_not_found": {
        "de": "Die Konfigurationsdatei (app.ini) ist im Container {container} nicht zu finden (gesucht: {paths}). Lösung: den Pfad im Container mit `--config <pfad>` angeben.",
        "en": "The configuration file (app.ini) cannot be found in the container {container} (searched: {paths}). Fix: give its path inside the container with `--config <path>`.",
    },
    "git_identity_missing": {
        "de": "Für {dir} ist keine Git-Identität eingerichtet (Name und E-Mail für Commits). Lösung: Name und E-Mail erfragen und mit `--git-name` und `--git-email` erneut aufrufen; sie gelten nur für dieses Repo.",
        "en": "No Git identity is set for {dir} (name and email for commits). Fix: ask for name and email and call again with `--git-name` and `--git-email`; they apply to this repository only.",
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
        "de": "Der Betreiber hat Organisationen bzw. Gruppen ({orgs}). Mit `--owner` den Eigentümer wählen.",
        "en": "The operator has organizations or groups ({orgs}). Choose the owner with `--owner`.",
    },
    "repo_exists": {
        "de": "Das Repository {repo} existiert bereits. Mit `--existing-ok` trotzdem einrichten.",
        "en": "The repository {repo} already exists. Use `--existing-ok` to set it up anyway.",
    },
    "repo_not_found": {
        "de": "Das Repository {repo} existiert nicht.",
        "en": "The repository {repo} does not exist.",
    },
    "confirm_mismatch": {
        "de": "Löschen nicht bestätigt: `--bestaetigen` muss genau {repo} lauten.",
        "en": "Deletion not confirmed: `--confirm` must be exactly {repo}.",
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
        "de": "{server} konnte nicht installiert werden: {err}",
        "en": "{server} could not be installed: {err}",
    },
    "w_local_kept": {
        "de": "Das Verzeichnis {dir} wurde nicht gelöscht: {reasons}.",
        "en": "The directory {dir} was not deleted: {reasons}.",
    },
    "r_not_git": {"de": "kein Git-Repository", "en": "not a Git repository"},
    "r_other_origin": {"de": "`origin` zeigt nicht auf dieses Repository", "en": "`origin` does not point to this repository"},
    "r_dirty": {"de": "enthält nicht committete Änderungen", "en": "contains uncommitted changes"},
    "r_unpushed": {"de": "enthält nicht gepushte Commits", "en": "contains unpushed commits"},
    "w_secret_key": {
        "de": "SECRET_KEY der Instanz ist leer. {platform} verwendet dann still einen öffentlich bekannten Standardschlüssel für verschlüsselte Daten (z. B. 2FA-Geheimnisse). Nachträgliches Setzen macht bereits verschlüsselte Daten unlesbar; der Skill ändert daher nichts.",
        "en": "The instance's SECRET_KEY is empty. {platform} then silently uses a publicly known default key for encrypted data (e.g. 2FA secrets). Setting it afterwards makes already encrypted data unreadable, so the skill changes nothing.",
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
        "de": "{server} {version} installiert und per SHA-256 geprüft. Die Prüfsummendatei stammt vom selben Server; eine Signaturprüfung fand nicht statt.",
        "en": "{server} {version} installed and checked via SHA-256. The checksum file comes from the same server; no signature check was done.",
    },
    "w_restart": {
        "de": "Der MCP-Server `{server}` steht erst nach einem Neustart von Claude Code zur Verfügung.",
        "en": "The MCP server `{server}` is only available after restarting Claude Code.",
    },
    "w_mcp_check": {
        "de": "Der MCP-Server `{server}` antwortet nicht wie erwartet (Schritt {step}: {err}). Lösung: `einrichten` erneut ausführen; hilft das nicht, `{starter}` im Terminal starten und die Fehlermeldung lesen.",
        "en": "The MCP server `{server}` does not answer as expected (step {step}: {err}). Fix: run `setup` again; if that does not help, start `{starter}` in a terminal and read the error.",
    },
    "w_mcp_login": {
        "de": "Der MCP-Server `{server}` meldet sich als {login} an statt als {bot}. Lösung: {token} löschen und `einrichten` erneut ausführen.",
        "en": "The MCP server `{server}` logs in as {login} instead of {bot}. Fix: delete {token} and run `setup` again.",
    },
    "w_hostkey_tofu": {
        "de": "Host-Keys von {host}:{port} direkt über das Netz abgefragt und beim ersten Kontakt vertraut (TOFU). Vergleiche die Fingerprints mit {url}; ohne Zugang zum Host der Instanz (`--ssh-host`) geht es nicht sicherer.",
        "en": "Host keys of {host}:{port} fetched directly over the network and trusted on first use (TOFU). Compare the fingerprints with {url}; without access to the instance host (`--ssh-host`) it cannot be done more safely.",
    },
    "w_migrated": {
        "de": "Einrichtung von `{old}` auf `{new}` umgestellt ({inst}): Konfiguration, Schlüssel, SSH-Alias, known_hosts und MCP-Server.",
        "en": "Set-up migrated from `{old}` to `{new}` ({inst}): configuration, keys, SSH alias, known_hosts and MCP server.",
    },
    "w_migrate_remotes": {
        "de": "Andere Verzeichnisse mit `origin` auf `{old}:…` von Hand umstellen: `git remote set-url origin {new}:<eigentümer>/<repo>.git`.",
        "en": "Update other directories whose `origin` uses `{old}:…` by hand: `git remote set-url origin {new}:<owner>/<repo>.git`.",
    },
    "ssh_key_required": {
        "de": "Trage den öffentlichen Schlüssel dieses Clients in deinem GitLab-Konto ein: {url} (Titel `{title}`). Danach `einrichten` erneut ausführen.",
        "en": "Add this client's public key to your GitLab account: {url} (title `{title}`). Then run `setup` again.",
    },
    "ssh_unreachable": {
        "de": "SSH auf {host}:{port} ist nicht erreichbar ({err}). Ist der Name intern auflösbar? Sonst die interne Adresse mit `--ssh-hostname` angeben.",
        "en": "SSH on {host}:{port} is not reachable ({err}). Does the name resolve internally? Otherwise give the internal address with `--ssh-hostname`.",
    },
    "gitlab_unsupported": {
        "de": "Bei GitLab verbindet der Skill nur dein Konto per SSH mit Repos, die du selbst angelegt hast (`verbinden`). Repos anlegen, freigeben, archivieren, löschen und Abhängigkeiten gibt es dort nicht.",
        "en": "For GitLab the skill only connects your account via SSH to repositories you created yourself (`connect`). Creating, granting, archiving, deleting and dependencies are not available there.",
    },
    "repo_no_access": {
        "de": "Kein Zugriff auf {remote}: Gibt es das Repository, und hat dein Konto Zugriff? ({err})",
        "en": "No access to {remote}: does the repository exist and does your account have access? ({err})",
    },
    "w_gitlab_revoke": {
        "de": "Entferne den Schlüssel `{title}` auch in GitLab: {url}",
        "en": "Also remove the key `{title}` in GitLab: {url}",
    },
    "gitlab_md": {
        "de": "Dieses Verzeichnis ist mit dem GitLab-Repository `{repo}` auf `{inst}` verbunden (Konto @{account}, SSH-Alias `{alias}`). Claude leistet hier nur Hilfestellung: `git commit` und `git push` nur auf ausdrückliche Anforderung des Betreibers; keine Änderungen auf GitLab selbst (Issues, Merge Requests, Einstellungen).",
        "en": "This directory is connected to the GitLab repository `{repo}` on `{inst}` (account @{account}, SSH alias `{alias}`). Claude only assists here: `git commit` and `git push` only when the operator explicitly asks; no changes on GitLab itself (issues, merge requests, settings).",
    },
    "connect_md": {
        "de": "Dieses Verzeichnis ist mit dem {platform}-Repository `{repo}` auf `{inst}` verbunden (SSH-Alias `{alias}`, MCP-Server `{server}`).",
        "en": "This directory is connected to the {platform} repository `{repo}` on `{inst}` (SSH alias `{alias}`, MCP server `{server}`).",
    },
    "c_einrichten": {
        "de": "Prüft die Einrichtung dieser Instanz und bringt sie auf den aktuellen Stand (Schlüssel, Host-Key, Token, MCP-Server); ändert nichts, was schon stimmt.",
        "en": "Checks this instance's set-up and brings it up to date (key, host key, token, MCP server); leaves everything that is already correct.",
    },
    "c_einrichten_gitlab": {
        "de": "Prüft den SSH-Zugang deines Kontos (Schlüssel, Host-Key, Alias); ändert nichts, was schon stimmt.",
        "en": "Checks your account's SSH access (key, host key, alias); leaves everything that is already correct.",
    },
    "c_verbinden": {
        "de": "Verbindet ein lokales Verzeichnis mit einem bestehenden Repo (setzt `origin`, schreibt den Hinweis in die CLAUDE.md).",
        "en": "Connects a local directory to an existing repository (sets `origin`, writes the note into CLAUDE.md).",
    },
    "c_verbinden_gitlab": {
        "de": "Verbindet ein lokales Verzeichnis mit einem Repo, das du selbst in GitLab angelegt hast. Danach hilft Claude nur; Commit und Push nur auf deine Anforderung.",
        "en": "Connects a local directory to a repository you created yourself in GitLab. Afterwards Claude only assists; commit and push only when you ask.",
    },
    "c_repo": {
        "de": "Legt ein neues Repo an, trägt den Bot mit Schreibrecht ein, legt einen Meilenstein an und verbindet ein lokales Verzeichnis.",
        "en": "Creates a new repository, adds the bot with write access, creates a milestone and connects a local directory.",
    },
    "c_freigeben": {
        "de": "Gibt dem Bot Schreibzugriff auf bestehende Repos, z. B. solche, die du in der Weboberfläche angelegt hast.",
        "en": "Gives the bot write access to existing repositories, e.g. ones you created in the web interface.",
    },
    "c_abhaengigkeit": {
        "de": "Legt fest, welches Issue ein anderes blockiert, oder listet bzw. entfernt solche Abhängigkeiten.",
        "en": "Sets which issue blocks another, or lists or removes such dependencies.",
    },
    "c_archivieren": {
        "de": "Macht ein Repo schreibgeschützt; lässt sich rückgängig machen.",
        "en": "Makes a repository read-only; can be undone.",
    },
    "c_loeschen": {
        "de": "Löscht ein Repo endgültig, nach ausdrücklicher Bestätigung; auf Wunsch auch das lokale Verzeichnis, falls nichts Ungesichertes darin liegt.",
        "en": "Deletes a repository permanently after explicit confirmation; optionally the local directory too if nothing unsaved is in it.",
    },
    "c_widerrufen": {
        "de": "Entzieht einem Claude-Client den Zugriff (Token und SSH-Schlüssel); andere Clients bleiben unberührt.",
        "en": "Revokes a Claude client's access (token and SSH key); other clients are unaffected.",
    },
    "c_widerrufen_gitlab": {
        "de": "Entfernt den SSH-Zugang dieses Rechners lokal; den Schlüssel löschst du danach selbst in GitLab.",
        "en": "Removes this machine's SSH access locally; you then delete the key in GitLab yourself.",
    },
    "c_neu": {
        "de": "Eine weitere Instanz einrichten (Forgejo, Gitea oder GitLab) oder Forgejo neu installieren.",
        "en": "Set up another instance (Forgejo, Gitea or GitLab) or install Forgejo from scratch.",
    },
    "log_starting": {"de": "starte Forgejo in {dir}", "en": "starting Forgejo in {dir}"},
    "board_hint": {
        "de": "Lege ein Projektboard an ({url}) und übernimm die Issues des Meilensteins „{milestone}“.",
        "en": "Create a project board ({url}) and add the issues of the milestone \"{milestone}\".",
    },
    "claude_md": {
        "de": "Dieses Verzeichnis gehört zum {platform}-Repository `{repo}` auf der Instanz `{inst}` (MCP-Server `{server}`). Ordne jedes neu angelegte Issue dem Meilenstein „{milestone}“ (ID {mid}) zu. Abhängigkeiten zwischen Issues setzt `gitlink abhaengigkeit`.",
        "en": "This directory belongs to the {platform} repository `{repo}` on the instance `{inst}` (MCP server `{server}`). Assign every newly created issue to the milestone \"{milestone}\" (ID {mid}). Set dependencies between issues with `gitlink dependency`.",
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
    print(f"{NAME}: {text}", file=sys.stderr)


# --------------------------------------------------------------------------- Dateien

def home():
    return Path(os.environ.get("HOME") or Path.home())


def config_root(name=NAME):
    return home() / ".config" / name


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


def alias(inst, name=NAME):
    return f"{name}-{inst}"


def keyfile_for(inst, name=NAME):
    return home() / ".ssh" / f"{name}_{inst}"


def ssh_block(inst, hostname, port, keyfile, name=NAME):
    begin, end = f"# {name}:{inst} begin", f"# {name}:{inst} end"
    body = (
        f"{begin}\n"
        f"Host {alias(inst, name)}\n"
        f"    HostName {hostname}\n"
        f"    Port {port}\n"
        f"    User git\n"
        f"    IdentityFile {keyfile}\n"
        f"    IdentitiesOnly yes\n"
        f"    HostKeyAlias {alias(inst, name)}\n"
        f"    StrictHostKeyChecking yes\n"
        f"{end}\n"
    )
    return begin, end, body


def update_ssh_config(inst, hostname, port, keyfile, remove=False, name=NAME):
    cfg = private_dir(home() / ".ssh") / "config"
    text = cfg.read_text() if cfg.exists() else ""
    begin, end, body = ssh_block(inst, hostname, port, keyfile, name)
    # Vorn einfügen: In ssh_config gewinnt der erste Wert, ein späteres `Host *` überschreibt so nichts.
    write_private(cfg, replace_block(text, begin, end, "" if remove else body + "\n", prepend=True))


def update_known_hosts(inst, keys, remove=False, name=NAME):
    kh = private_dir(home() / ".ssh") / "known_hosts"
    prefix = alias(inst, name) + " "
    mode = kh.stat().st_mode & 0o777 if kh.exists() else 0o644
    lines = [line for line in (kh.read_text().splitlines() if kh.exists() else []) if not line.startswith(prefix)]
    if not remove:
        lines += [prefix + k for k in keys]
    write_private(kh, "\n".join(lines) + ("\n" if lines else ""), mode=mode)


def inst_dir(inst):
    return config_root() / inst


def load_config(inst):
    p = inst_dir(inst) / "config.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_config(inst, cfg):
    write_private(inst_dir(inst) / "config.json", json.dumps(cfg, indent=2) + "\n")


def all_configs():
    out = {}
    if config_root().is_dir():
        for p in sorted(config_root().glob("*/config.json")):
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


def write_md_note(workdir, note):
    md = workdir / "CLAUDE.md"
    text = md.read_text() if md.exists() else ""
    text = replace_block(text, *LEGACY_MD, "")
    md.write_text(replace_block(text, MD_BEGIN, MD_END, f"{MD_BEGIN}\n{note}\n{MD_END}\n"))
    return md


# --------------------------------------------------------------------------- Prozesse

def run(cmd, check=True, input=None, timeout=120, env=None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, input=input, timeout=timeout, env=env)
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

    def containers(self, kinds=("forgejo", "gitea")):
        out = self.run(self.docker() + ["ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Ports}}"]).stdout
        res = []
        for line in out.splitlines():
            parts = line.split("\t")
            kind = next((k for k in kinds if len(parts) == 3 and k in parts[1]), None)
            if kind:
                ports = {int(m.group(2)): int(m.group(1))
                         for m in re.finditer(r"(?:[\d.]+|\[::\]):(\d+)->(\d+)/tcp", parts[2])}
                res.append({"name": parts[0], "image": parts[1], "kind": kind, "ports": ports})
        return res

    def stopped_containers(self, kinds=("forgejo", "gitea")):
        out = self.run(self.docker() + ["ps", "-a", "--filter", "status=exited", "--filter", "status=created",
                                        "--format", "{{.Names}}\t{{.Image}}"], check=False).stdout
        return [{"name": n, "image": i, "kind": k} for n, i in (line.split("\t", 1) for line in out.splitlines() if "\t" in line)
                for k in [next((k for k in kinds if k in i), None)] if k]

    def mounts(self, container):
        """{Ziel im Container: Quelle auf dem Host} der Bind-Mounts und Volumes."""
        out = self.run(self.docker() + ["inspect", "--format", "{{range .Mounts}}{{.Destination}}\t{{.Source}}\n{{end}}",
                                        container], check=False).stdout
        return dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)


DEFAULT_CUSTOM = "/data/gitea"  # GITEA_CUSTOM in den Images von Forgejo und Gitea


def locate_config(host, container, given=None):
    """Pfad der app.ini im Container. Prüft nur, ob Dateien existieren; liest weder sie noch Umgebungswerte außer Pfaden."""
    def sh(script):
        return host.run(host.docker() + ["exec", container, "sh", "-c", script], check=False)

    cands = [given] if given else []
    if not given:
        for line in sh("ps -o args").stdout.splitlines():
            m = re.search(r"\b(?:forgejo|gitea)\b.*?\s(?:--config|-c)[=\s]+(\S+)", line)
            if m:
                cands.append(m.group(1))
        env = sh('printf "%s\\n%s\\n" "$GITEA_APP_INI" "$GITEA_CUSTOM"').stdout.split("\n")
        app_ini, custom = (env + ["", ""])[:2]
        cands += [p for p in (app_ini, f"{custom or DEFAULT_CUSTOM}/conf/app.ini") if p]
    cands = list(dict.fromkeys(cands))
    for path in cands:
        if sh(f"test -f {shlex.quote(path)}").returncode == 0:
            return path
    custom_dir = str(Path(cands[-1]).parent.parent)
    if not given and sh(f"test -d {shlex.quote(custom_dir)}").returncode != 0:
        mounts = host.mounts(container)
        source = next((src for dst, src in sorted(mounts.items(), key=lambda m: -len(m[0]))
                       if custom_dir == dst or custom_dir.startswith(dst.rstrip("/") + "/")), "?")
        raise Fail("instance_data_missing", {"container": container, "mounts": mounts, "missing": custom_dir},
                   container=container, path=custom_dir, source=source)
    raise Fail("config_not_found", {"container": container, "searched": cands},
               container=container, paths=", ".join(cands))


# --------------------------------------------------------------------------- HTTP

def is_loopback(hostname):
    try:
        return all(ipaddress.ip_address(info[4][0]).is_loopback for info in socket.getaddrinfo(hostname, None))
    except (socket.gaierror, ValueError):
        return False


def use_ca(path):
    """Vertraut zusätzlich der Zertifizierungsstelle in `path` (nur für Aufrufe an die Instanz)."""
    global SSL_CTX
    SSL_CTX = None
    if path:
        SSL_CTX = ssl.create_default_context()
        SSL_CTX.load_verify_locations(cafile=str(path))


def check_transport(url):
    u = urllib.parse.urlparse(url)
    if u.scheme == "http" and not is_loopback(u.hostname or ""):
        raise Fail("insecure_url", url=url)


class Api:
    """HTTP-Client. `auth` ist ("token", t), ("basic", user, t), ("private", t) oder None."""

    def __init__(self, base, auth=None, prefix="/api/v1"):
        self.base = base.rstrip("/")
        self.auth = auth
        self.prefix = prefix
        if auth:
            check_transport(self.base)

    def headers(self):
        if not self.auth:
            return {}
        kind = self.auth[0]
        if kind == "token":
            return {"Authorization": "token " + self.auth[1]}
        if kind == "basic":
            return {"Authorization": "Basic " + base64.b64encode(f"{self.auth[1]}:{self.auth[2]}".encode()).decode()}
        return {"PRIVATE-TOKEN": self.auth[1]}

    def call(self, method, path, body=None, ok=(200, 201, 202, 204), soft=()):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + self.prefix + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in self.headers().items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                status, raw = r.status, r.read()
                check_redirect(self.base, r.geturl())
        except urllib.error.HTTPError as e:
            check_redirect(self.base, e.geturl())
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

    def paged(self, path, size="limit"):
        page, out = 1, []
        sep = "&" if "?" in path else "?"
        while True:
            _, items = self.call("GET", f"{path}{sep}{size}=50&page={page}")
            if not items:
                return out
            out += items
            if len(items) < 50 and size == "per_page":
                return out
            page += 1


def check_redirect(start, final):
    """Bricht ab, wenn eine Anfrage auf einen fremden Host umgeleitet wurde (Anmelde-Proxy)."""
    a, b = urllib.parse.urlparse(start), urllib.parse.urlparse(final)
    if (a.hostname, a.port) != (b.hostname, b.port):
        raise Fail("auth_proxy", {"url": start, "redirect_host": b.hostname}, url=start, host=b.hostname)


def get_json(url, timeout=5):
    """(status, json) ohne Authentifizierung; (None, None) bei Netzfehler."""
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=SSL_CTX) as r:
            check_redirect(url, r.geturl())
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        check_redirect(url, e.geturl())
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


def detect_platform(url):
    """Liefert ("forgejo"|"gitea"|"gitlab", version) oder (None, None)."""
    url = url.rstrip("/")
    status, data = get_json(url + "/api/forgejo/v1/version")
    if status == 200 and isinstance(data, dict) and data.get("version"):
        return "forgejo", data["version"]
    status, data = get_json(url + "/api/v1/version")
    if status == 200 and isinstance(data, dict) and data.get("version"):
        return ("forgejo" if "+gitea" in data["version"] else "gitea"), data["version"]
    status, data = get_json(url + "/api/v4/version")
    if status == 401 and isinstance(data, dict) and "401" in str(data.get("message", "")):
        return "gitlab", None
    if status == 200 and isinstance(data, dict) and "revision" in data:
        return "gitlab", data.get("version")
    return None, None


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
        self.sock = Path(tempfile.mkdtemp(prefix=f"{NAME}-")) / "tunnel.sock"

    def __enter__(self):
        run(["ssh", "-f", "-N", "-M", "-S", str(self.sock), "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
             "-L", f"127.0.0.1:{self.local_port}:localhost:{self.remote_port}", self.ssh_host])
        return f"http://127.0.0.1:{self.local_port}"

    def __exit__(self, *exc):
        run(["ssh", "-S", str(self.sock), "-O", "exit", self.ssh_host], check=False)
        shutil.rmtree(self.sock.parent, ignore_errors=True)


def ssh_resolved(ssh_host):
    out = run(["ssh", "-G", ssh_host]).stdout
    return dict(line.split(" ", 1) for line in out.splitlines() if " " in line).get("hostname", ssh_host)


def keyscan(host, hostname, port):
    out = host.run(["ssh-keyscan", "-p", str(port), hostname], check=False).stdout
    return [" ".join(line.split()[1:3]) for line in out.splitlines() if line and not line.startswith("#")]


def parse_ssh_url(ssh_url, default_host):
    """(host, port) aus `ssh://git@host:port/pfad.git` oder `git@host:pfad.git`."""
    m = re.match(r"ssh://[^@]+@([^:/]+)(?::(\d+))?/", ssh_url)
    if m:
        return m.group(1), int(m.group(2) or 22)
    m = re.match(r"[^@]+@([^:]+):", ssh_url)
    return (m.group(1), 22) if m else (default_host, None)


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


# --------------------------------------------------------------------------- MCP-Server

def release_binary(server, releases_url, archive_name, sums_name):
    """Lädt ein Release-Binary, prüft SHA-256 gegen die Prüfsummendatei und legt es nach ~/.local/bin."""
    target = home() / ".local" / "bin" / server
    for cand in (shutil.which(server), target):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            return str(cand), None
    try:
        with urllib.request.urlopen(releases_url, timeout=30) as r:
            rel = json.loads(r.read())
        assets = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
        version = rel["tag_name"].lstrip("v")
        archive, sums = archive_name(version), sums_name(version)
        if archive not in assets or sums not in assets:
            raise RuntimeError(f"kein Release-Archiv {archive}")
        with urllib.request.urlopen(assets[sums], timeout=30) as r:
            checksums = dict(reversed(line.split()) for line in r.read().decode().splitlines() if line.strip())
        with urllib.request.urlopen(assets[archive], timeout=120) as r:
            blob = r.read()
        if hashlib.sha256(blob).hexdigest() != checksums.get(archive):
            raise RuntimeError("SHA-256 stimmt nicht")
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            member = next(m for m in tar.getmembers() if Path(m.name).name == server and m.isfile())
            data = tar.extractfile(member).read()
    except Exception as e:  # noqa: BLE001 – jeder Fehler wird als mcp_download gemeldet
        raise Fail("mcp_download", server=server, err=str(e))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.chmod(0o755)
    tmp.replace(target)
    return str(target), t("w_mcp_checksum_only", server=server, version=version)


STARTER = """#!/bin/sh
# Erzeugt von {name}. Startet den MCP-Server für die Instanz {inst}; der Token wird aus der Datei gelesen.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
{tunnel}{body}
"""

TUNNEL = """SOCK="$DIR/tunnel.sock"
if ! ssh -S "$SOCK" -O check {host} 2>/dev/null; then
  ssh -f -N -M -S "$SOCK" -o BatchMode=yes -o ExitOnForwardFailure=yes -L 127.0.0.1:{lport}:localhost:{rport} {host}
fi
"""


def write_starter(inst, cfg, body):
    tunnel = ""
    if cfg.get("ssh_host"):
        tunnel = TUNNEL.format(host=shlex.quote(cfg["ssh_host"]), lport=cfg["mcp_port"], rport=cfg["web_port"])
    if cfg.get("ca_cert"):
        ca = shlex.quote(cfg["ca_cert"])  # Node (GitLab-MCP) ergänzt, Go (forgejo-/gitea-mcp) ersetzt den Speicher
        tunnel += f"export NODE_EXTRA_CA_CERTS={ca} SSL_CERT_FILE={ca}\n"
    path = inst_dir(inst) / "start-mcp"
    content = STARTER.format(name=NAME, inst=inst, tunnel=tunnel, body=body)
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


def mcp_check(starter, bot, timeout=30):
    """Startet den MCP-Server wie Claude Code (stdio) und prüft Handshake, Tools und das angemeldete Konto.

    Liefert {"ok", "server", "tools", "login"} und bei einem Fehler `step` und `error`. stderr des Servers
    wird verworfen, Antworten werden nur auf diese Felder ausgewertet; so erscheint kein Geheimnis.
    """
    res = {"ok": False, "server": None, "tools": 0, "login": None}
    try:
        p = subprocess.Popen([str(starter)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
    except OSError as e:
        return {**res, "step": "start", "error": str(e)}
    lines = queue.Queue()

    def reader():
        try:
            for line in p.stdout:
                lines.put(line)
        except (OSError, ValueError):  # Pipe beim Aufräumen geschlossen
            pass
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    deadline = time.time() + timeout

    def call(ident, method, params=None):
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}}) + "\n")
        p.stdin.flush()
        while True:
            try:
                line = lines.get(timeout=max(0.0, deadline - time.time()))
            except queue.Empty:
                raise TimeoutError(f"> {timeout} s") from None
            if line is None:
                raise EOFError("server exited")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == ident:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"].get("message", msg["error"]))[:200])
                return msg.get("result") or {}

    step = "initialize"
    try:
        info = call(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": NAME, "version": "1"}}).get("serverInfo", {})
        res["server"] = " ".join(filter(None, (info.get("name"), info.get("version"))))
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()
        step = "tools/list"
        names = [tool.get("name") for tool in call(2, "tools/list").get("tools", [])]
        res["tools"] = len(names)
        if not names:
            raise RuntimeError("no tools")
        if "get_my_user_info" in names:
            step = "get_my_user_info"
            out = call(3, "tools/call", {"name": "get_my_user_info", "arguments": {}})
            text = "".join(c.get("text", "") for c in out.get("content", []))
            m = re.search(r'"(?:login|UserName|username)"\s*:\s*"([^"]+)"', text)
            if out.get("isError"):
                raise RuntimeError(text[:200])
            res["login"] = m.group(1) if m else None  # unbekanntes Antwortformat: Login bleibt offen
            if res["login"] and res["login"] != bot:
                step = "login"
                raise RuntimeError(res["login"])
        res["ok"] = True
        return res
    except (OSError, ValueError, RuntimeError, TimeoutError, EOFError) as e:
        return {**res, "step": step, "error": str(e)}
    finally:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        for pipe in (p.stdin, p.stdout):
            try:
                pipe.close()
            except OSError:
                pass


def register_mcp(server, starter):
    """Registriert den MCP-Server nur, wenn er fehlt oder abweicht; liefert (name, geändert)."""
    if mcp_registered(server, starter):
        return server, False
    run(["claude", "mcp", "remove", server, "-s", "user"], check=False)
    run(["claude", "mcp", "add", "-s", "user", server, "--", str(starter)])
    return server, True


# --------------------------------------------------------------------------- Adapter: Forgejo und Gitea

class GiteaFamily:
    """Gemeinsamer Adapter für Forgejo und Gitea; Unterschiede stehen in den Unterklassen."""

    name = cli = label = None
    api_prefix = "/api/v1"
    admin_scopes = "write:admin,write:repository,write:user,write:issue,write:organization"
    client_scopes = ["write:repository", "write:issue", "read:user"]

    def __init__(self, cfg, operator=None):
        self.cfg = cfg
        self.host = Host(cfg.get("ssh_host"))
        self.container = cfg.get("container")
        self.admin_exec = cfg.get("admin_exec")
        self.operator = operator or cfg.get("operator")
        self.warnings = []
        self.api = None
        self._tunnel = None
        self._config = None

    # --- Admin-Zugang über die CLI der Plattform
    def config_path(self):
        """app.ini im Container; bei `--admin-exec` nur, wenn `--config` angegeben ist."""
        if self._config is None:
            self._config = (locate_config(self.host, self.container, self.cfg.get("config")) if self.container
                            else self.cfg.get("config") or "")
        return self._config

    def cli_run(self, args):
        config = ["--config", self.config_path()] if self.config_path() else []
        if self.admin_exec:
            return self.host.run(shlex.split(self.admin_exec) + config + args)
        return self.host.run(self.host.docker() + ["exec", "-u", "git", self.container, self.cli] + config + args)

    def read_file(self, path):
        if not self.container:
            return None
        p = self.host.run(self.host.docker() + ["exec", self.container, "cat", path], check=False)
        return p.stdout if p.returncode == 0 else None

    def admins(self):
        names = []
        for line in self.cli_run(["admin", "user", "list", "--admin"]).stdout.splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 2 and cols[0].isdigit():
                names.append(cols[1])
        return names

    # --- Sitzung mit vorübergehendem Admin-Token
    def __enter__(self):
        if not self.operator:
            admins = self.admins()
            if not admins:
                raise Fail("no_admin_user")
            if len(admins) > 1:
                raise Fail("operator_ambiguous", {"admins": admins}, admins=", ".join(admins))
            self.operator = admins[0]
        try:
            if self.cfg.get("ssh_host"):
                self._tunnel = Tunnel(self.cfg["ssh_host"], self.cfg["web_port"])
                self.base = self._tunnel.__enter__()
            else:
                self.base = self.cfg["url"]
            self.token_name = RUN_TOKEN_PREFIX + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(2)
            out = self.cli_run(["admin", "user", "generate-access-token", "-u", self.operator, "-t", self.token_name,
                                "--scopes", self.admin_scopes, "--raw"]).stdout.strip()
            self.api = Api(self.base, self.admin_auth(out.splitlines()[-1].strip()), self.api_prefix)
            for tok in self.list_tokens(self.operator):
                if tok["name"].startswith((RUN_TOKEN_PREFIX, LEGACY_PREFIXES[0])) and tok["name"] != self.token_name:
                    self.delete_token(self.operator, tok["id"])
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self.api:
                self.delete_token(self.operator, self.token_name)
        except Fail:
            self.warnings.append(t("w_run_token_left", name=self.token_name))
        finally:
            if self._tunnel:
                self._tunnel.__exit__()

    # --- Tokens (hier unterscheiden sich Forgejo und Gitea)
    def admin_auth(self, token):
        return ("token", token)

    def tokens_path(self, user):
        return f"/admin/users/{user}/tokens"

    def list_tokens(self, user):
        return self.api.call("GET", self.tokens_path(user))[1] or []

    def delete_token(self, user, ident):
        self.api.call("DELETE", f"{self.tokens_path(user)}/{ident}", soft=(404,))

    def create_token(self, user, name, scopes):
        return self.api.call("POST", self.tokens_path(user), {"name": name, "scopes": scopes})[1]["sha1"]

    # --- Einrichtung
    def health(self):
        text = self.read_file(self.config_path()) if self.config_path() else None
        if text is None:
            return {}, [t("w_health_skipped")]
        ini = parse_ini(text)
        warn = [] if ini.get(("security", "SECRET_KEY")) else [t("w_secret_key", platform=self.label)]
        return ini, warn

    def ssh_endpoint(self, ini, url):
        port = int(ini.get(("server", "SSH_PORT")) or 22)
        hostname = ssh_resolved(self.cfg["ssh_host"]) if self.cfg.get("ssh_host") else \
            (ini.get(("server", "SSH_DOMAIN")) or urllib.parse.urlparse(url).hostname)
        return hostname, port

    def host_keys(self, ssh_hostname, ssh_port):
        # Admin-Zugang läuft immer auf dem Host der Instanz; dort liegen die Keys, Scan nur über Loopback.
        keys = []
        for typ in HOSTKEY_TYPES:
            txt = self.read_file(f"/data/ssh/ssh_host_{typ}_key.pub")
            if txt:
                keys.append(" ".join(txt.split()[:2]))
        return keys or keyscan(self.host, "localhost", ssh_port)

    def ensure_bot(self):
        status, _ = self.api.call("GET", f"/users/{BOT}", soft=(404,))
        if status == 404:
            self.api.call("POST", "/admin/users", {
                "username": BOT, "email": f"{BOT}@noreply.localhost", "full_name": BOT_FULLNAME,
                "password": secrets.token_urlsafe(32), "must_change_password": False,
                "restricted": True, "send_notify": False})
        self.api.call("PATCH", f"/admin/users/{BOT}", {
            "login_name": BOT, "source_id": 0, "restricted": True,
            "max_repo_creation": 0, "allow_create_organization": False, "full_name": BOT_FULLNAME})

    def bot_keys(self):
        return [{"id": k["id"], "title": k["title"], "key": " ".join(k["key"].split()[:2])}
                for k in self.api.call("GET", f"/users/{BOT}/keys")[1] or []]

    def add_bot_key(self, title, pub):
        self.api.call("POST", f"/admin/users/{BOT}/keys", {"title": title, "key": pub, "read_only": False})

    def delete_bot_key(self, key_id):
        self.api.call("DELETE", f"/admin/users/{BOT}/keys/{key_id}", soft=(404,))

    def client_token(self, name):
        for tok in self.list_tokens(BOT):
            if tok["name"] == name:
                self.delete_token(BOT, tok["id"])
        return self.create_token(BOT, name, self.client_scopes), None

    def bot_token_valid(self, token):
        status, me = Api(self.base, ("token", token), self.api_prefix).call("GET", "/user", soft=(401, 403))
        return status == 200 and me.get("login") == BOT

    def bot_token_names(self):
        return [tok["name"] for tok in self.list_tokens(BOT)]

    def revoke_token(self, name):
        for tok in self.list_tokens(BOT):
            if tok["name"] == name:
                self.delete_token(BOT, tok["id"])

    # --- Repositories
    def owners(self):
        return [o["username"] for o in self.api.paged("/user/orgs")]

    def user_info(self, name):
        """Name und E-Mail eines Kontos, als Vorschlag für die Git-Identität."""
        user = self.api.call("GET", f"/users/{name}")[1] or {}
        return {"name": user.get("full_name") or user.get("login") or name, "email": user.get("email") or None}

    def missing_repos(self):
        owners = {self.operator, *self.owners()}
        missing = []
        for repo in self.api.paged("/user/repos"):
            if repo["owner"]["login"] in owners:
                status, _ = self.api.call("GET", f"/repos/{repo['full_name']}/collaborators/{BOT}", soft=(404,))
                if status == 404:
                    missing.append(repo["full_name"])
        return missing

    def grant(self, full):
        self.api.call("PUT", f"/repos/{full}/collaborators/{BOT}", {"permission": "write"})

    def get_repo(self, full):
        status, repo = self.api.call("GET", f"/repos/{full}", soft=(404,))
        return None if status == 404 else repo

    def create_repo(self, owner, name, private):
        body = {"name": name, "private": private, "auto_init": False, "default_branch": "main"}
        path = "/user/repos" if owner == self.operator else f"/orgs/{owner}/repos"
        return self.api.call("POST", path, body)[1]

    def ensure_milestone(self, full, title):
        _, milestones = self.api.call("GET", f"/repos/{full}/milestones?state=all&limit=50")
        found = next((m for m in milestones or [] if m["title"] == title), None)
        return found or self.api.call("POST", f"/repos/{full}/milestones", {"title": title})[1]

    def repo_view(self, repo):
        return {"private": repo.get("private"), "html_url": repo.get("html_url"), "archived": repo.get("archived")}

    def board_url(self, full):
        return f"{self.cfg['url']}/{full}/projects/new"

    def archive(self, full, undo):
        return self.api.call("PATCH", f"/repos/{full}", {"archived": not undo})[1].get("archived")

    def delete_repo(self, full):
        self.api.call("DELETE", f"/repos/{full}")
        return []

    # --- Arbeit als Bot (Client-Token)
    @classmethod
    def bot_api(cls, base, token):
        return Api(base, ("token", token), cls.api_prefix)

    @classmethod
    def dependency(cls, api, full, issue, blocker, remove):
        owner, repo = full.split("/", 1)
        if blocker is not None:
            api.call("DELETE" if remove else "POST", f"/repos/{full}/issues/{issue}/dependencies",
                     {"owner": owner, "repo": repo, "index": blocker}, soft=(404,) if remove else ())
        _, deps = api.call("GET", f"/repos/{full}/issues/{issue}/dependencies")
        return [d["number"] for d in deps or []]

    # --- MCP-Server
    def mcp_setup(self, inst):
        raise NotImplementedError


class Forgejo(GiteaFamily):
    name, cli, label = "forgejo", "forgejo", "Forgejo"

    def mcp_setup(self, inst):
        arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
        osname = platform.system().lower()
        binary, note = release_binary(
            "forgejo-mcp", "https://git.b4mad.industries/api/v1/repos/agentic-forges/forgejo-mcp/releases/latest",
            lambda v: f"forgejo-mcp_{v}_{osname}_{arch}.tar.gz", lambda v: f"forgejo-mcp_{v}_checksums.txt")
        body = ('FORGEJO_ACCESS_TOKEN="$(cat "$DIR/token")"\nexport FORGEJO_ACCESS_TOKEN\n'
                f"exec {shlex.quote(binary)} --transport stdio --url {shlex.quote(self.cfg['mcp_url'])}")
        return body, [note] if note else []


class Gitea(GiteaFamily):
    name, cli, label = "gitea", "gitea", "Gitea"

    # Gitea kennt keine /admin/users/{u}/tokens; /users/{u}/tokens verlangt Basic-Authentifizierung.
    def admin_auth(self, token):
        return ("basic", self.operator, token)

    def tokens_path(self, user):
        return f"/users/{user}/tokens"

    def mcp_setup(self, inst):
        arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
        osname = platform.system()
        binary, note = release_binary(
            "gitea-mcp", "https://gitea.com/api/v1/repos/gitea/gitea-mcp/releases/latest",
            lambda v: f"gitea-mcp_{osname}_{arch}.tar.gz", lambda v: f"gitea-mcp_{v}_checksums.txt")
        body = ('export GITEA_ACCESS_TOKEN_FILE="$DIR/token"\n'
                f"exec {shlex.quote(binary)} -t stdio -H {shlex.quote(self.cfg['mcp_url'])}")
        return body, [note] if note else []


# --------------------------------------------------------------------------- GitLab: nur Konto per SSH

GITLAB_KEYS_PATH = "/-/user_settings/ssh_keys"


def gitlab_ssh_user(ssh_alias, host, port):
    """Konto, als das GitLab den Client-Schlüssel erkennt; None, wenn der Schlüssel (noch) fehlt."""
    p = run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", ssh_alias], check=False, timeout=30)
    out = p.stdout + p.stderr
    m = re.search(r"Welcome to GitLab, @([\w.-]+)!", out)
    if m:
        return m.group(1)
    if "Permission denied" in out:
        return None
    raise Fail("ssh_unreachable", {"host": host, "port": port}, host=host, port=port, err=out.strip()[-200:] or "-")


def fingerprints(keys):
    out = run(["ssh-keygen", "-lf", "-"], input="".join(f"x {k}\n" for k in keys), check=False).stdout
    return [" ".join(line.split()[i] for i in (1, 3)) for line in out.splitlines() if len(line.split()) >= 4]


def setup_gitlab(args, cfg, inst, client, warnings):
    """GitLab ohne Token: Client-Schlüssel, Host-Key-Pinning und SSH-Alias für das Konto des Betreibers."""
    hostname = args.ssh_hostname or cfg.get("ssh_hostname") or urllib.parse.urlparse(cfg["url"]).hostname
    port = args.ssh_port or cfg.get("ssh_port") or 22
    keyfile = keyfile_for(inst)
    private_dir(keyfile.parent)
    if not keyfile.exists():
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"{NAME}-{client}@{inst}", "-f", str(keyfile)])
    pub = " ".join(Path(str(keyfile) + ".pub").read_text().split()[:2])
    if cfg.get("pinned") != [hostname, port] or not cfg.get("host_keys"):
        keys = keyscan(Host(), hostname, port)
        if not keys:
            raise Fail("ssh_unreachable", {"host": hostname, "port": port}, host=hostname, port=port, err="ssh-keyscan")
        update_known_hosts(inst, keys)
        cfg["host_keys"] = fingerprints(keys)
        cfg["pinned"] = [hostname, port]
        if not is_loopback(hostname):
            warnings.append(t("w_hostkey_tofu", host=hostname, port=port,
                              url=f"{cfg['url']}/help/instance_configuration#ssh-host-keys-fingerprints"))
    update_ssh_config(inst, hostname, port, keyfile)
    cfg.pop("bot", None)
    cfg.update({"ssh_alias": alias(inst), "ssh_hostname": hostname, "ssh_port": port, "mode": "konto"})
    save_config(inst, cfg)
    account = gitlab_ssh_user(alias(inst), hostname, port)
    if not account:
        url = cfg["url"] + GITLAB_KEYS_PATH
        raise Fail("ssh_key_required", {"public_key": pub, "title": f"{NAME}-{client}", "add_key_url": url,
                                        "host_key_fingerprints": cfg["host_keys"], "warnings": warnings},
                   url=url, title=f"{NAME}-{client}")
    cfg["account"] = account
    save_config(inst, cfg)
    return {"instance": inst, "url": cfg["url"], "platform": "gitlab", "mode": "konto", "account": account,
            "client": client, "ssh_alias": alias(inst), "ssh_hostname": hostname, "ssh_port": port,
            "host_key_fingerprints": cfg["host_keys"]}, warnings


PLATFORMS = {"forgejo": Forgejo, "gitea": Gitea}


def adapter(cfg, operator=None):
    if cfg.get("platform") == "gitlab":
        raise Fail("gitlab_unsupported")
    use_ca(cfg.get("ca_cert"))
    return PLATFORMS[cfg.get("platform", "forgejo")](cfg, operator)


# --------------------------------------------------------------------------- Migration von igit

def migrate_legacy():
    """Stellt Einrichtungen des Vorgängers `igit` auf `gitlink` um; idempotent, nur lokale Daten."""
    notes = []
    old_root = config_root(LEGACY)
    if not old_root.is_dir():
        return notes
    for old_cfg in sorted(old_root.glob("*/config.json")):
        inst = old_cfg.parent.name
        if inst_dir(inst).exists():
            continue
        cfg = json.loads(old_cfg.read_text())
        private_dir(config_root())
        shutil.move(str(old_cfg.parent), str(inst_dir(inst)))
        for suffix in ("", ".pub"):
            src = Path(str(keyfile_for(inst, LEGACY)) + suffix)
            if src.exists():
                src.rename(Path(str(keyfile_for(inst)) + suffix))
        kh = home() / ".ssh" / "known_hosts"
        old_prefix = alias(inst, LEGACY) + " "
        keys = [line[len(old_prefix):] for line in (kh.read_text().splitlines() if kh.exists() else [])
                if line.startswith(old_prefix)]
        update_known_hosts(inst, [], remove=True, name=LEGACY)
        update_known_hosts(inst, keys)
        update_ssh_config(inst, "", 0, "", remove=True, name=LEGACY)
        if cfg.get("ssh_hostname"):
            update_ssh_config(inst, cfg["ssh_hostname"], cfg.get("ssh_port", 22), keyfile_for(inst))
        old_server = cfg.pop("mcp_server", None)
        if old_server:
            run(["claude", "mcp", "remove", old_server, "-s", "user"], check=False)
        cfg.update({"platform": cfg.get("platform", "forgejo"), "instance": inst, "ssh_alias": alias(inst),
                    "token_name": LEGACY_PREFIXES[1] + cfg.get("client", ""), "migrated_from": LEGACY})
        cfg["dirs"] = sorted(set(cfg.get("dirs", [])) | {str(Path.cwd())})
        for d in cfg["dirs"]:
            relink_dir(Path(d), inst)
        (inst_dir(inst) / "start-mcp").unlink(missing_ok=True)
        save_config(inst, cfg)
        if old_server:
            try:
                body, _ = adapter(cfg).mcp_setup(inst)
                if body:
                    starter, _ = write_starter(inst, cfg, body)
                    cfg["mcp_server"], _ = register_mcp(alias(inst), starter)
                    save_config(inst, cfg)
            except Fail:
                pass
        notes += [t("w_migrated", old=LEGACY, new=NAME, inst=inst), t("w_restart", server=alias(inst)),
                  t("w_migrate_remotes", old=alias(inst, LEGACY), new=alias(inst))]
    if old_root.is_dir() and not any(old_root.iterdir()):
        old_root.rmdir()
    return notes


def relink_dir(workdir, inst):
    """Stellt `origin` und den CLAUDE.md-Hinweis eines Verzeichnisses vom alten auf den neuen Alias um."""
    git = ["git", "-C", str(workdir)]
    cur = run(git + ["remote", "get-url", "origin"], check=False).stdout.strip()
    old = alias(inst, LEGACY) + ":"
    if cur.startswith(old):
        run(git + ["remote", "set-url", "origin", alias(inst) + ":" + cur[len(old):]], check=False)
    md = workdir / "CLAUDE.md"
    if md.exists() and LEGACY_MD[0] in md.read_text():
        text = md.read_text()
        block = re.search(re.escape(LEGACY_MD[0]) + r"\n(.*?)\n" + re.escape(LEGACY_MD[1]), text, re.S)
        if block:
            note = block.group(1).replace(alias(inst, LEGACY), alias(inst))
            md.write_text(replace_block(text, *LEGACY_MD, f"{MD_BEGIN}\n{note}\n{MD_END}\n"))


# --------------------------------------------------------------------------- Unterbefehle

def cmd_discover(args):
    cands = {}

    def add(url, source, **extra):
        c = cands.setdefault(url.rstrip("/"), {"url": url.rstrip("/"), "sources": []})
        if source not in c["sources"]:
            c["sources"].append(source)
        c.update(extra)

    for name, cfg in all_configs().items():
        add(cfg["url"], "config", instance=name)
    for line in run(["git", "-C", args.dir, "remote", "-v"], check=False).stdout.splitlines():
        remote = line.split()[1] if len(line.split()) > 1 else ""
        m = re.match(r"(https?://[^/]+)", remote)
        if m:
            add(m.group(1), "git-remote")
        m = re.match(rf"(?:{NAME}|{LEGACY})-([a-z0-9-]+):", remote)
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

    def check_data(c):
        if not c.get("container"):
            return
        try:
            locate_config(Host(), c["container"])
        except Fail as e:
            if e.code == "instance_data_missing":
                c.update({"data_missing": True, "message": e.message})

    for c in cands.values():
        try:
            plat, version = detect_platform(c["url"])
        except Fail as e:
            known = load_config(c["instance"]) if c.get("instance") else None
            c.update({"platform": known.get("platform") if known else None, "http_detected": False,
                      "error": e.code, "redirect_host": e.details.get("redirect_host")})
            found.append(c)
            continue
        if plat:
            c.update({"platform": plat, "version": version})
            if plat in PLATFORMS:
                check_data(c)
            found.append(c)
        elif c.get("instance") and load_config(c["instance"]):
            # Eingerichtet, aber per HTTP nicht erkennbar (z. B. interne Zertifizierungsstelle, nur SSH genutzt)
            c.update({"platform": load_config(c["instance"]).get("platform"), "version": None, "http_detected": False})
            found.append(c)
    return {"instances": found}


def cmd_install(args):
    host = Host()
    compose = host.compose()
    target = Path(args.dir).expanduser()
    if (target / "docker-compose.yml").exists():
        raise Fail("dir_exists", dir=str(target))
    if host.run(host.docker() + ["inspect", args.container], check=False).returncode == 0:
        raise Fail("container_exists", name=args.container)
    for port in (args.web_port, args.ssh_port):
        if not port_free(port):
            free = [p for p in range(port + 1, port + 200) if port_free(p)][:3]
            raise Fail("port_busy", {"port": port, "free": free}, port=port, free=", ".join(map(str, free)))
    inst = valid_name(args.instanz or f"localhost-{args.web_port}")
    url = f"http://localhost:{args.web_port}"
    # Eigener Projektname: Compose leitet ihn sonst aus dem Verzeichnisnamen ab und würde fremde
    # Container desselben Projekts (z. B. ein anderes Verzeichnis namens `forgejo`) neu erzeugen.
    project = alias(inst)
    if host.run(host.docker() + ["ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"]).stdout.strip():
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
    log(t("log_starting", dir=target))
    run(compose + ["-p", project, "-f", str(target / "docker-compose.yml"), "up", "-d"], timeout=600)
    deadline = time.time() + args.timeout
    while detect_platform(url)[0] != "forgejo":
        if time.time() > deadline:
            raise Fail("start_timeout", sec=args.timeout, url=url)
        time.sleep(2)
    password = secrets.token_urlsafe(24)
    for _ in range(15):  # die Datenbank-Migration kann den ersten Aufruf noch ablehnen
        p = host.run(host.docker() + ["exec", "-u", "git", args.container, "forgejo", "admin", "user", "create",
                                      "--admin", "--username", args.operator, "--email", args.email,
                                      "--password", password, "--must-change-password=false"], check=False)
        if p.returncode == 0 or "already exists" in (p.stderr + p.stdout):
            break
        time.sleep(2)
    else:
        raise Fail("cmd_error", cmd="forgejo admin user create", err=(p.stderr or p.stdout).strip()[-400:])
    pw_file = inst_dir(inst) / "betreiber-passwort"
    write_private(pw_file, password + "\n")
    save_config(inst, {"url": url, "platform": "forgejo", "instance": inst, "container": args.container,
                       "compose_dir": str(target), "compose_project": project,
                       "web_port": args.web_port, "operator": args.operator})
    return {"instance": inst, "url": url, "platform": "forgejo", "operator": args.operator,
            "password_file": str(pw_file), "compose_file": str(target / "docker-compose.yml")}


def ensure_client_key(a, inst, client):
    keyfile = keyfile_for(inst)
    private_dir(keyfile.parent)
    if not keyfile.exists():
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"{NAME}-{client}@{inst}", "-f", str(keyfile)])
    pub = " ".join(Path(str(keyfile) + ".pub").read_text().split()[:2])
    keys = a.bot_keys()
    if any(k["key"] == pub for k in keys):
        return keyfile
    for k in keys:
        if k["title"] == client:
            a.delete_bot_key(k["id"])
    a.add_bot_key(client, pub)
    return keyfile


def ensure_client_token(a, inst, cfg, client):
    """Behält einen gültigen Token mit aktuellem Namen; sonst neu erzeugen und Altlasten entfernen."""
    path = inst_dir(inst) / "token"
    name = CLIENT_TOKEN_PREFIX + client
    if path.exists() and cfg.get("token_name", name) == name and a.bot_token_valid(path.read_text().strip()):
        return None
    token, expires = a.client_token(name)
    write_private(path, token + "\n")
    legacy = LEGACY_PREFIXES[1] + client
    if legacy in a.bot_token_names():
        a.revoke_token(legacy)
    cfg["token_name"] = name
    return expires


def cmd_setup(args):
    migrate_notes = migrate_legacy()
    client = valid_name(args.client or slug(socket.gethostname()))
    url = args.url.rstrip("/")
    u = urllib.parse.urlparse(url)
    web_port = u.port or (443 if u.scheme == "https" else 80)
    remote = args.ssh_host
    inst = valid_name(args.instanz or slug(f"{remote.split('@')[-1] if remote else u.hostname}-{web_port}"))
    old = load_config(inst) or {}
    ca = old.get("ca_cert")
    if args.ca_cert:
        ca = str(inst_dir(inst) / "ca.pem")
        write_private(Path(ca), Path(args.ca_cert).expanduser().read_text())
    use_ca(ca)
    plat = args.platform or old.get("platform")
    if plat:
        detected = plat  # vorgegeben oder gespeichert; hinter einem Anmelde-Proxy geht Erkennung nicht
        if not remote and plat != "gitlab":  # GitLab: es geht nie ein Token über HTTP
            check_transport(url)
    elif not remote:
        check_transport(url)
        detected, _ = detect_platform(url)
    else:
        with Tunnel(remote, web_port) as base:
            detected, _ = detect_platform(base)
    if not detected:
        raise Fail("unsupported_platform", url=url)
    plat = plat or detected
    cfg = {**old, "url": url, "platform": plat, "instance": inst, "ssh_host": remote, "web_port": web_port,
           "client": client, "bot": BOT, "ca_cert": ca}
    if args.ssh_port:
        cfg["ssh_port"] = args.ssh_port
    if plat in PLATFORMS:
        container, admin_exec = args.container or old.get("container"), args.admin_exec or old.get("admin_exec")
        if not container and not admin_exec:
            for c in Host(remote).containers():
                if c["kind"] == plat and c["ports"].get(3000) == web_port:
                    container = c["name"]
            if not container:
                raise Fail("no_admin_access", platform=PLATFORMS[plat].label)
        cfg.update({"container": container, "admin_exec": admin_exec})
        if args.config:
            cfg["config"] = args.config
    if args.operator:
        cfg["operator"] = args.operator
    warnings = list(migrate_notes)
    if plat == "gitlab":
        return setup_gitlab(args, cfg, inst, client, warnings)
    with adapter(cfg, args.operator) as a:
        cfg["operator"] = a.operator
        ini, health = a.health()
        warnings += health
        ssh_hostname, ssh_port = a.ssh_endpoint(ini, url)
        a.ensure_bot()
        keyfile = ensure_client_key(a, inst, client)
        keys = a.host_keys(ssh_hostname, ssh_port)
        update_known_hosts(inst, keys)
        update_ssh_config(inst, ssh_hostname, ssh_port, keyfile)
        cfg.update({"ssh_alias": alias(inst), "ssh_hostname": ssh_hostname, "ssh_port": ssh_port})
        if remote:
            cfg["mcp_port"] = old.get("mcp_port") or free_port()
            cfg["mcp_url"] = f"http://127.0.0.1:{cfg['mcp_port']}"
        else:
            cfg["mcp_url"] = url
        ensure_client_token(a, inst, cfg, client)
        missing = a.missing_repos()
    warnings += a.warnings
    server = check = None
    if not args.no_mcp:
        body, notes = a.mcp_setup(inst)
        warnings += notes
        if body:
            starter, starter_changed = write_starter(inst, cfg, body)
            server, registration_changed = register_mcp(alias(inst), starter)
            cfg["mcp_server"] = server
            check = mcp_check(starter, BOT)
            if check.get("step") == "login":
                warnings.append(t("w_mcp_login", server=server, login=check["login"], bot=BOT,
                                  token=inst_dir(inst) / "token"))
            elif not check["ok"]:
                warnings.append(t("w_mcp_check", server=server, step=check["step"], err=check["error"], starter=starter))
            if starter_changed or registration_changed or notes:
                warnings.append(t("w_restart", server=server))
    save_config(inst, cfg)
    return {"instance": inst, "url": url, "platform": plat, "operator": cfg["operator"], "bot": BOT,
            "client": client, "ssh_alias": cfg["ssh_alias"], "host_keys_pinned": len(keys),
            "mcp_server": server, "mcp_check": check, "missing_repos": missing}, warnings


def cmd_grant(args):
    notes = migrate_legacy()
    inst, cfg = pick_instance(args.instanz)
    with adapter(cfg) as a:
        for full in args.repos:
            a.grant(full)
    return {"instance": inst, "granted": args.repos}, notes + a.warnings


def cmd_orgs(args):
    notes = migrate_legacy()
    inst, cfg = pick_instance(args.instanz)
    with adapter(cfg) as a:
        orgs = a.owners()
    return {"instance": inst, "platform": cfg.get("platform", "forgejo"), "operator": a.operator, "orgs": orgs}, notes + a.warnings


def git_identity(workdir):
    """{"name", "email"} der Git-Konfiguration, die für Commits in `workdir` gilt; None, wenn eines fehlt."""
    own = workdir.is_dir() and run(["git", "-C", str(workdir), "rev-parse", "--show-toplevel"],
                                   check=False).stdout.strip() == str(workdir)
    base = ["git", "-C", str(workdir) if own else "/"]  # außerhalb eines eigenen Repos: nur global/system
    ident = {k: run(base + ["config", "--get", f"user.{k}"], check=False).stdout.strip() for k in ("name", "email")}
    return ident if all(ident.values()) else None


def require_identity(args, workdir, suggestion):
    """Bricht vor jeder Änderung ab, wenn Commits in `workdir` keine Identität hätten; `suggestion` ist eine Funktion."""
    if not (args.git_name and args.git_email) and not git_identity(workdir):
        raise Fail("git_identity_missing", {"dir": str(workdir), "suggestion": suggestion()}, dir=str(workdir))


def set_identity(args, workdir):
    for key, value in (("name", args.git_name), ("email", args.git_email)):
        if value:
            run(["git", "-C", str(workdir), "config", f"user.{key}", value])


def has_commits(workdir):
    return run(["git", "-C", str(workdir), "rev-parse", "--verify", "-q", "HEAD"], check=False).returncode == 0


def cmd_repo(args):
    warnings = migrate_legacy()
    inst, cfg = pick_instance(args.instanz)
    workdir = Path(args.dir).resolve()
    with adapter(cfg) as a:
        require_identity(args, workdir, lambda: a.user_info(a.operator))
        owner = args.owner
        if not owner:
            orgs = a.owners()
            if orgs:
                raise Fail("owner_required", {"orgs": orgs, "operator": a.operator}, orgs=", ".join(orgs))
            owner = a.operator
        full = f"{owner}/{args.name}"
        repo = a.get_repo(full)
        created = repo is None
        if not created and not args.existing_ok:
            raise Fail("repo_exists", repo=full)
        if created:
            repo = a.create_repo(owner, args.name, args.private)
        a.grant(full)
        milestone = a.ensure_milestone(full, args.name)
        board = a.board_url(full)
    warnings += a.warnings
    remote = f"{cfg['ssh_alias']}:{full}.git"
    if run(["git", "-C", str(workdir), "rev-parse", "--git-dir"], check=False).returncode != 0:
        workdir.mkdir(parents=True, exist_ok=True)
        run(["git", "-C", str(workdir), "init", "-q", "-b", "main"])
    current = run(["git", "-C", str(workdir), "remote", "get-url", "origin"], check=False)
    if current.returncode != 0:
        run(["git", "-C", str(workdir), "remote", "add", "origin", remote])
    elif current.stdout.strip() != remote:
        warnings.append(t("w_remote_conflict", current=current.stdout.strip(), wanted=remote))
    set_identity(args, workdir)
    server = cfg.get("mcp_server") or alias(inst)
    md = write_md_note(workdir, t("claude_md", platform=a.label, repo=full, inst=inst, server=server,
                                  milestone=milestone["title"], mid=milestone["id"]))
    cfg["dirs"] = sorted(set(cfg.get("dirs", [])) | {str(workdir)})
    save_config(inst, cfg)
    return {"instance": inst, "platform": a.name, "repo": full, "created": created, **a.repo_view(repo),
            "ssh_remote": remote, "milestone": milestone["title"], "milestone_id": milestone["id"],
            "claude_md": str(md), "git_identity": git_identity(workdir), "initial_commit_pending": not has_commits(workdir),
            "board_instruction": t("board_hint", url=board, milestone=milestone["title"])}, warnings


def cmd_archive(args):
    notes = migrate_legacy()
    inst, cfg = pick_instance(args.instanz)
    with adapter(cfg) as a:
        if a.get_repo(args.repo) is None:
            raise Fail("repo_not_found", repo=args.repo)
        archived = a.archive(args.repo, args.undo)
    return {"instance": inst, "repo": args.repo, "archived": archived}, notes + a.warnings


def local_dir_blockers(workdir, remote):
    """Gründe, die gegen das Löschen eines lokalen Verzeichnisses sprechen; leer heißt: gefahrlos."""
    git = ["git", "-C", str(workdir)]
    if run(git + ["rev-parse", "--git-dir"], check=False).returncode != 0:
        return [t("r_not_git")]
    reasons = []
    if run(git + ["remote", "get-url", "origin"], check=False).stdout.strip() != remote:
        reasons.append(t("r_other_origin"))
    dirty = [line[3:] for line in run(git + ["status", "--porcelain"]).stdout.splitlines()]
    md = workdir / "CLAUDE.md"
    if dirty == ["CLAUDE.md"]:
        rest = replace_block(replace_block(md.read_text(), MD_BEGIN, MD_END, ""), *LEGACY_MD, "")
        if not rest.strip():
            dirty = []  # nur der Hinweis, den `repo` selbst geschrieben hat
    if dirty:
        reasons.append(t("r_dirty"))
    if run(git + ["log", "--branches", "--not", "--remotes", "--oneline"]).stdout.strip():
        reasons.append(t("r_unpushed"))
    return reasons


def cmd_delete(args):
    warnings = migrate_legacy()
    inst, cfg = pick_instance(args.instanz)
    if args.confirm != args.repo:
        raise Fail("confirm_mismatch", repo=args.repo)
    workdir = Path(args.dir).expanduser().resolve() if args.dir else None
    remote = f"{cfg['ssh_alias']}:{args.repo}.git"
    # Vor dem Löschen prüfen: danach gibt es keinen Server mehr, gegen den unpushte Commits zählen.
    blockers = local_dir_blockers(workdir, remote) if workdir and workdir.exists() else []
    with adapter(cfg) as a:
        if a.get_repo(args.repo) is None:
            raise Fail("repo_not_found", repo=args.repo)
        warnings += a.delete_repo(args.repo)
    warnings += a.warnings
    local_deleted = False
    if workdir and workdir.exists():
        if blockers:
            warnings.append(t("w_local_kept", dir=str(workdir), reasons=", ".join(blockers)))
        else:
            shutil.rmtree(workdir)
            local_deleted = True
    if workdir:
        cfg["dirs"] = [d for d in cfg.get("dirs", []) if d != str(workdir) or not local_deleted]
        save_config(inst, cfg)
    return {"instance": inst, "repo": args.repo, "deleted": True,
            "local_dir": str(workdir) if workdir else None, "local_deleted": local_deleted}, warnings


def client_of(token_name):
    for prefix in (CLIENT_TOKEN_PREFIX, LEGACY_PREFIXES[1]):
        if token_name.startswith(prefix) and not token_name.startswith((RUN_TOKEN_PREFIX, LEGACY_PREFIXES[0])):
            return token_name[len(prefix):]
    return None


def revoke_local(inst, cfg):
    if cfg.get("mcp_server"):
        run(["claude", "mcp", "remove", cfg["mcp_server"], "-s", "user"], check=False)
    update_ssh_config(inst, "", 0, "", remove=True)
    update_known_hosts(inst, [], remove=True)
    for suffix in ("", ".pub"):
        Path(str(keyfile_for(inst)) + suffix).unlink(missing_ok=True)
    for name in ("token", "start-mcp", "config.json"):
        (inst_dir(inst) / name).unlink(missing_ok=True)


def cmd_revoke(args):
    notes = migrate_legacy()
    inst, cfg = pick_instance(args.instanz)
    if cfg.get("platform") == "gitlab":
        client = cfg.get("client")
        if not args.client:
            raise Fail("client_required", {"clients": [client], "this_client": client}, clients=client)
        if args.client != client:
            raise Fail("client_unknown", {"clients": [client]}, client=args.client)
        revoke_local(inst, cfg)
        return {"instance": inst, "revoked": client, "local_cleanup": True}, notes + [
            t("w_gitlab_revoke", title=f"{NAME}-{client}", url=cfg["url"] + GITLAB_KEYS_PATH)]
    with adapter(cfg) as a:
        names = a.bot_token_names()
        keys = a.bot_keys()
        clients = sorted({c for c in map(client_of, names) if c} | {k["title"] for k in keys})
        if not args.client:
            raise Fail("client_required", {"clients": clients, "this_client": cfg.get("client")},
                       clients=", ".join(clients) or "-")
        if args.client not in clients:
            raise Fail("client_unknown", {"clients": clients}, client=args.client)
        for prefix in (CLIENT_TOKEN_PREFIX, LEGACY_PREFIXES[1]):
            if prefix + args.client in names:
                a.revoke_token(prefix + args.client)
        for k in keys:
            if k["title"] == args.client:
                a.delete_bot_key(k["id"])
    local = args.local and args.client == cfg.get("client")
    if local:
        revoke_local(inst, cfg)
    return {"instance": inst, "revoked": args.client, "local_cleanup": local}, notes + a.warnings


def cmd_dependency(args):
    notes = migrate_legacy()
    inst, cfg = pick_instance(args.instanz)
    if cfg.get("platform") == "gitlab":
        raise Fail("gitlab_unsupported")
    token = (inst_dir(inst) / "token").read_text().strip()
    use_ca(cfg.get("ca_cert"))
    cls = PLATFORMS[cfg.get("platform", "forgejo")]
    tunnel = Tunnel(cfg["ssh_host"], cfg["web_port"]) if cfg.get("ssh_host") else None  # eigener freier Port
    try:
        base = tunnel.__enter__() if tunnel else cfg["url"]
        blocked_by = cls.dependency(cls.bot_api(base, token), args.repo, args.issue, args.blocker, args.remove)
    finally:
        if tunnel:
            tunnel.__exit__()
    return {"instance": inst, "repo": args.repo, "issue": args.issue, "blocked_by": blocked_by}, notes


def remote_access(remote):
    """(ok, fehlertext) für einen Lesezugriff auf das entfernte Repository."""
    p = run(["git", "ls-remote", remote], check=False, timeout=60)
    return p.returncode == 0, (p.stderr or p.stdout).strip()[-200:]


def cmd_connect(args):
    notes = migrate_legacy()
    inst, cfg = pick_instance(args.instanz)
    workdir = Path(args.dir).resolve()
    remote = f"{cfg['ssh_alias']}:{args.repo}.git"
    granted = False
    if cfg.get("platform", "forgejo") in PLATFORMS:  # Bot eintragen, sonst hätte er keinen Zugriff
        with adapter(cfg) as a:
            require_identity(args, workdir, lambda: a.user_info(a.operator))
            if a.get_repo(args.repo) is None:
                raise Fail("repo_not_found", repo=args.repo)
            a.grant(args.repo)
            granted = True
        notes += a.warnings
    else:
        require_identity(args, workdir, lambda: {"name": cfg.get("account"), "email": None})
    ok, err = remote_access(remote)
    if not ok:
        raise Fail("repo_no_access", {"remote": remote}, remote=remote, err=err)
    if run(["git", "-C", str(workdir), "rev-parse", "--git-dir"], check=False).returncode != 0:
        workdir.mkdir(parents=True, exist_ok=True)
        run(["git", "-C", str(workdir), "init", "-q", "-b", "main"])
    current = run(["git", "-C", str(workdir), "remote", "get-url", "origin"], check=False)
    if current.returncode != 0:
        run(["git", "-C", str(workdir), "remote", "add", "origin", remote])
    elif current.stdout.strip() != remote:
        notes.append(t("w_remote_conflict", current=current.stdout.strip(), wanted=remote))
    set_identity(args, workdir)
    plat = cfg.get("platform", "forgejo")
    if plat == "gitlab":
        note = t("gitlab_md", repo=args.repo, inst=inst, account=cfg.get("account", "?"), alias=cfg["ssh_alias"])
    else:
        note = t("connect_md", platform=PLATFORMS[plat].label, repo=args.repo, inst=inst, alias=cfg["ssh_alias"],
                 server=cfg.get("mcp_server") or alias(inst))
    md = write_md_note(workdir, note)
    cfg["dirs"] = sorted(set(cfg.get("dirs", [])) | {str(workdir)})
    save_config(inst, cfg)
    return {"instance": inst, "platform": plat, "repo": args.repo, "ssh_remote": remote, "bot_granted": granted,
            "claude_md": str(md)}, notes


COMMANDS = {
    "forgejo": ["einrichten", "verbinden", "repo", "freigeben", "abhaengigkeit", "archivieren", "loeschen", "widerrufen"],
    "gitea": ["einrichten", "verbinden", "repo", "freigeben", "abhaengigkeit", "archivieren", "loeschen", "widerrufen"],
    "gitlab": ["einrichten", "verbinden", "widerrufen"],
}
EN_NAMES = {"einrichten": "setup", "verbinden": "connect", "freigeben": "grant", "abhaengigkeit": "dependency",
            "archivieren": "archive", "loeschen": "delete", "widerrufen": "revoke", "repo": "repo"}


def cmd_overview(args):
    """Eingerichtete Instanzen und je Plattform nur die Befehle, die dort möglich sind."""
    notes = migrate_legacy()
    instances = []
    for inst, cfg in all_configs().items():
        plat = cfg.get("platform", "forgejo")
        cmds = []
        for c in COMMANDS[plat]:
            key = f"c_{c}_{plat}" if f"c_{c}_{plat}" in MSG else f"c_{c}"
            cmds.append({"command": c if LANG == "de" else EN_NAMES[c], "description": t(key)})
        instances.append({"instance": inst, "platform": plat, "url": cfg.get("url"),
                          "account": cfg.get("account") or cfg.get("operator"), "commands": cmds})
    return {"instances": instances, "other": {"command": "einrichten" if LANG == "de" else "setup",
                                              "description": t("c_neu")}}, notes


# --------------------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog=NAME, description="Forgejo/Gitea/GitLab + Claude einrichten / set up")
    p.add_argument("--lang", choices=["de", "en"], help="Sprache der Meldungen / message language")
    sub = p.add_subparsers(dest="cmd", required=True)

    def inst_arg(sp):
        sp.add_argument("--instanz", "--instance", dest="instanz")

    def identity_args(sp):
        sp.add_argument("--git-name", help="Git-Name für Commits in diesem Repo / Git name for this repository")
        sp.add_argument("--git-email", help="Git-E-Mail für Commits in diesem Repo / Git email for this repository")

    u = sub.add_parser("uebersicht", aliases=["overview"], help="eingerichtete Instanzen und mögliche Befehle / set-up instances and possible commands")
    u.set_defaults(fn=cmd_overview)

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
    i.add_argument("--timeout", type=int, default=180)
    inst_arg(i)
    i.set_defaults(fn=cmd_install)

    s = sub.add_parser("einrichten", aliases=["setup"], help="Bot, Schlüssel, Token, MCP einrichten / set up")
    s.add_argument("--url", required=True)
    s.add_argument("--plattform", "--platform", dest="platform", choices=[*PLATFORMS, "gitlab"])
    s.add_argument("--ssh-host")
    s.add_argument("--ssh-port", type=int)
    s.add_argument("--ssh-hostname", help="SSH-Ziel, falls abweichend vom Web-Host (z. B. interne Adresse)")
    s.add_argument("--ca-cert", help="Zertifikat einer internen Zertifizierungsstelle (PEM) / internal CA certificate")
    s.add_argument("--container")
    s.add_argument("--admin-exec")
    s.add_argument("--config", help="Pfad der app.ini im Container bzw. für `--admin-exec` / app.ini path")
    s.add_argument("--operator")
    s.add_argument("--client")
    s.add_argument("--no-mcp", action="store_true")
    inst_arg(s)
    s.set_defaults(fn=cmd_setup)

    g = sub.add_parser("freigeben", aliases=["grant"], help="Bot in Repos eintragen / grant bot access")
    g.add_argument("repos", nargs="+")
    inst_arg(g)
    g.set_defaults(fn=cmd_grant)

    o = sub.add_parser("orgs", help="Organisationen/Gruppen des Betreibers / operator's organizations or groups")
    inst_arg(o)
    o.set_defaults(fn=cmd_orgs)

    r = sub.add_parser("repo", help="Repository anlegen / create repository")
    r.add_argument("--name", required=True)
    vis = r.add_mutually_exclusive_group(required=True)
    vis.add_argument("--privat", "--private", dest="private", action="store_true")
    vis.add_argument("--oeffentlich", "--public", dest="private", action="store_false")
    r.add_argument("--owner")
    r.add_argument("--dir", default=".")
    r.add_argument("--existing-ok", action="store_true")
    identity_args(r)
    inst_arg(r)
    r.set_defaults(fn=cmd_repo)

    w = sub.add_parser("widerrufen", aliases=["revoke"], help="Claude-Client widerrufen / revoke client")
    w.add_argument("--client")
    w.add_argument("--lokal", "--local", dest="local", action="store_true")
    inst_arg(w)
    w.set_defaults(fn=cmd_revoke)

    a = sub.add_parser("archivieren", aliases=["archive"], help="Repository archivieren / archive repository")
    a.add_argument("--repo", required=True, help="eigentümer/name")
    a.add_argument("--rueckgaengig", "--undo", dest="undo", action="store_true")
    inst_arg(a)
    a.set_defaults(fn=cmd_archive)

    x = sub.add_parser("loeschen", aliases=["delete"], help="Repository endgültig löschen / delete repository")
    x.add_argument("--repo", required=True, help="eigentümer/name")
    x.add_argument("--bestaetigen", "--confirm", dest="confirm", required=True,
                   help="noch einmal eigentümer/name / eigentümer/name again")
    x.add_argument("--dir", help="lokales Verzeichnis mitlöschen / also delete local directory")
    inst_arg(x)
    x.set_defaults(fn=cmd_delete)

    v = sub.add_parser("verbinden", aliases=["connect"], help="Verzeichnis mit bestehendem Repo verbinden / connect directory to existing repo")
    v.add_argument("--repo", required=True, help="eigentümer/name bzw. gruppe/…/name")
    v.add_argument("--dir", default=".")
    identity_args(v)
    inst_arg(v)
    v.set_defaults(fn=cmd_connect)

    b = sub.add_parser("abhaengigkeit", aliases=["dependency"], help="Issue-Abhängigkeiten / issue dependencies")
    b.add_argument("--repo", required=True, help="eigentümer/name")
    b.add_argument("--issue", type=int, required=True, help="Nummer des blockierten Issues / blocked issue number")
    b.add_argument("--blockiert-durch", "--blocked-by", dest="blocker", type=int,
                   help="Nummer des blockierenden Issues; ohne: nur auflisten / blocking issue; omit to list")
    b.add_argument("--entfernen", "--remove", dest="remove", action="store_true")
    inst_arg(b)
    b.set_defaults(fn=cmd_dependency)
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
