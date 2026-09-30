---
name: igit
description: Forgejo + Claude einrichten / set up Forgejo for Claude. Use when the user wants to connect Claude to a Forgejo instance (einrichten, setup, install Forgejo), create a Forgejo repository for the current directory (Repo anlegen, create repo), or revoke a Claude client's access (widerrufen, revoke).
---

# igit

Der Skill richtet die Zusammenarbeit zwischen einer Forgejo-Instanz und Claude ein. Alles Deterministische erledigt das mitgelieferte Skript `igit.py` im Basisverzeichnis dieses Skills. Deine Aufgabe ist es, die Rückfragen zu stellen und das Skript mit den Antworten aufzurufen.

## Sprache

Antworte in der Sprache des Betreibers. Übergib dem Skript immer `--lang de` oder `--lang en` passend dazu. Alle Unterbefehle haben einen deutschen und einen englischen Namen (`einrichten`/`setup`, `widerrufen`/`revoke` …); nimm den zur Sprache passenden.

## Skript aufrufen

```
python3 <basisverzeichnis>/igit.py --lang <de|en> <unterbefehl> [optionen]
```

Jeder Aufruf gibt genau ein JSON-Objekt aus. Bei `"ok": true` stehen die Ergebnisse unter `result` und Hinweise unter `warnings`; gib jede Warnung dem Betreiber sinngemäß weiter. Bei `"ok": false` nennen `error` und `details`, was fehlt; die Tabelle unter [Fehlercodes](#fehlercodes) sagt, was du dann tust.

Geheimnisse (Tokens, Passwörter, private Schlüssel) liest und zeigst du nie. Das Skript legt sie in `0600`-Dateien ab und nennt nur Pfade.

## Unterbefehl: einrichten / setup

1. **Instanz finden:** `finden --dir <arbeitsverzeichnis>`.
   - Genau eine Instanz: weiter mit Schritt 3.
   - Mehrere: frage, welche gemeint ist.
   - Keine: frage, ob und wo eine Instanz läuft (Adresse; bei einem anderen Rechner zusätzlich den SSH-Host, über den der Betreiber dorthin kommt) oder ob du eine installieren sollst.
2. **Installieren (nur auf Wunsch):** frage Benutzername und E-Mail des Betreiber-Kontos, dann `installieren --operator <name> --email <mail>`. Standard sind `~/forgejo` und die Ports 3000/2222; nur bei `port_busy` fragst du nach anderen Ports (`--web-port`, `--ssh-port`). Nenne dem Betreiber danach den Pfad der Passwortdatei aus `result.password_file`.
3. **Einrichten:** `einrichten --url <url>`. Läuft die Instanz auf einem anderen Rechner, zusätzlich `--ssh-host <host>`; die URL ist dann die Adresse, unter der Forgejo auf diesem Rechner erreichbar ist (meist `http://localhost:3000`).
4. **Abgleich:** Enthält `result.missing_repos` Einträge, zeige die Liste und frage, welche Repos Claude nutzen darf. Für die gewählten: `freigeben <eigentümer/repo> …`.
5. **Abschluss:** fasse zusammen (Instanz, Bot-Konto, SSH-Alias, MCP-Server) und sage, dass der MCP-Server erst nach einem Neustart von Claude Code verfügbar ist.

Fertig ist der Unterbefehl, wenn `einrichten` mit `"ok": true` zurückkam, jede Warnung weitergegeben und über jedes Repo aus `missing_repos` entschieden ist.

## Unterbefehl: repo

1. `orgs` aufrufen. Hat der Betreiber Organisationen, frage, ob das Repo unter seinem Konto oder einer Organisation liegen soll.
2. Frage **immer** nach Name und Sichtbarkeit (privat oder öffentlich).
3. `repo --name <name> --privat|--oeffentlich [--owner <org>] --dir <arbeitsverzeichnis>`. Bei `repo_exists` frage, ob das bestehende Repo eingerichtet werden soll; wenn ja, mit `--existing-ok` wiederholen.
4. Gib zum Schluss `result.board_instruction` an den Betreiber weiter: Das Projektboard legt er selbst an, weil Forgejo dafür keine API hat.

Ab jetzt ordnest du jedes Issue, das du in diesem Repo anlegst, dem Meilenstein aus `result.milestone_id` zu. Das Skript hat dazu einen Hinweis in die `CLAUDE.md` des Arbeitsverzeichnisses geschrieben.

## Unterbefehl: widerrufen / revoke

1. `widerrufen` ohne `--client` aufrufen; die Antwort `client_required` listet die bekannten Clients in `details.clients` und den eigenen in `details.this_client`.
2. Frage, welcher Client widerrufen werden soll.
3. `widerrufen --client <name>`; ist es der eigene Client, zusätzlich `--lokal`, damit auch Schlüssel, Token-Datei, SSH-Eintrag und MCP-Server auf diesem Rechner entfernt werden.

## Fehlercodes

| `error` | Was du tust |
|---|---|
| `operator_ambiguous` | Frage, welches Admin-Konto aus `details.admins` der Betreiber ist; wiederhole mit `--operator`. |
| `instance_ambiguous` | Frage, welche Instanz aus `details.instances`; wiederhole mit `--instanz`. |
| `no_instance` | Führe zuerst `einrichten` aus. |
| `owner_required` | Frage nach dem Eigentümer (Betreiber oder eine Organisation aus `details.orgs`). |
| `port_busy` | Schlage die Ports aus `details.free` vor und frage. |
| `no_admin_access` | Frage, in welchem Container Forgejo läuft (`--container`) oder mit welchem Befehl die Forgejo-CLI aufgerufen wird (`--admin-exec`). |
| `insecure_url` | Die Instanz ist nur per unverschlüsseltem HTTP über das Netz erreichbar. Frage nach dem SSH-Host für einen Tunnel (`--ssh-host`) oder einer HTTPS-Adresse. |
| alle anderen | Gib `message` weiter und frage, wie der Betreiber fortfahren will. |
