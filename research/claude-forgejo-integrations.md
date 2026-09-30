# Welche bestehenden Integrationen lassen Claude Code eine Forgejo-Instanz steuern?

Recherche für Issue #4. Stand 2026-09-30, erhoben aus Primärquellen (Projekt-READMEs, Quelldateien, generierte CLI-Doku, Wikis und Release-APIs). Lokales Ziel: Forgejo `16.0.5+gitea-1.22.0` (aus `GET /api/v1/version`). Der Endpunkt `/issues/{n}/dependencies` funktioniert dort (liefert `[]` für #4).

## Kurzfassung

| Integration | Art | Token-Übergabe | Mehrere Instanzen | Repo anlegen | Issues / Kommentare | PRs | Issue-Abhängigkeiten | Letztes Release |
|---|---|---|---|---|---|---|---|---|
| **forgejo-mcp** (goern / agentic-forges) | MCP-Server, Forgejo-nativ | Env `FORGEJO_ACCESS_TOKEN` oder `--token`. Im HTTP-Modus ein `Authorization`-Header pro Anfrage | **Nein**, eine `--url` pro Prozess. Pro Instanz einen Server-Eintrag betreiben | Ja (`create_repo`, `owner` = Nutzer oder Organisation), dazu `create_org` | Vollständig | Anlegen, ändern, mergen, reviewen, Diff | **Ja**: `list_issue_dependencies`, `list_issue_dependents`, `add_issue_dependency`, `remove_issue_dependency` (repo-übergreifend möglich) | v3.2.0, 2026-09-16 (laut Projektseite; der Release-Host steht hinter einer Bot-Sperre) |
| **gitea-mcp** (offiziell von Gitea) | MCP-Server, Gitea-API | Env `GITEA_ACCESS_TOKEN` oder `-T`. Im HTTP-Modus `Authorization: Bearer/token` | **Nein**, ein `GITEA_HOST` / `-H` pro Prozess | Ja (`create_repo`, optional `organization`) | Vollständig (`issue_write`) | Anlegen, mergen, Reviewer, Reviews | Ja, über `issue_read` / `issue_write`-Methoden | v1.7.0, 2026-08-27 |
| **tea** (offizielle Gitea-CLI) | CLI | `tea login add --url … --token …` (oder OAuth, SSH-Schlüssel, Passwort), gespeichert in `$XDG_CONFIG_HOME/tea` | **Ja**: benannte Logins, `--login <name>` oder aus dem Git-Remote erkannt | Ja (`tea repos create`, `create-from-template`, `migrate`) | Anlegen, ändern, schließen, kommentieren | Anlegen, reviewen, freigeben, mergen, auschecken | Kein Unterbefehl. `tea api` verwenden | v0.16.0, 2026-09-10 |
| **fj / forgejo-cli** (forgejo-contrib) | CLI, Forgejo-nativ | `fj auth add-key` (interaktives Einfügen) oder `fj auth login` (OAuth, nur freigegebene Instanzen) | **Ja**: pro Host, gewählt mit `-H/--host` oder aus dem Git-Remote | Ja (`fj repo create`, mit `--push` / `--remote`) | Anlegen, ändern, Labels, kommentieren, schließen | Anlegen (auch AGit), mergen | Nicht dokumentiert | v0.6.0, 2026-07-19 |
| Reines REST (`curl` oder das `fj`-Hilfsskript dieses Repos) | HTTP | `Authorization: token …` | Trivial ja | Ja | Ja | Ja | Ja | n/a |

**Antwort:** Zwei MCP-Server werden gepflegt und decken alles ab, was dieses Projekt braucht: Repos anlegen, Issues und PRs bearbeiten und Issue-Abhängigkeiten. Keiner der beiden spricht mit mehr als einer Instanz pro Server-Prozess, man registriert also einen MCP-Server pro Instanz. Für mehrere Instanzen sind die CLIs (`tea`, `fj`) besser, weil jede benannte Logins pro Host verwaltet. `tea` hat zusätzlich mit `tea api` einen authentifizierten Ausweg für alles, wofür es keinen Unterbefehl gibt, etwa Abhängigkeiten.

## 1. forgejo-mcp (Christoph Görn / „agentic-forges“)

- **Ort:** Die Entwicklung ist 2026 nach `https://git.b4mad.industries/agentic-forges/forgejo-mcp` umgezogen. `codeberg.org/goern/forgejo-mcp` ist jetzt ein schreibgeschützter Spiegel, die GitHub-Kopie trägt das Label „MIRROR ONLY“. Quelle: das Banner im README des Spiegels („📦 This project has moved…“).
- **Pflege:** aktiv. Die Projektseite meldet v3.2.0 am 2026-09-16, mit 32 Releases und ~1,5k Commits. Die Codeberg-Release-API endet bei v2.30.2 (2026-07-13), dem Zeitpunkt des Umzugs. Es werden signierte OCI-Images (cosign plus SBOM) ausgeliefert, und es gibt einen Go-Modulpfad `git.b4mad.industries/agentic-forges/forgejo-mcp/v3`. Der neue Host steht hinter Anubis, seine Release-API ließ sich daher nicht direkt abfragen.
- **Authentifizierung:** `--url` / `FORGEJO_URL` und `--token` / `FORGEJO_ACCESS_TOKEN` (Konfigurationstabelle im README).
  - In den Transporten `http`/`sse` muss jede Anfrage ihren eigenen Header `Authorization: token <t>` oder `Bearer <t>` tragen. Das ist der „Multi-Tenant“-Modus. Der eigene Token des Servers wird nur mit `--allow-operator-token-fallback` verwendet.
  - Es gibt einen optionalen OAuth-Resource-Server-Modus (`--auth-mode resource-server`).
  - `FORGEJO_USER_AGENT` existiert für Proxys, die Gos Standard-User-Agent blockieren.
- **Mehrere Instanzen:** nein. „Multi-Tenant“ meint viele *Nutzer* auf einer Instanz, da `--url` pro Prozess fest ist. Für N Instanzen konfiguriert man N MCP-Server (z. B. `forgejo-home`, `forgejo-work`). Die `forgejo://`-Ressourcen-URIs werden als „instance-portable“ beschrieben, das betrifft aber ihre Form, nicht ein Routing über mehrere Instanzen.
- **Abdeckung (Tool-Tabelle im README):**
  - **Repos:** `create_repo` (Quelle: `operation/repo/repo.go` nimmt `owner` „Owner/org name“), `fork_repo`, `edit_repo`, `get_repo`, `search_repos`, `list_my_repos`, Topics, Branch-Schutz, Webhooks.
  - **Dateien:** anlegen, ändern, löschen, Baum.
  - **Organisationen:** `create_org`, `edit_org`, `delete_org`, Mitgliedschaft.
  - **Issues:** `create_issue`, `update_issue`, `issue_state_change`, `add_issue_labels`/`remove_issue_labels`, `search_issues` sowie Label-CRUD auf Repo- und Organisationsebene.
  - **Kommentare:** vollständiges CRUD, dazu Anhänge.
  - **Abhängigkeiten:** `list_issue_dependencies`, `list_issue_dependents`, `add_issue_dependency`, `remove_issue_dependency`. Die repo-übergreifende Form nutzt `depends_on_owner`/`depends_on_repo`.
  - **PRs:** `create_pull_request`, `update_pull_request`, `get_pull_request_diff`, `list_pull_request_files`, `merge_pull_request` (merge/rebase/squash, Branch löschen), `create_pull_review` (APPROVED/REQUEST_CHANGES/COMMENT mit Inline-Kommentaren).
  - **Sonstiges:** Releases, Wiki, Actions-Läufe und -Logs (Forgejo v16+), Pakete, Benachrichtigungen.
  - **CLI-Modus:** Das Binary kann Tools auch ohne MCP aufrufen, mit JSON auf stdout.
- **Lücken:** keine für „Repos anlegen + Issues/PRs bearbeiten + Abhängigkeiten“. Die einzige Lücke ist die Beschränkung auf eine Instanz pro Prozess.

## 2. gitea-mcp (offiziell, gitea.com/gitea/gitea-mcp)

- **Pflege:** aktiv, gepflegt von der Gitea-Organisation. v1.7.0 erschien am 2026-08-27, v1.6.0 am 2026-07-30 (gitea.com-Release-API).
- **Authentifizierung:** `GITEA_ACCESS_TOKEN` / `-T` und `GITEA_HOST` / `-H`, wobei Flags Vorrang vor Env haben. Im HTTP-Modus wird `Authorization: Bearer|token` akzeptiert.
  - Das README nennt einen Claude-Code-Einzeiler: `claude mcp add --transport stdio --scope user gitea --env GITEA_ACCESS_TOKEN=… --env GITEA_HOST=… -- go run gitea.com/gitea/gitea-mcp@latest -t stdio`.
  - Nur-Lese-Modus ist `-r` / `GITEA_READONLY`. Tool-Filter sind `-S` / `GITEA_SCOPES` und `-O` / `GITEA_TOOLS`.
- **Mehrere Instanzen:** nein, ein Host pro Prozess.
- **Abdeckung (Tabelle im README):**
  - `create_repo`: Quelle `operation/repo/repo.go` hat einen optionalen Parameter `organization`, der `CreateOrgRepo` aufruft.
  - `fork_repo`.
  - `issue_read` / `issue_write`: „create, update, manage comments, labels and dependencies“.
  - `pull_request_write`: anlegen, ändern, schließen, wieder öffnen, mergen, Branch aktualisieren, Reviewer.
  - `pull_request_review_write`.
  - Außerdem Labels, Meilensteine, Projekte, Wiki, Actions, Releases, Dateien, Branches und Tags.
  - Die Tools sind zusammengefasst und aktionsbasiert (ein `method`-Parameter).
- **Forgejo-Kompatibilität:** im README nicht erwähnt. Das Ziel ist die Gitea-API, und Forgejo 16 wirbt mit Gitea-1.22-API-Kompatibilität. Neuere, nur in Gitea vorhandene Endpunkte (z. B. Gitea-Projekte, falls aufgerufen) können auf Forgejo 404 liefern. Das ist eine Schlussfolgerung und wurde hier nicht getestet.
- **Lücken:** keine für die Kernanforderungen, abgesehen von einer Instanz pro Prozess und unverifizierten Abweichungen zu Forgejo.

## 3. tea (offizielle Gitea-CLI, gitea.com/gitea/tea)

- **Pflege:** aktiv. v0.16.0 erschien am 2026-09-10, v0.15.1 am 2026-08-02 (gitea.com-Release-API).
- **Authentifizierung:** `tea login add` mit `--url/-u`, `--token/-t`, `--name/-n`, `--insecure`, `--oauth`, `--ssh-agent-key`, `--password` (erzeugt einen Token), `--scopes` und `--no-version-check`. Logins werden in `$XDG_CONFIG_HOME/tea` gespeichert (`docs/CLI.md`, README). `--git-credentials` registriert tea als Git-Credential-Helper. Ein Modus mit Token allein aus einer Umgebungsvariable ist nicht dokumentiert.
- **Mehrere Instanzen:** ja. Es verwaltet benannte Logins, und jeder Befehl nimmt `--login/-l` oder `--remote/-R`, um den Login aus dem Git-Remote zu ermitteln.
- **Abdeckung (`docs/CLI.md`):**
  - `repos create|create-from-template|fork|migrate|delete|edit` (mit `--owner` für Organisationen bei list).
  - `issues create|edit|close|reopen`.
  - `comments add|list|edit|delete`.
  - `pulls create|review|approve|reject|merge|checkout|review-comments|resolve`.
  - Außerdem Labels, Meilensteine, Releases, Organisationen, Actions, Webhooks, Wiki und Admin.
  - `--output json` bei vielen Befehlen.
  - **`tea api`** stellt beliebige authentifizierte Anfragen (`-X`, `-f/-F`, `-d`, `--login`), ähnlich wie `gh api`.
- **Lücken:** kein Unterbefehl für Issue-Abhängigkeiten. `tea api -X POST /repos/{o}/{r}/issues/{n}/dependencies` deckt das ab. Die Gitea-Versionsprüfung lässt sich mit `--no-version-check` überspringen, falls Forgejos Versionsstring sie stört.

## 4. fj / forgejo-cli (codeberg.org/forgejo-contrib/forgejo-cli)

- **Pflege:** aktiv, aber langsamer. v0.6.0 erschien am 2026-07-19, v0.5.0 am 2026-04-16 (Codeberg-Release-API). Forgejo-nativ und in Rust geschrieben. Nicht mit dem `fj`-API-Hilfsskript dieses Repos verwechseln.
- **Authentifizierung (Wiki „Authentication“):**
  - `fj auth add-key` bedeutet, einen Anwendungs-Token interaktiv einzufügen.
  - `fj auth login` nutzt OAuth, aber nur für freigegebene Instanzen (Codeberg, code.forgejo.org und andere). Die Liste lässt sich über `~/.config/forgejo-cli/client_ids` erweitern.
  - Eine localhost-Instanz braucht `add-key`. Ein Token per Umgebungsvariable ist nicht dokumentiert, was eine nicht-interaktive Einrichtung umständlich macht.
- **Mehrere Instanzen:** ja. Schlüssel gelten pro Host, gewählt über `-H/--host` oder aus dem Git-Remote abgeleitet.
- **Abdeckung (README und Wiki):**
  - `fj repo create` (`--private`, `--push`, `--remote`), fork, migrate, delete, edit.
  - Issues: anlegen, Titel/Body/Labels ändern, kommentieren, schließen mit `--with-msg`.
  - PRs: anlegen (auch AGit-PRs ohne Fork) und mergen.
  - Außerdem Organisationen, Teams, Releases und Actions.
- **Lücken:** keine dokumentierten Issue-Abhängigkeiten und kein dokumentiertes generisches `api`-Passthrough. Interaktive Editor-Voreinstellungen brauchen zudem Flags wie `--body`, um nicht-interaktiv zu bleiben.

## 5. Sonstiges / Randerscheinungen

- Eine Suche findet mehrere Forgejo-MCP-Server einzelner Autoren: `raohwork/forgejo-mcp`, `Sqcows`/SquareCows `forgejo-mcp` („103 tools“), `teran/mcp-forgejo`, `kepatrick/forgejo-mcp` (Governance-Dashboard), `minhcuongvu`, `nsvk13` und ein npm-Paket `@ric_/forgejo-mcp`. Keiner wurde eingehend geprüft. Sie sind aufgeführt, damit sie nicht erneut gesucht werden, und werden nicht gegenüber den beiden gepflegten Servern oben empfohlen.
- **Forgejo selbst** liefert keinen eingebauten MCP-Endpunkt. In den Release-Notes bis v16.0.x fand sich nichts.
- **Reines REST** deckt alles ab, einschließlich Abhängigkeiten (auf der lokalen Instanz geprüft), mit einem `Authorization: token`-Header. Genau das tut das `fj`-Hilfsskript dieses Repos bereits.

## Folgerungen für igit

1. Die beste MCP-Option ist **forgejo-mcp**, weil es Forgejo-nativ ist, explizite Abhängigkeits-Tools hat und Repo-Anlage in Organisationen unterstützt. Es wird einmal pro Instanz mit `--url` plus `FORGEJO_ACCESS_TOKEN` registriert. `gitea-mcp` ist knapp dahinter, mit offizieller Unterstützung und einem Claude-Code-Einzeiler.
2. Keiner der MCP-Server bedient mehrere Instanzen in einem Prozess. Ein Design für mehrere Instanzen braucht entweder einen MCP-Server-Eintrag pro Instanz oder eine CLI mit benannten Logins (`tea --login`).
3. `tea` plus `tea api` ist der vollständigste Weg ohne MCP und von Haus aus mehrinstanzfähig.
4. Die Installation eines dieser Werkzeuge ist eine Änderung auf Nutzerebene und wurde in dieser Recherche bewusst nicht vorgenommen.

## Quellen

- forgejo-mcp README (Codeberg-Spiegel): https://codeberg.org/goern/forgejo-mcp/raw/branch/main/README.md. Außerdem `operation/repo/repo.go` im selben Repo. Neue Heimat: https://git.b4mad.industries/agentic-forges/forgejo-mcp
- gitea-mcp README: https://gitea.com/gitea/gitea-mcp/raw/branch/main/README.md. Außerdem `operation/repo/repo.go`. Releases: https://gitea.com/api/v1/repos/gitea/gitea-mcp/releases
- tea README und generierte CLI-Doku: https://gitea.com/gitea/tea (`docs/CLI.md`). Releases: https://gitea.com/api/v1/repos/gitea/tea/releases
- forgejo-cli README und Wiki (Authentication, Repositories, Issues): https://codeberg.org/forgejo-contrib/forgejo-cli. Releases: https://codeberg.org/api/v1/repos/forgejo-contrib/forgejo-cli/releases
- Lokale Instanz: `GET /api/v1/version`, `GET /api/v1/repos/dreamer/igit/issues/4/dependencies`
