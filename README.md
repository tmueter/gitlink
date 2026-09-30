# gitlink

`gitlink` ist ein Claude-Code-Skill, der die Ersteinrichtung zwischen einer selbst betriebenen Instanz von **Forgejo**, **Gitea** oder **GitLab** und Claude automatisiert. Nach einem Lauf kann Claude über ein eigenes Bot-Konto Repositories anlegen, per SSH pushen und Issues verwalten, ohne dass Schlüssel, Tokens oder Remotes von Hand übertragen werden. Der Skill hieß früher `igit`; bestehende Einrichtungen stellt er beim ersten Lauf automatisch um.

Der Skill versteht Deutsch und Englisch: Er antwortet in der Sprache, in der man ihn anspricht, und alle Unterbefehle haben einen deutschen und einen englischen Namen.

## Plattformen

| Plattform | Stand | Admin-Zugang | MCP-Server |
|---|---|---|---|
| Forgejo 16 | vollständig, gegen echte Instanz getestet; der Skill kann Forgejo auch installieren | Forgejo-CLI im Container, vorübergehender Admin-Token | forgejo-mcp |
| Gitea 28 | vollständig, gegen echte Instanz getestet | Gitea-CLI im Container, vorübergehender Admin-Token | gitea-mcp |
| GitLab, selbst gehostet | umgesetzt, **nur gegen einen nachgebauten API-Server getestet** | Admin-Token, den der Betreiber einmal ablegt | `@zereight/mcp-gitlab` (Node.js ≥ 18.17) |

GitHub und gitlab.com werden nicht unterstützt.

## Inhalt

| Pfad | Inhalt |
|---|---|
| [`skill/gitlink/SKILL.md`](skill/gitlink/SKILL.md) | Anweisungen für Claude: Rückfragen und Abläufe |
| [`skill/gitlink/gitlink.py`](skill/gitlink/gitlink.py) | Skript für alle deterministischen Schritte (Python 3, nur Standardbibliothek) |
| [`tests/test_gitlink.py`](tests/test_gitlink.py) | Unit-Tests, laufen ohne Docker und ohne echte Instanz |
| [`docs/spec-gitlink-skill.md`](docs/spec-gitlink-skill.md) | Spezifikation: Ablauf, Dateien, Sicherheitsregeln, Plattformen, Umfang |
| [`CONTEXT.md`](CONTEXT.md) | Glossar der Fachbegriffe (Instanz, Betreiber, Bot-Konto, Client-Schlüssel …) |
| Branches `research/*` | Rechercheergebnisse mit Quellenangaben, auf die sich die Entscheidungen stützen |

Die Entscheidungen hinter der Spezifikation sind als geschlossene Issues zweier Wayfinder-Maps auf der Forgejo-Instanz des Autors dokumentiert. Diese Issues sind nicht öffentlich; die Spezifikation fasst ihre Ergebnisse vollständig zusammen.

## Voraussetzungen

- Claude Code
- Python 3.8 oder neuer
- OpenSSH-Client (`ssh`, `ssh-keygen`, `ssh-keyscan`) und Git
- Forgejo und Gitea: Docker auf dem Rechner der Instanz, direkt oder per `sudo` ohne Passwortabfrage nutzbar, dazu `docker compose` oder `docker-compose` für die Installation. Für Installationen ohne Container gibt es `--admin-exec`.
- GitLab: ein Admin-Token (Scope `api`) und für den MCP-Server Node.js ab 18.17.
- Für Clients auf anderen Rechnern: SSH-Zugang zum Host der Instanz.

forgejo-mcp und gitea-mcp müssen nicht vorab installiert sein. Fehlen sie, lädt der Skill die aktuelle Version aus den Releases des jeweiligen Projekts nach `~/.local/bin` und prüft die SHA-256-Prüfsumme.

## Installation

Den Skill für alle Claude-Code-Sitzungen verfügbar machen:

```sh
mkdir -p ~/.claude/skills
ln -s "$PWD/skill/gitlink" ~/.claude/skills/gitlink
```

Der symbolische Link sorgt dafür, dass Änderungen im Repository sofort wirken. Wer eine feste Kopie bevorzugt, kopiert das Verzeichnis stattdessen mit `cp -r skill/gitlink ~/.claude/skills/`. Ein alter Link `~/.claude/skills/igit` kann entfernt werden.

Eine Instanz muss nicht vorab laufen. Findet der Skill keine, bietet er an, Forgejo per Docker Compose in `~/forgejo` einzurichten (Ports 3000 und 2222).

## Benutzung

In Claude Code genügt eine Aufforderung in eigenen Worten, zum Beispiel „Richte Forgejo für Claude ein“ oder „Set up Gitea for Claude“. Alternativ ruft man den Skill direkt auf:

| Aufruf | Wirkung |
|---|---|
| `/gitlink einrichten` bzw. `/gitlink setup` | Findet eine laufende Instanz und erkennt ihre Plattform oder installiert auf Wunsch Forgejo. Richtet Bot-Konto, Client-Schlüssel, Host-Key-Pinning, Token und den MCP-Server `gitlink-<instanz>` ein. Fragt zum Schluss, welche bestehenden Repositories Claude nutzen darf. Bei GitLab fordert der erste Lauf den Admin-Token an. |
| `/gitlink repo` | Legt ein Repository an. Fragt nach Eigentümer (falls Organisationen oder Gruppen existieren), Name und Sichtbarkeit, trägt das Bot-Konto ein, legt einen Meilenstein an und verbindet das Arbeitsverzeichnis per SSH. Am Ende folgt die Aufforderung, ein Projektboard anzulegen. |
| `/gitlink abhaengigkeit` bzw. `/gitlink dependency` | Setzt, entfernt oder listet Abhängigkeiten zwischen Issues. |
| `/gitlink archivieren` bzw. `/gitlink archive` | Macht ein Repository schreibgeschützt; lässt sich wieder aufheben. |
| `/gitlink löschen` bzw. `/gitlink delete` | Löscht ein Repository nach ausdrücklicher Bestätigung, auf Wunsch samt verbundenem lokalem Verzeichnis. Das Verzeichnis wird nur gelöscht, wenn es auf dieses Repository zeigt und keine ungesicherten Änderungen oder ungepushten Commits enthält. |
| `/gitlink widerrufen` bzw. `/gitlink revoke` | Entzieht einem einzelnen Claude-Client den Zugriff, indem Token und SSH-Schlüssel gelöscht werden. Andere Clients bleiben unberührt. |

Am Ende von `einrichten` und `repo` empfiehlt der Skill die [Skills von Matt Pocock](https://github.com/mattpocock/skills), bietet an, sie als Plugin zu installieren, und fragt, ob ein Vorhaben mit `/wayfinder` geplant werden soll.

Wird der MCP-Server neu registriert oder geändert, muss Claude Code einmal neu gestartet werden; der Skill sagt dann Bescheid. Alle Unterbefehle lassen sich gefahrlos wiederholen; sie legen nur an, was fehlt.

Das Skript lässt sich auch direkt aufrufen, etwa zur Fehlersuche. `python3 skill/gitlink/gitlink.py --help` listet die Unterbefehle; jeder gibt ein JSON-Objekt aus.

## Sicherheit

- Bei Forgejo und Gitea nutzt der Skill Admin-Rechte nur während eines Laufs und löscht den dafür erzeugten Admin-Token am Ende wieder. Bei GitLab bleibt der vom Betreiber abgelegte Admin-Token gespeichert, weil GitLab keinen Weg bietet, ihn ohne Handarbeit neu zu erzeugen.
- Das Bot-Konto `claude-bot` sieht nur Repositories, in die es ausdrücklich eingetragen ist (Forgejo/Gitea: `restricted`; GitLab: Service Account).
- Jeder Claude-Client hat einen eigenen Token und einen eigenen SSH-Schlüssel.
- Geheimnisse liegen nur in Dateien, die allein der eigene Benutzer lesen kann (`~/.config/gitlink/`, `~/.ssh/`). Sie erscheinen nie im Chat und nicht in `~/.claude.json`.
- Tokens gehen nur über Loopback, HTTPS oder einen SSH-Tunnel, nie über unverschlüsseltes HTTP im Netz.
- Findet der Skill Schwächen einer Instanz, etwa ein leeres `SECRET_KEY`, meldet er sie, ändert aber nichts.

## Tests

```sh
python3 -m unittest tests/test_gitlink.py
```

Die Unit-Tests brauchen weder Docker noch eine echte Instanz; GitLab wird dabei durch einen nachgebauten API-Server ersetzt. Den vollständigen Ablauf haben Wegwerf-Instanzen von Forgejo 16 und Gitea 28 in einem abgeschotteten Home-Verzeichnis geprüft. Dieser Test ist nicht automatisiert, und gegen eine echte GitLab-Instanz fand keiner statt.
