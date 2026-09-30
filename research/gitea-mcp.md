# Welcher MCP-Server bedient Gitea, und wie wird er installiert?

Recherche zu Issue #17 (Map #15). Stand: 30.09.2026. Untersuchte Versionen: gitea-mcp v1.7.0 (veröffentlicht 27.08.2026) und forgejo-mcp v3.2.0 (veröffentlicht 16.09.2026).

## Kurzantwort

Für Gitea empfiehlt sich **gitea-mcp** (gitea.com/gitea/gitea-mcp), den das Gitea-Projekt selbst pflegt. Er wird wie forgejo-mcp als statisches Go-Binary aus den Release-Assets installiert, über stdio gestartet und liest den Token aus einer Env-Variable oder direkt aus einer Datei (`GITEA_ACCESS_TOKEN_FILE`). Die unbequeme Einschränkung: **gitea-mcp hat keine Werkzeuge für Issue-Abhängigkeiten**, obwohl die Gitea-API sie anbietet. Außerdem liefert gitea-mcp nur eine SHA-256-Prüfsummendatei, keine Signatur.

forgejo-mcp deckt Abhängigkeiten ab und würde gegen Gitea technisch wahrscheinlich laufen, weil die Endpunkte gleich heißen und die Versionsprüfungen des SDK Gitea-Versionen (1.x) akzeptieren. Das Projekt testet aber ausschließlich gegen Forgejo und sagt keine Gitea-Unterstützung zu. [Unsicher] Ein Live-Test gegen eine Gitea-Instanz fand nicht statt, weil keine Container gestartet werden durften.

## Vergleich

| Kriterium | gitea-mcp v1.7.0 | forgejo-mcp v3.2.0 gegen Gitea |
|---|---|---|
| Zielplattform laut Projekt | Gitea | Forgejo; getestet gegen Forgejo 15.0.4 und 16.0.0 |
| Repos (anlegen, auflisten, Dateien, Branches) | ja | ja |
| Issues (anlegen, ändern, kommentieren, Labels) | ja, als `issue_write` mit `method` | ja, als einzelne Werkzeuge |
| Meilensteine anlegen/ändern | ja (`milestone_write`) | ja |
| Meilenstein beim Anlegen eines Issues zuordnen | ja, Parameter `milestone` als **ID** | ja, Parameter `milestone` als Name **oder** ID |
| Issue-Abhängigkeiten | **nein** | ja (`list_issue_dependencies`, `list_issue_dependents`, `add_issue_dependency`, `remove_issue_dependency`) |
| Pull Requests (anlegen, mergen, Reviews) | ja | ja |
| Token per Env-Variable | `GITEA_ACCESS_TOKEN` | `FORGEJO_ACCESS_TOKEN` (veraltet: `GITEA_ACCESS_TOKEN`) |
| Token aus Datei | `GITEA_ACCESS_TOKEN_FILE` | nein |
| Token per Flag | `-T`/`-token` | `--token` |
| URL | `-H`/`-host` oder `GITEA_HOST` (Standard: `https://gitea.com`) | `--url` oder `FORGEJO_URL` |
| stdio-Aufruf | `gitea-mcp -t stdio -H <url>` | `forgejo-mcp --transport stdio --url <url>` |
| Prüfsummen | `gitea-mcp_<version>_checksums.txt` (SHA-256) | `forgejo-mcp_<version>_checksums.txt` (SHA-256) |
| Signatur | **keine** | `checksums.txt.sig` (cosign), zusätzlich SBOM je Archiv |
| Plattformen (Binaries) | Linux, macOS, Windows; x86_64, arm64, i386 (macOS ohne i386) | Linux, macOS; amd64, arm64 |

## gitea-mcp im Detail

### Abdeckung

Die Werkzeugtabelle im README nennt unter anderem `create_repo`, `list_my_repos`, `list_issues`, `issue_read`, `issue_write`, `milestone_read`, `milestone_write`, `list_pull_requests`, `pull_request_read`, `pull_request_write` und `pull_request_review_write` ([README.md, Abschnitt „Available Tools“](https://gitea.com/gitea/gitea-mcp/src/tag/v1.7.0/README.md)). Mehrere Werkzeuge sind zusammengefasst und wählen die Operation über einen Pflichtparameter `method`. Für `issue_write` sind das `create`, `update`, `add_comment`, `edit_comment`, `add_labels`, `remove_label`, `replace_labels` und `clear_labels`; die Parameter umfassen `assignees`, `milestone` (Zahl) und `labels` (Label-IDs) (`operation/issue/issue.go`, Zeilen 68–80). Beim Anlegen wird `milestone` direkt in `CreateIssueOption.Milestone` übernommen (`operation/issue/issue.go`, Zeilen 241–247). Ein Meilenstein lässt sich also beim Anlegen zuordnen, aber nur über die numerische ID; ein Name wird nicht aufgelöst.

Im gesamten Verzeichnis `operation/` gibt es kein Werkzeug für Abhängigkeiten; die Suche nach „dependenc“ trifft nur `pkg/log/log.go`. Die Gitea-API selbst kennt die Endpunkte `/repos/{owner}/{repo}/issues/{index}/dependencies` und `/repos/{owner}/{repo}/issues/{index}/blocks` jeweils mit GET, POST und DELETE ([Swagger von gitea.com](https://gitea.com/swagger.v1.json), Gitea 1.27.0+dev). Die Lücke liegt also im MCP-Server, nicht in Gitea.

Mit `-r`/`GITEA_READONLY` blendet der Server alle schreibenden Werkzeuge aus; mit `-S`/`GITEA_SCOPES` und `-O`/`GITEA_TOOLS` lässt sich die Werkzeugmenge filtern (README, Hinweis unter „Available Tools“).

### Token, Aufruf und Laufzeitverhalten

Die Ausgabe von `gitea-mcp --help` (v1.7.0, lokal in einem temporären Verzeichnis ausgeführt) nennt die Flags `-t, -transport` (Standard `stdio`), `-H, -host` (Standard `https://gitea.com`), `-T, -token`, `-r, -read-only`, `-k, -insecure` und `-v, -version` sowie die Env-Variablen `GITEA_ACCESS_TOKEN`, `GITEA_ACCESS_TOKEN_FILE`, `GITEA_HOST`, `GITEA_READONLY`, `GITEA_INSECURE` und `MCP_MODE`. Laut README haben Flags Vorrang vor Env-Variablen.

`GITEA_ACCESS_TOKEN_FILE` liest die Datei und entfernt abschließende Zeilenumbrüche (`cmd/cmd.go`, Zeilen 120–127). Damit entfällt im Starter das `cat` in eine Variable; der Token erscheint weder in der Prozessliste noch in der Umgebung des Prozesses.

Der Server schreibt ein Log nach `$HOME/.gitea-mcp/gitea-mcp.log` (README, Abschnitt „Configuration“). Das ist ein Seiteneffekt, den forgejo-mcp nicht hat.

Die Flags folgen dem Go-Paket `flag`, das `-host` und `--host` gleich behandelt. [Unsicher] Die Doppelstrich-Form wurde nicht ausgeführt, nur aus der Go-Konvention und dem README-Beispiel `"--host"` (Abschnitt „Other clients“) abgeleitet. Der Starter unten nutzt die Kurzformen aus `--help`.

### Release-Assets

Die Release-API `https://gitea.com/api/v1/repos/gitea/gitea-mcp/releases/latest` liefert für v1.7.0 diese Assets:

- `gitea-mcp_1.7.0_checksums.txt`
- `gitea-mcp_Darwin_arm64.tar.gz`, `gitea-mcp_Darwin_x86_64.tar.gz`
- `gitea-mcp_Linux_arm64.tar.gz`, `gitea-mcp_Linux_i386.tar.gz`, `gitea-mcp_Linux_x86_64.tar.gz`
- `gitea-mcp_Windows_arm64.zip`, `gitea-mcp_Windows_i386.zip`, `gitea-mcp_Windows_x86_64.zip`

Das Namensschema weicht in drei Punkten von forgejo-mcp ab. Erstens enthalten die Archivnamen **keine Version**, nur die Prüfsummendatei. Zweitens ist das Betriebssystem großgeschrieben (`Linux`, `Darwin`) und entspricht damit direkt `platform.system()`. Drittens heißt amd64 `x86_64` und 386 `i386`, wie bei `uname -m`. Das Schema stammt aus `.goreleaser.yaml` (`name_template` mit `title .Os` und der Umbenennung von amd64/386). Dieselbe Datei enthält keinen `signs`- oder `sboms`-Abschnitt, daher gibt es keine Signatur.

Die Prüfsummendatei hat das übliche Format `<sha256>  <dateiname>`. Für `gitea-mcp_Linux_x86_64.tar.gz` stimmte die berechnete SHA-256 (`bbc9a7b4…f00e`) mit dem Eintrag überein. Das Archiv enthält auf oberster Ebene `gitea-mcp`, `LICENSE`, `README.md`, `README.zh-cn.md` und `README.zh-tw.md`.

Alternativ gibt es das Container-Image `docker.gitea.com/gitea-mcp-server` und `go run gitea.com/gitea/gitea-mcp@latest` (README, Abschnitte „Installation“ und „Claude Code“). Beides passt nicht zum bisherigen Installationsweg des Skills.

## forgejo-mcp gegen Gitea

### Was dafür spricht

forgejo-mcp nutzt das SDK `codeberg.org/mvdkleijn/forgejo-sdk/forgejo/v3` v3.0.0 (`go.mod`). Dessen Versionsprüfungen vergleichen mit Gitea-artigen Schwellen (1.11.0 bis 1.23.0, dazu 8.0.3) (`version.go` im SDK, Zeilen 67–78). Eine Gitea-Instanz meldet eine Version wie `1.27.0+dev-955-g37488799e1` ([`/api/v1/version` von gitea.com](https://gitea.com/api/v1/version)) und besteht damit alle Prüfungen bis 1.23.0. Die einzige Stelle, die 1.23.0 verlangt, ist die HTTP-Signatur (`httpsign.go`, Zeile 213), die für Token-Betrieb keine Rolle spielt.

forgejo-mcp fragt die Server-Version selbst nur im Modus `--auth-mode resource-server` ab und verlangt dort eine Forgejo-Hauptversion (`operation/authmode.go`, Zeilen 179–189). Im stdio-Modus mit Token greift diese Sperre nicht.

Die Abhängigkeitswerkzeuge rufen `/repos/{owner}/{repo}/issues/{index}/dependencies` und `/blocks` auf (`operation/issue/dependency.go`, Zeilen 104, 119, 212, 237). Diese Endpunkte existieren in der Gitea-API mit gleichem Pfad.

forgejo-mcp liest zudem noch die alten Variablen `GITEA_HOST` und `GITEA_ACCESS_TOKEN` mit Deprecation-Warnung (`cmd/cmd.go`, Zeilen 159–164 und 208–211); das ist ein Überbleibsel aus der gemeinsamen Herkunft, keine Gitea-Unterstützung.

### Was dagegen spricht

Das README nennt als getesteten Bereich ausschließlich Forgejo `15.0.4+gitea-1.22.0` und `16.0.0+gitea-1.22.0` und schreibt ausdrücklich „This is the tested range, not a guarantee“ (README, Abschnitt zum Wiki). Forgejo ist seit 2024 ein harter Fork; seine API entfernt sich schrittweise von Gitea. Jede Abweichung würde bei Gitea erst im Betrieb auffallen, und das Projekt hat keinen Anlass, sie zu beheben. [Unsicher] Konkrete Inkompatibilitäten sind nicht belegt, weil kein Live-Test stattfand.

## Empfehlung

**gitea-mcp für Gitea, forgejo-mcp weiter für Forgejo.** Begründung: gitea-mcp ist der vom Hersteller gepflegte Server, deckt Repos, Issues, Meilensteine (inklusive Zuordnung beim Anlegen) und PRs ab und lässt sich nach demselben Muster installieren. Der Preis ist die fehlende Abhängigkeitsverwaltung. Falls die Map #15 Abhängigkeiten für Gitea zwingend braucht, sind zwei Wege denkbar: forgejo-mcp gegen Gitea einsetzen und das Risiko einer nicht zugesagten Kompatibilität tragen, oder Abhängigkeiten für Gitea über die REST-API im Skill setzen. Diese Entscheidung gehört in die Map, nicht in dieses Ticket.

### Starter

Analog zu `STARTER` in `skill/igit/igit.py`, aber mit Token-Datei statt `cat`:

```sh
#!/bin/sh
# Erzeugt von igit. Startet gitea-mcp für die Instanz {inst}; der Token wird aus der Datei gelesen.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
GITEA_ACCESS_TOKEN_FILE="$DIR/token"
export GITEA_ACCESS_TOKEN_FILE
{tunnel}exec {binary} -t stdio -H {url}
```

`-H` ist Pflicht, weil der Standardwert `https://gitea.com` ist; ohne das Flag würde der Server mit dem lokalen Token gegen gitea.com arbeiten. Der Tunnel-Block `TUNNEL` kann unverändert übernommen werden. Registriert wird wie bisher mit `claude mcp add -s user gitea-{inst} -- <starter>`; der Servername sollte das Präfix `gitea-` tragen, damit er neben `forgejo-{inst}` eindeutig bleibt.

### Installationsweg

Nach dem Muster von `install_mcp()`:

1. `https://gitea.com/api/v1/repos/gitea/gitea-mcp/releases/latest` abrufen; `version = tag_name.lstrip("v")`.
2. Betriebssystem: `platform.system()` direkt verwenden (`Linux`, `Darwin`). Architektur abbilden: `x86_64`/`amd64` → `x86_64`, `aarch64`/`arm64` → `arm64`.
3. Archiv `gitea-mcp_{os}_{arch}.tar.gz` (ohne Version) und Prüfsummendatei `gitea-mcp_{version}_checksums.txt` suchen; fehlt eines, abbrechen.
4. SHA-256 des Archivs gegen den Eintrag prüfen.
5. Aus dem Archiv das Mitglied `gitea-mcp` extrahieren und atomar nach `~/.local/bin/gitea-mcp` schreiben, Modus 0755.
6. Warnung ausgeben, dass nur die Prüfsumme vom selben Server geprüft wurde und das Projekt keine Signatur veröffentlicht.

`mcp_binary()` sollte entsprechend nach `gitea-mcp` im `PATH` und in `~/.local/bin` suchen. Beim Versionsschema ist zu beachten, dass gitea-mcp (1.x) und forgejo-mcp (3.x) unabhängig nummerieren.

## Quellen

- Issue #17: http://localhost:3000/dreamer/igit/issues/17
- gitea-mcp v1.7.0: README.md, `.goreleaser.yaml`, `cmd/cmd.go`, `operation/issue/issue.go`, `operation/milestone/milestone.go`, `operation/pull/pull.go` (Quellarchiv https://gitea.com/gitea/gitea-mcp/archive/v1.7.0.tar.gz)
- gitea-mcp Release-API: https://gitea.com/api/v1/repos/gitea/gitea-mcp/releases/latest
- gitea-mcp `--help` und Prüfsummenabgleich: lokal ausgeführt, Linux x86_64
- Gitea-API: https://gitea.com/swagger.v1.json, https://gitea.com/api/v1/version
- forgejo-mcp v3.2.0: README.md, `go.mod`, `cmd/cmd.go`, `operation/authmode.go`, `operation/issue/dependency.go`, `operation/issue/issue.go`, `pkg/forgejo/version.go` (Quellarchiv über https://git.b4mad.industries/api/v1/repos/agentic-forges/forgejo-mcp/archive/v3.2.0.tar.gz)
- forgejo-mcp Release-API: https://git.b4mad.industries/api/v1/repos/agentic-forges/forgejo-mcp/releases/latest
- forgejo-sdk v3.0.0: `version.go`, `httpsign.go` (https://proxy.golang.org/codeberg.org/mvdkleijn/forgejo-sdk/forgejo/v3/@v/v3.0.0.zip)
- Heutiger Skill: `skill/igit/igit.py`, Funktionen `install_mcp`, `write_starter`, `register_mcp` und Konstante `STARTER`
