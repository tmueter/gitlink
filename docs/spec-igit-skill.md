# Spezifikation: Skill `igit`

Diese Spezifikation fasst die Entscheidungen der Wayfinder-Map [Wayfinder: Zero-Touch Forgejo + Claude](http://localhost:3000/dreamer/igit/issues/1) zusammen. Jede Entscheidung verweist auf das Ticket, in dem sie begründet ist. Begriffe folgen dem Glossar in [`CONTEXT.md`](../CONTEXT.md).

Punkte, die in der Map nicht entschieden wurden, aber für die Umsetzung eine Festlegung brauchen, sind mit **[Vorschlag]** markiert. Punkte, deren Verhalten nicht geprüft wurde, sind mit **[Unsicher]** markiert.

## 1. Zweck

Der Skill `igit` automatisiert die Ersteinrichtung zwischen einer Forgejo-Instanz und Claude. Nach einem Lauf kann Claude über ein eigenes Bot-Konto Repositories anlegen, per SSH pushen und Issues sowie Meilensteine verwalten, ohne dass der Betreiber Schlüssel, Tokens oder Remotes von Hand überträgt.

Der Betreiber handelt nur an drei Stellen selbst: Er ruft den Skill auf, beantwortet dessen Rückfragen und legt am Ende das Projektboard in der Forgejo-Oberfläche an.

Forgejo wird nicht verändert. Es gibt keinen Fork ([Forgejo forken oder Zero-Touch als externe Werkzeuge bauen?](http://localhost:3000/dreamer/igit/issues/5)). Stößt die Umsetzung auf eine echte Lücke in Forgejo, wird sie upstream eingereicht.

## 2. Aufbau

Der Skill besteht aus zwei Teilen ([Welche Teile des Skills sind Anweisung, welche ein mitgeliefertes Skript?](http://localhost:3000/dreamer/igit/issues/13)):

- **Skill-Anweisungen (`SKILL.md`):** Claude stellt die Rückfragen an den Betreiber und ruft mit den Antworten das Skript auf. Claude führt keine API-Aufrufe und keine Dateioperationen selbst aus.
- **Mitgeliefertes Skript (`igit.py`):** Python 3, ausschließlich Standardbibliothek. Es erledigt alle deterministischen Schritte: API-Aufrufe, Container-Befehle, Schlüssel, Dateien und Konfiguration. Jeder Schritt ist idempotent: Das Skript prüft zuerst den Ist-Zustand und legt nur an, was fehlt. Ein wiederholter Lauf ändert nichts Bestehendes.

Der Skill hat drei Unterbefehle:

| Unterbefehl | Zweck |
|---|---|
| `einrichten` | Instanz finden oder installieren, Bot-Konto, Client-Schlüssel, Host-Key-Pinning, Token und forgejo-mcp einrichten, Abgleich bestehender Repos |
| `repo` | Ein Repository anlegen, das Bot-Konto eintragen, Meilenstein anlegen, Arbeitsverzeichnis verbinden |
| `widerrufen` | Einen Claude-Client widerrufen, ohne andere zu beeinträchtigen |

## 3. Dateien auf dem Claude-Client

Alle Geheimnisse liegen in eigenen Dateien mit Modus `0600` in Verzeichnissen mit Modus `0700`. Kein Geheimnis erscheint im Chat, in `~/.claude.json` oder in einem Repository.

| Pfad | Inhalt |
|---|---|
| `~/.config/igit/<instanz>/config.json` | URL, SSH-Alias, Container-Name, Name des Bot-Kontos, Name dieses Clients, bei Fernzugriff der SSH-Host |
| `~/.config/igit/<instanz>/token` | Token des Bot-Kontos für diesen Client |
| `~/.config/igit/<instanz>/start-mcp` | Starter für forgejo-mcp (ausführbar, enthält keinen Token) |
| `~/.ssh/igit_<instanz>` und `.pub` | Client-Schlüssel (ed25519) |
| `~/.ssh/config` | `Host`-Eintrag `igit-<instanz>` |
| `~/.ssh/known_hosts` | Gepinnter Host-Key der Instanz |

`<instanz>` ist ein kurzer Name der Instanz. **[Vorschlag]** Er leitet sich aus Host und Port ab (z. B. `localhost-3000`), und der Skill fragt nur bei einer Kollision nach.

## 4. Unterbefehl `einrichten`

### 4.1 Instanz finden

Quelle: [Wie erkennt der Skill, ob und wo eine Instanz läuft?](http://localhost:3000/dreamer/igit/issues/9)

Das Skript sucht in dieser Reihenfolge:

1. gespeicherte Konfiguration unter `~/.config/igit/`,
2. Git-Remote des aktuellen Arbeitsverzeichnisses,
3. laufende Docker-Container mit einem Forgejo-Image,
4. `http://localhost:3000`.

Ein Kandidat gilt als Forgejo-Instanz, wenn `GET /api/v1/version` eine Forgejo-Version liefert. Findet das Skript genau eine Instanz, fährt es fort. Findet es mehrere, fragt Claude, welche gemeint ist. Findet es keine, fragt Claude, ob und wo eine Instanz läuft oder ob der Skill eine installieren soll.

### 4.2 Instanz installieren (nur auf Wunsch)

Quellen: [Wie installiert der Skill Forgejo, wenn keine Instanz läuft?](http://localhost:3000/dreamer/igit/issues/10), [Welche Wege gibt es, Forgejo 16 nicht-interaktiv zu installieren?](http://localhost:3000/dreamer/igit/issues/8)

- Installationsweg ist Docker Compose mit dem rootful Image `codeberg.org/forgejo/forgejo:16`. Docker muss vorhanden sein. Fehlt Docker, bricht der Skill mit einer klaren Meldung ab.
- Das Verzeichnis ist `~/forgejo`. Die Ports sind 3000 für Web und 2222 für SSH. Nur wenn ein Port belegt ist, fragt Claude nach einem anderen.
- Das Skript startet Compose mit dem eigenen Projektnamen `igit-<instanz>` und bricht ab, wenn dieses Projekt schon existiert. Ohne eigenen Namen leitet Compose ihn aus dem Verzeichnisnamen ab und würde fremde Container desselben Projekts neu erzeugen.
- Die Compose-Datei setzt `FORGEJO__security__INSTALL_LOCK=true` und einen vom Skript erzeugten, zufälligen `FORGEJO__security__SECRET_KEY`. Ein leerer `SECRET_KEY` ist ausgeschlossen, weil Forgejo sonst stillschweigend einen öffentlich bekannten Standardschlüssel verwendet.
- Den SSH-Port für Clone-URLs setzt das Skript über `FORGEJO__server__SSH_PORT`, nicht über die Template-Variable `SSH_PORT`, weil diese auch den `sshd` im Container verschiebt.
- Das Betreiber-Konto entsteht mit `docker exec -u git <container> forgejo admin user create --admin`. **[Vorschlag]** Claude fragt Benutzername und E-Mail. Das Skript erzeugt ein zufälliges Passwort, legt es in `~/.config/igit/<instanz>/betreiber-passwort` (0600) ab und nennt dem Betreiber nur den Pfad.

Danach geht es weiter wie bei einer gefundenen Instanz.

### 4.3 Gesundheitsprüfung

Das Skript prüft eine gefundene Instanz auf bekannte Schwächen, insbesondere ein leeres `SECRET_KEY`. Befunde werden gemeldet, samt Folgen. Das Skript ändert nichts an der Instanz, weil ein nachträglich gesetzter `SECRET_KEY` bereits verschlüsselte Daten unlesbar macht ([Wie erkennt der Skill, ob und wo eine Instanz läuft?](http://localhost:3000/dreamer/igit/issues/9)).

### 4.4 Vorübergehender Admin-Token

Quelle: [Welchen Zugriff erhält jeder Claude-Client, und wie wird einer widerrufen?](http://localhost:3000/dreamer/igit/issues/7)

- Das Skript erzeugt für die Dauer des Laufs einen Admin-Token des Betreibers mit `docker exec -u git <container> forgejo admin user generate-access-token -u <betreiber> --raw`, mit den Scopes `write:admin`, `write:repository`, `write:user` und `write:issue`.
- Der Token existiert nur im Speicher des Skripts und wird am Ende des Laufs gelöscht, auch wenn der Lauf fehlschlägt. Im Alltag hat Claude keine Admin-Rechte.
- **[Vorschlag]** Der Token-Name enthält einen Zeitstempel (`igit-lauf-<zeitstempel>`). Beim Start löscht das Skript übrig gebliebene Tokens dieses Namensmusters aus abgebrochenen Läufen.

### 4.5 Bot-Konto

- Das Skript legt das Bot-Konto an, falls es fehlt. **[Vorschlag]** Name `claude-bot`, voller Name „Claude (Bot)“.
- Forgejo kennt keinen zugänglichen Bot-Kontotyp. Das Bot-Konto ist daher ein normales Konto, gehärtet mit `restricted: true`, `max_repo_creation: 0` und `allow_create_organization: false`. Wegen `restricted` sieht es nur Repositories, in die es ausdrücklich eingetragen ist ([Was kann Forgejo für Bootstrap und Registrierung ohne Codeänderungen automatisieren?](http://localhost:3000/dreamer/igit/issues/2)).
- Das Passwort ist zufällig und wird nicht gespeichert. Das Bot-Konto meldet sich nur per Token und SSH an. **[Unsicher]** `prohibit_login` wird nicht gesetzt, weil nicht geprüft ist, ob Token und SSH danach weiter funktionieren.

### 4.6 Client-Schlüssel und Host-Key-Pinning

- Das Skript erzeugt den Client-Schlüssel `~/.ssh/igit_<instanz>` (ed25519), falls er fehlt, und hinterlegt den öffentlichen Teil mit `POST /admin/users/<bot>/keys` am Bot-Konto. Der Titel des Schlüssels ist der Name des Clients, damit der Widerruf ihn eindeutig findet.
- Den Host-Key liest das Skript auf dem Host der Instanz: bevorzugt die Dateien `ssh_host_*_key.pub` im Datenvolume, sonst `ssh-keyscan -p <ssh-port> localhost` über Loopback. Es trägt ihn als `[<host>]:<port>` in `~/.ssh/known_hosts` ein.
- Der `Host`-Eintrag `igit-<instanz>` in `~/.ssh/config` setzt `HostName`, `Port`, `User git`, `IdentityFile ~/.ssh/igit_<instanz>`, `IdentitiesOnly yes` und `StrictHostKeyChecking yes`.

### 4.7 Token des Clients

- Jeder Claude-Client erhält genau einen Token des Bot-Kontos, erzeugt mit `POST /admin/users/<bot>/tokens`. Name `igit-<client>`, Scopes `write:repository`, `write:issue` und `read:user`. Der Token ist nicht auf einzelne Repositories beschränkt, weil forgejo-mcp nur einen Token pro Instanz nimmt. Die Beschränkung ergibt sich aus dem `restricted`-Bot-Konto.
- `read:user` ist enthalten, damit forgejo-mcp das eigene Konto abfragen kann. Mit diesen Scopes meldet `claude mcp get` den Server im Test als verbunden; ob es ohne `read:user` ginge, ist nicht geprüft.
- Der Token wird nach `~/.config/igit/<instanz>/token` geschrieben. Tokens laufen nicht ab und werden nicht rotiert. Sie gelten bis zum Widerruf.

### 4.8 forgejo-mcp einrichten

Quelle: [Wie spricht Claude jenseits von Git mit der Instanz?](http://localhost:3000/dreamer/igit/issues/6), Recherche in [Welche bestehenden Integrationen lassen Claude Code eine Forgejo-Instanz steuern?](http://localhost:3000/dreamer/igit/issues/4)

- Pro Instanz gibt es einen MCP-Server-Eintrag, registriert mit `claude mcp add --scope user forgejo-<instanz> -- ~/.config/igit/<instanz>/start-mcp`.
- Der Starter liest den Token aus der Datei, übergibt ihn als `FORGEJO_ACCESS_TOKEN` und startet forgejo-mcp mit `--url`. Bei einem Client auf einem anderen Rechner öffnet er vorher den SSH-Tunnel (siehe Abschnitt 7).
- Das Skript installiert forgejo-mcp als Binary aus den Releases des Projekts nach `~/.local/bin`, falls es fehlt, und prüft die SHA-256-Prüfsumme gegen die Prüfsummendatei des Releases. Eine cosign-Signaturprüfung findet nicht statt; das Skript weist darauf hin.

### 4.9 Abgleich bestehender Repositories

Das Skript listet die Repositories des Betreibers und seiner Organisationen, in denen das Bot-Konto nicht eingetragen ist. Claude fragt den Betreiber, welche davon freigegeben werden sollen. Für die gewählten Repositories trägt das Skript das Bot-Konto mit Schreibrecht ein ([Welche Schritte führt der Skill beim Anlegen eines Repos aus?](http://localhost:3000/dreamer/igit/issues/12)). Der Abgleich läuft bei jedem Aufruf von `einrichten`. Einen dauerhaft laufenden Dienst gibt es nicht.

## 5. Unterbefehl `repo`

Quelle: [Welche Schritte führt der Skill beim Anlegen eines Repos aus?](http://localhost:3000/dreamer/igit/issues/12), [Was bedeutet „Projekt“, und wie bildet der Skill es ohne Projekt-API ab?](http://localhost:3000/dreamer/igit/issues/11)

1. **Eigentümer:** Hat der Betreiber Organisationen, fragt Claude, ob das Repository unter seinem Konto oder unter einer Organisation liegen soll. Sonst liegt es unter dem Konto des Betreibers.
2. **Name und Sichtbarkeit:** Claude fragt beides jedes Mal.
3. **Anlegen:** Das Skript legt das Repository mit einem vorübergehenden Admin-Token an (wie in 4.4) und löscht den Token am Ende.
4. **Bot-Konto eintragen:** als Mitarbeiter mit Schreibrecht, auch bei Organisations-Repositories. Kein Team mit Zugriff auf alle Repositories, damit der Zugriff genauso eng bleibt. (Diese Festlegung ist eine Annahme und vom Betreiber nicht ausdrücklich entschieden.)
5. **Meilenstein:** Das Skript legt einen Meilenstein an. **[Vorschlag]** Er trägt den Namen des Repositorys.
6. **Arbeitsverzeichnis verbinden:** Falls nötig führt das Skript `git init` aus. Es setzt `origin` auf `igit-<instanz>:<eigentümer>/<name>.git`.
7. **Zuordnung neuer Issues:** Claude ordnet jedes Issue, das es in diesem Repository anlegt, dem Meilenstein zu. **[Vorschlag]** Damit spätere Sitzungen das wissen, ergänzt das Skript die `CLAUDE.md` des Arbeitsverzeichnisses um einen Hinweis mit Repository und Meilenstein.
8. **Anweisung am Ende:** Claude weist den Betreiber an, in der Forgejo-Oberfläche ein Projektboard anzulegen und die Issues des Meilensteins zu übernehmen. Forgejo 16 hat keine API für Projekte. **[Unsicher]** Ob das Board alle Issues eines Meilensteins auf einmal übernehmen kann, ist nicht geprüft.

## 6. Unterbefehl `widerrufen`

Quelle: [Welchen Zugriff erhält jeder Claude-Client, und wie wird einer widerrufen?](http://localhost:3000/dreamer/igit/issues/7)

- Claude fragt, welcher Client widerrufen werden soll. Das Skript listet dazu die Tokens `igit-<client>` des Bot-Kontos.
- Das Skript löscht mit einem vorübergehenden Admin-Token den Token und den SSH-Schlüssel genau dieses Clients am Bot-Konto. Andere Clients bleiben unberührt.
- Wird der Befehl auf dem widerrufenen Client selbst ausgeführt, entfernt das Skript zusätzlich die lokalen Dateien aus Abschnitt 3 und den MCP-Server-Eintrag.

## 7. Clients auf anderen Rechnern

Quelle: [Wie registriert der Skill einen Claude-Client auf einem anderen Rechner?](http://localhost:3000/dreamer/igit/issues/14)

- Das Anfangsvertrauen stammt aus dem bestehenden SSH-Zugang des Betreibers zum Host der Instanz. Das Skript führt alle Admin-Schritte über diese Verbindung aus (`ssh <host> docker exec …`). Es gibt keinen Einmal-Code und keinen manuellen Schritt.
- Den Host-Key der Instanz liest das Skript auf dem Host und überträgt ihn über dieselbe SSH-Verbindung.
- forgejo-mcp erreicht die API über einen SSH-Tunnel, den der Starter vor dem Start öffnet (`ssh -L <lokaler-port>:localhost:<web-port> <host>`). forgejo-mcp spricht dann mit `http://localhost:<lokaler-port>`. Ein TLS-Zertifikat ist nicht nötig, und kein Token geht unverschlüsselt über das Netz.
- Git-Zugriffe gehen direkt per SSH an den SSH-Port der Instanz, abgesichert durch den gepinnten Host-Key.

## 8. Sicherheitsregeln

- Admin-Rechte bestehen nur während eines Skill-Laufs. Der Admin-Token wird am Ende immer gelöscht.
- Das Bot-Konto ist `restricted` und hat pro Repository höchstens Schreibrecht.
- Jeder Client hat einen eigenen Token und einen eigenen SSH-Schlüssel, damit er einzeln widerrufen werden kann.
- Geheimnisse liegen nur in `0600`-Dateien und erscheinen nie im Chat.
- Tokens gehen nur über Loopback oder einen SSH-Tunnel über das Netz, nie über unverschlüsseltes HTTP.
- Kein SSH-Verbindungsaufbau ohne gepinnten Host-Key.

## 9. Außerhalb des Umfangs

- Claude als Akteur innerhalb von Forgejo, etwa als Review-Bot.
- Ein dauerhaft laufender Webhook-Empfänger. Der Abgleich beim nächsten Lauf genügt.
- Ablauf und Rotation von Tokens.
- Weitergabe an andere Personen, also Paketierung, Dokumentation und Upgrade-Pfade für Dritte.
- Anlegen von Projektboards, weil Forgejo 16 dafür keine API hat.
