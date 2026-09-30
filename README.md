# igit

`igit` ist ein geplanter Claude-Code-Skill, der die Ersteinrichtung zwischen einer selbst betriebenen Forgejo-Instanz und Claude automatisiert. Nach einem Lauf kann Claude über ein eigenes Bot-Konto Repositories anlegen, per SSH pushen und Issues verwalten, ohne dass Schlüssel, Tokens oder Remotes von Hand übertragen werden.

## Status

**Der Skill ist noch nicht umgesetzt.** Dieses Repository enthält bisher nur die Spezifikation und die Entscheidungen, die zu ihr geführt haben. Die Abschnitte zu Installation und Benutzung beschreiben den geplanten Stand gemäß Spezifikation.

## Inhalt

| Pfad | Inhalt |
|---|---|
| [`docs/spec-igit-skill.md`](docs/spec-igit-skill.md) | Spezifikation des Skills: Ablauf, Dateien, Sicherheitsregeln, Umfang |
| [`CONTEXT.md`](CONTEXT.md) | Glossar der Fachbegriffe (Instanz, Betreiber, Bot-Konto, Client-Schlüssel …) |
| [`CLAUDE.md`](CLAUDE.md) | Arbeitsanweisungen für Claude in diesem Repository |
| Branches `research/*` | Rechercheergebnisse mit Quellenangaben, auf die sich die Entscheidungen stützen |

Die Entscheidungen selbst sind als geschlossene Issues im Meilenstein „Wayfinder: Zero-Touch Forgejo + Claude“ dokumentiert. Die Übersicht bietet die Map [Wayfinder: Zero-Touch Forgejo + Claude](http://localhost:3000/dreamer/igit/issues/1).

## Voraussetzungen (geplant)

- Claude Code
- Python 3 (nur Standardbibliothek)
- OpenSSH-Client (`ssh`, `ssh-keygen`, `ssh-keyscan`)
- Docker mit Compose, auf dem Rechner der Instanz; nur nötig, wenn der Skill Forgejo installieren soll oder eine Instanz im Container betrieben wird
- Für Clients auf anderen Rechnern: SSH-Zugang zum Host der Instanz

## Installation (geplant)

Die Spezifikation legt die Installation des Skills selbst nicht fest. Vorgesehen ist, das Skill-Verzeichnis (`SKILL.md` und `igit.py`) nach `~/.claude/skills/igit/` zu kopieren, damit der Skill in allen Claude-Code-Sitzungen verfügbar ist.

Forgejo muss nicht vorab installiert sein. Findet der Skill keine Instanz, bietet er an, eine per Docker Compose in `~/forgejo` einzurichten (Ports 3000 und 2222).

## Benutzung (geplant)

Der Skill hat drei Unterbefehle, die in Claude Code aufgerufen werden:

- **`/igit einrichten`** findet eine laufende Instanz oder installiert auf Wunsch eine neue. Anschließend richtet er das Bot-Konto, den Client-Schlüssel, das Host-Key-Pinning, den Token und forgejo-mcp ein. Zum Schluss fragt er, welche bestehenden Repositories für Claude freigegeben werden sollen. Der Befehl kann gefahrlos erneut ausgeführt werden; er legt nur an, was fehlt.
- **`/igit repo`** legt ein Repository an. Er fragt nach Eigentümer, Name und Sichtbarkeit, trägt das Bot-Konto mit Schreibrecht ein, legt einen Meilenstein an und verbindet das Arbeitsverzeichnis per SSH mit dem Repository. Am Ende fordert er dazu auf, in der Forgejo-Oberfläche ein Projektboard anzulegen, weil Forgejo dafür keine API bietet.
- **`/igit widerrufen`** entzieht einem einzelnen Claude-Client den Zugriff, indem er dessen Token und SSH-Schlüssel löscht. Andere Clients bleiben unberührt.

Alle Geheimnisse landen in Dateien, die nur der eigene Benutzer lesen kann, unter `~/.config/igit/` und `~/.ssh/`. Admin-Rechte nutzt der Skill nur während eines Laufs und löscht den dafür erzeugten Admin-Token danach wieder.
