# gitlink: Sonderfälle

Nachschlagewerk zu [SKILL.md](SKILL.md) für seltene Lagen. Die Gesprächsregeln dort gelten auch hier: eine gebündelte Frage mit Vorschlag, knappe Ergebnisse.

## Installation

Nur Forgejo wird installiert; Gitea und GitLab bedient der Skill nur, wenn sie schon laufen. Frag in einer Frage nach Benutzername und E-Mail des Betreiber-Kontos, dann `installieren --operator <name> --email <mail>` (Standard: `~/forgejo`, Ports 3000/2222). Nenne danach den Pfad aus `result.password_file` und fahre mit `einrichten --url <result.url>` fort. Bei `port_busy` schlag die Ports aus `details.free` vor (`--web-port`, `--ssh-port`).

## Instanz auf einem anderen Rechner (Forgejo, Gitea)

Hat der Betreiber SSH-Zugang zum Rechner der Instanz: `einrichten --url <adresse auf jenem rechner, meist http://localhost:3000> --ssh-host <host>`. Das Skript arbeitet dann über SSH und einen Tunnel.

## GitLab: SSH-Port

Lehnt GitLab den eingetragenen Schlüssel ab, läuft sein Git-Zugang meist auf einem anderen Port oder Host (z. B. GitLab im Container; Port 22 ist dann der Login des Servers). Lass dir die URL unter **Code → Clone with SSH** eines Projekts nennen und wiederhole `einrichten` mit `--ssh-port` bzw. `--ssh-hostname`. Das Skript pinnt die Host-Keys neu; zeig die neuen Fingerprints zum Vergleich.

## Anmelde-Proxy

`auth_proxy`: Vor der Instanz steht ein Proxy mit eigener Anmeldung (z. B. Microsoft Entra). Kein Token hilft dagegen. Frag nach einem Zugang ohne Proxy: VPN mit interner Adresse, oder für Forgejo/Gitea ein Rechner im Netz der Instanz (`--ssh-host`). Für GitLab genügt SSH: `--plattform gitlab`, ggf. mit `--ssh-hostname <interne adresse>`.

## Interne Zertifizierungsstelle

Scheitert HTTPS an einem unbekannten Zertifikat (die Instanz wird dann per HTTP nicht erkannt), frag nach dem Zertifikat der internen Stelle als PEM-Datei und übergib `--ca-cert <datei>`. Es gilt nur für diese Instanz. Bei GitLab ist das unnötig, weil dort nur SSH genutzt wird.

## Fehlercodes

| `error` | Was du tust |
|---|---|
| `instance_ambiguous` | Wähle die Instanz nach den Gesprächsregeln; sonst frag (`details.instances`), dann `--instanz`. |
| `no_instance` | Zuerst `einrichten`. |
| `operator_ambiguous` | Frag, welches Admin-Konto aus `details.admins` der Betreiber ist; `--operator`. |
| `owner_required` | Frag nach dem Eigentümer (Betreiber oder `details.orgs`); `--owner`. |
| `repo_exists` | Frag, ob das bestehende Repo eingerichtet werden soll; `--existing-ok`. |
| `repo_not_found` | Prüfe den Namen mit dem Betreiber. |
| `repo_no_access` | Repo fehlt oder Konto ohne Zugriff; der Betreiber legt es an oder klärt die Rechte. |
| `confirm_mismatch` | Bestätigung erneut einholen; `--bestaetigen` muss genau den Repo-Namen tragen. |
| `no_admin_access` | Frag nach dem Container (`--container`) oder dem CLI-Aufruf der Plattform (`--admin-exec`). |
| `ssh_unreachable` | Frag, ob der Zugang (z. B. VPN) steht und wie die interne Adresse lautet (`--ssh-hostname`). |
| `gitlab_unsupported` | Bei GitLab gibt es nur `einrichten`, `verbinden` und `widerrufen`. |
| `unsupported_platform` | Unter der Adresse läuft weder Forgejo noch Gitea noch GitLab; frag nach der richtigen. Ist die Plattform bekannt, `--plattform`. |
| `insecure_url` | Unverschlüsseltes HTTP über das Netz: frag nach `--ssh-host` oder einer HTTPS-Adresse. |
| `client_required` | Frag, welcher Client aus `details.clients` widerrufen werden soll (eigener: `details.this_client`). |
| `client_unknown` | Der genannte Client ist unbekannt; zeig `details.clients` und frag erneut. |
| `auth_proxy` | Siehe [Anmelde-Proxy](#anmelde-proxy). |
| `port_busy` | Siehe [Installation](#installation). |
| alle anderen (z. B. `no_docker`, `api_error`, `cmd_error`, `mcp_download`) | Die `message` erklärt die Ursache; gib sie weiter und frag, wie es weitergehen soll. |
