# igit

`igit` ist ein Claude-Code-Skill, der die Ersteinrichtung zwischen einer selbst betriebenen GIT-Instanz (Gitea/Forgeo) und Claude automatisiert. Nach einem Lauf kann Claude über ein eigenes Bot-Konto Repositories anlegen, per SSH pushen und Issues verwalten, ohne dass Schlüssel, Tokens oder Remotes von Hand übertragen werden.

Der Skill versteht Deutsch und Englisch: Er antwortet in der Sprache, in der man ihn anspricht, und alle Unterbefehle haben einen deutschen und einen englischen Namen.

## Inhalt

| Pfad | Inhalt |
|---|---|
| [`skill/igit/SKILL.md`](skill/igit/SKILL.md) | Anweisungen für Claude: Rückfragen und Abläufe |
| [`skill/igit/igit.py`](skill/igit/igit.py) | Skript für alle deterministischen Schritte (Python 3, nur Standardbibliothek) |
| [`tests/test_igit.py`](tests/test_igit.py) | Unit-Tests, laufen ohne Docker und ohne Forgejo |
| [`docs/spec-igit-skill.md`](docs/spec-igit-skill.md) | Spezifikation: Ablauf, Dateien, Sicherheitsregeln, Umfang |
| [`CONTEXT.md`](CONTEXT.md) | Glossar der Fachbegriffe (Instanz, Betreiber, Bot-Konto, Client-Schlüssel …) |
| Branches `research/*` | Rechercheergebnisse mit Quellenangaben, auf die sich die Entscheidungen stützen |

Die Entscheidungen hinter der Spezifikation sind als geschlossene Issues dokumentiert; die Übersicht bietet die Map [Wayfinder: Zero-Touch Forgejo + Claude](http://localhost:3000/dreamer/igit/issues/1).

## Voraussetzungen

- Claude Code
- Python 3.8 oder neuer
- OpenSSH-Client (`ssh`, `ssh-keygen`, `ssh-keyscan`) und Git
- Auf dem Rechner der Instanz: Docker, direkt oder per `sudo` ohne Passwortabfrage nutzbar, sowie `docker compose` oder `docker-compose`. Der Skill verwaltet Instanzen im offiziellen Forgejo-Container; für andere Installationen gibt es `--admin-exec`.
- Für Clients auf anderen Rechnern: SSH-Zugang zum Host der Instanz

forgejo-mcp muss nicht vorab installiert sein. Fehlt es, lädt der Skill die aktuelle Version aus den Releases des Projekts nach `~/.local/bin` und prüft die SHA-256-Prüfsumme.

## Installation

Den Skill für alle Claude-Code-Sitzungen verfügbar machen:

```sh
mkdir -p ~/.claude/skills
ln -s "$PWD/skill/igit" ~/.claude/skills/igit
```

Der symbolische Link sorgt dafür, dass Änderungen im Repository sofort wirken. Wer eine feste Kopie bevorzugt, kopiert das Verzeichnis stattdessen mit `cp -r skill/igit ~/.claude/skills/`.

Forgejo selbst muss nicht vorab installiert sein. Findet der Skill keine Instanz, bietet er an, eine per Docker Compose in `~/forgejo` einzurichten (Ports 3000 und 2222).

## Benutzung

In Claude Code genügt eine Aufforderung in eigenen Worten, zum Beispiel „Richte Forgejo für Claude ein“ oder „Set up Forgejo for Claude“. Alternativ ruft man den Skill direkt auf:

| Aufruf | Wirkung |
|---|---|
| `/igit einrichten` bzw. `/igit setup` | Findet eine laufende Instanz oder installiert auf Wunsch eine neue. Richtet Bot-Konto, Client-Schlüssel, Host-Key-Pinning, Token und den MCP-Server `forgejo-<instanz>` ein. Fragt zum Schluss, welche bestehenden Repositories Claude nutzen darf. |
| `/igit repo` | Legt ein Repository an. Fragt nach Eigentümer (falls Organisationen existieren), Name und Sichtbarkeit, trägt das Bot-Konto mit Schreibrecht ein, legt einen Meilenstein an und verbindet das Arbeitsverzeichnis per SSH. Am Ende folgt die Aufforderung, in Forgejo ein Projektboard anzulegen, weil Forgejo dafür keine API bietet. |
| `/igit archivieren` bzw. `/igit archive` | Macht ein Repository schreibgeschützt; lässt sich wieder aufheben. |
| `/igit löschen` bzw. `/igit delete` | Löscht ein Repository nach ausdrücklicher Bestätigung endgültig, auf Wunsch samt verbundenem lokalem Verzeichnis. Das Verzeichnis wird nur gelöscht, wenn es auf dieses Repository zeigt und keine ungesicherten Änderungen oder ungepushten Commits enthält. |
| `/igit widerrufen` bzw. `/igit revoke` | Entzieht einem einzelnen Claude-Client den Zugriff, indem Token und SSH-Schlüssel gelöscht werden. Andere Clients bleiben unberührt. |

Nach `einrichten` muss Claude Code einmal neu gestartet werden, damit der MCP-Server verfügbar ist. Alle Unterbefehle lassen sich gefahrlos wiederholen; sie legen nur an, was fehlt.

Das Skript lässt sich auch direkt aufrufen, etwa zur Fehlersuche. `python3 skill/igit/igit.py --help` listet die Unterbefehle; jeder gibt ein JSON-Objekt aus.

## Sicherheit

- Admin-Rechte nutzt der Skill nur während eines Laufs. Den dafür erzeugten Admin-Token löscht er am Ende wieder.
- Das Bot-Konto `claude-bot` ist eingeschränkt (`restricted`) und sieht nur Repositories, in die es ausdrücklich eingetragen ist.
- Jeder Claude-Client hat einen eigenen Token und einen eigenen SSH-Schlüssel.
- Geheimnisse liegen nur in Dateien, die allein der eigene Benutzer lesen kann (`~/.config/igit/`, `~/.ssh/`). Sie erscheinen nie im Chat und nicht in `~/.claude.json`.
- Tokens gehen nur über Loopback oder einen SSH-Tunnel, nie über unverschlüsseltes HTTP im Netz.
- Findet der Skill Schwächen einer Instanz, etwa ein leeres `SECRET_KEY`, meldet er sie, ändert aber nichts.

## Tests

```sh
python3 -m unittest tests/test_igit.py
```

Die Unit-Tests brauchen weder Docker noch Forgejo. Den vollständigen Ablauf (installieren, einrichten, freigeben, repo, archivieren, löschen, widerrufen) hat eine Wegwerf-Instanz in einem abgeschotteten Home-Verzeichnis geprüft. Dieser Test ist nicht automatisiert.
