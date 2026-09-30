---
name: gitlink
description: Forgejo/Gitea/GitLab + Claude einrichten / set up Forgejo, Gitea or GitLab for Claude. Use when the user wants to connect Claude to a Forgejo, Gitea or self-hosted GitLab instance (einrichten, setup, install Forgejo), create a repository or connect the current directory to an existing one (Repo anlegen, verbinden, create repo, connect), set issue dependencies (Abhängigkeit, blocked by), archive or delete a repository (archivieren, löschen, archive, delete), or revoke a Claude client's access (widerrufen, revoke).
---

# gitlink

Der Skill richtet die Zusammenarbeit zwischen einer Instanz von Forgejo, Gitea oder selbst gehostetem GitLab und Claude ein. Die Plattform erkennt das Skript selbst (`result.platform`). Alles Deterministische erledigt das mitgelieferte Skript `gitlink.py` im Basisverzeichnis dieses Skills. Deine Aufgabe ist es, die Rückfragen zu stellen und das Skript mit den Antworten aufzurufen.

## Sprache

Antworte in der Sprache des Betreibers. Übergib dem Skript immer `--lang de` oder `--lang en` passend dazu. Alle Unterbefehle haben einen deutschen und einen englischen Namen (`einrichten`/`setup`, `widerrufen`/`revoke` …); nimm den zur Sprache passenden.

## Skript aufrufen

```
python3 <basisverzeichnis>/gitlink.py --lang <de|en> <unterbefehl> [optionen]
```

Jeder Aufruf gibt genau ein JSON-Objekt aus. Bei `"ok": true` stehen die Ergebnisse unter `result` und Hinweise unter `warnings`; gib jede Warnung dem Betreiber sinngemäß weiter. Bei `"ok": false` nennen `error` und `details`, was fehlt; die Tabelle unter [Fehlercodes](#fehlercodes) sagt, was du dann tust.

Geheimnisse (Tokens, Passwörter, private Schlüssel) liest und zeigst du nie. Das Skript legt sie in `0600`-Dateien ab und nennt nur Pfade.

## Unterbefehl: einrichten / setup

1. **Instanz finden:** `finden --dir <arbeitsverzeichnis>`.
   - Genau eine Instanz: weiter mit Schritt 3. `result.instances[].platform` nennt die Plattform.
   - Mehrere: frage, welche gemeint ist.
   - Keine: frage, ob und wo eine Instanz läuft (Adresse; bei einem anderen Rechner zusätzlich den SSH-Host, über den der Betreiber dorthin kommt) oder ob du eine installieren sollst. Installiert wird immer Forgejo; Gitea und GitLab bedient der Skill nur, wenn sie schon laufen.
2. **Installieren (nur auf Wunsch):** frage Benutzername und E-Mail des Betreiber-Kontos, dann `installieren --operator <name> --email <mail>`. Standard sind `~/forgejo` und die Ports 3000/2222; nur bei `port_busy` fragst du nach anderen Ports (`--web-port`, `--ssh-port`). Nenne dem Betreiber danach den Pfad der Passwortdatei aus `result.password_file`.
3. **Einrichten:** `einrichten --url <url>`. Läuft die Instanz auf einem anderen Rechner, zusätzlich `--ssh-host <host>`; die URL ist dann die Adresse, unter der die Instanz auf diesem Rechner erreichbar ist (meist `http://localhost:3000`).
   - **GitLab:** Immer mit `--plattform gitlab`. Der Skill arbeitet dort ohne Token und ohne Bot, nur mit dem Konto des Betreibers per SSH. Ist der Web-Host nicht per SSH erreichbar (etwa hinter einem Anmelde-Proxy), gib die interne SSH-Adresse mit `--ssh-hostname` an.
     - Endet der Lauf mit `ssh_key_required`, halte an: Zeig dem Betreiber `details.public_key`, den Link `details.add_key_url` und den Titel `details.title`, damit er den Schlüssel in seinem GitLab-Konto einträgt. Nenne ihm auch `details.host_key_fingerprints` zum Vergleich mit der Seite `/help/instance_configuration` der Instanz. Warte auf seine Bestätigung und wiederhole dann `einrichten`.
     - Kommt `ssh_key_required` erneut, obwohl der Schlüssel eingetragen ist, läuft der Git-Zugang von GitLab meist auf einem anderen Port oder Host (z. B. GitLab im Container). Lass dir die URL unter **Code → Clone with SSH** eines Projekts nennen und wiederhole mit `--ssh-port` bzw. `--ssh-hostname`; der Skill pinnt die Host-Keys dann neu, und der Betreiber vergleicht die neuen Fingerprints.
     - Für GitLab entfallen Abgleich, MCP-Server und Matt-Pocock-Empfehlung.
   - **Anmelde-Proxy:** Endet der Lauf mit `auth_proxy`, steht vor der Instanz ein Proxy mit eigener Anmeldung (z. B. Microsoft Entra). Kein Token hilft dagegen. Erkläre das und frage nach einem Zugang ohne Proxy: VPN mit interner Adresse oder ein Rechner im Netz der Instanz (`--ssh-host`). Ist die Plattform bekannt, aber die Erkennung scheitert, übergib `--plattform gitlab`.
   - **Interne Zertifizierungsstelle:** Scheitert HTTPS an einem unbekannten Zertifikat (die Instanz wird dann nicht gefunden), frage nach dem Zertifikat der internen Stelle als PEM-Datei und übergib es mit `--ca-cert <datei>`. Der Skill vertraut ihm nur für diese Instanz; das System bleibt unverändert.
4. **Abgleich:** Enthält `result.missing_repos` Einträge, zeige die Liste und frage, welche Repos Claude nutzen darf. Für die gewählten: `freigeben <eigentümer/repo> …`.
5. **Abschluss:** fasse zusammen (Plattform, Instanz, Bot-Konto, SSH-Alias, MCP-Server). Den Neustart von Claude Code erwähnst du nur, wenn eine Warnung ihn verlangt.
6. [Matt-Pocock-Skills empfehlen](#matt-pocock-skills-empfehlen).

Fertig ist der Unterbefehl, wenn `einrichten` mit `"ok": true` zurückkam, jede Warnung weitergegeben, über jedes Repo aus `missing_repos` entschieden und die Empfehlung beantwortet ist.

## Unterbefehl: verbinden / connect

Verbindet das Arbeitsverzeichnis mit einem Repo, das der Betreiber selbst angelegt hat. Das ist bei GitLab der einzige Weg zu einem Repo.

1. Frage nach dem Pfad des Repos (`gruppe/…/name`) und dem Verzeichnis.
2. `verbinden --repo <pfad> --dir <verzeichnis>`. Bei `repo_no_access` gib die Meldung weiter: Das Repo fehlt, oder das Konto hat keinen Zugriff.

**Bei GitLab gilt danach:** Du leistest nur Hilfestellung. `git commit` und `git push` führst du nur aus, wenn der Betreiber es ausdrücklich verlangt. Auf GitLab selbst änderst du nichts (keine Issues, Merge Requests oder Einstellungen). Das Skript hat diese Regel auch in die `CLAUDE.md` des Verzeichnisses geschrieben.

## Unterbefehl: repo

1. `orgs` aufrufen. Hat der Betreiber Organisationen (bei GitLab: Gruppen, in denen er Owner ist), frage, ob das Repo unter seinem Konto oder dort liegen soll.
2. Frage **immer** nach Name und Sichtbarkeit (privat oder öffentlich).
3. `repo --name <name> --privat|--oeffentlich [--owner <org>] --dir <arbeitsverzeichnis>`. Bei `repo_exists` frage, ob das bestehende Repo eingerichtet werden soll; wenn ja, mit `--existing-ok` wiederholen.
4. Gib `result.board_instruction` an den Betreiber weiter: Das Projektboard legt er auf allen Plattformen selbst an.
5. [Matt-Pocock-Skills empfehlen](#matt-pocock-skills-empfehlen).

Ab jetzt ordnest du jedes Issue, das du in diesem Repo anlegst, dem Meilenstein aus `result.milestone_id` zu. Das Skript hat dazu einen Hinweis in die `CLAUDE.md` des Arbeitsverzeichnisses geschrieben.

## Unterbefehl: abhaengigkeit / dependency

Issue-Abhängigkeiten setzt du immer über das Skript, nicht über den MCP-Server; gitea-mcp kann sie nicht, und so verhält es sich überall gleich. Das Skript handelt als Bot.

- Anlegen: `abhaengigkeit --repo <eigentümer/name> --issue <blockiert> --blockiert-durch <blockierend>`
- Entfernen: zusätzlich `--entfernen`
- Auflisten: ohne `--blockiert-durch`; `result.blocked_by` nennt die blockierenden Issues.

Bei GitLab gehen blockierende Links laut Doku nur in Premium/Ultimate; `deps_unsupported` gibst du dann weiter.

## Matt-Pocock-Skills empfehlen

Letzter Schritt von `einrichten` und `repo`. Hat der Betreiber die Empfehlung in dieser Sitzung schon beantwortet, entfällt er.

1. Prüfe mit `claude plugin list`, ob `mattpocock-skills` installiert ist.
2. **Nicht installiert:** Empfiehl die Skills von Matt Pocock (https://github.com/mattpocock/skills) für die Planung und Umsetzung im neuen Repo, besonders `/wayfinder`, das eine grobe Idee in Entscheidungs-Tickets zerlegt. Frage, ob du sie installieren sollst. Bei Ja: `claude plugins install mattpocock-skills`, danach sage, dass die Skills nach einem Neustart von Claude Code verfügbar sind und `/mattpocock-skills:setup-matt-pocock-skills` sie einmalig für das Repo einrichtet.
3. Sind die Skills installiert, schon vorher oder gerade eben, frage, ob der Betreiber mit `/wayfinder` ein Vorhaben planen will, und wenn ja, welche Idee.
   - Skills waren schon installiert: rufe den Skill `mattpocock-skills:wayfinder` mit der Idee auf.
   - Skills wurden gerade erst installiert: nenne den Aufruf für nach dem Neustart, `/mattpocock-skills:wayfinder <idee>`.

## Unterbefehl: archivieren / archive

`archivieren --repo <eigentümer/name>` macht das Repo schreibgeschützt; `--rueckgaengig` hebt das wieder auf. Archivieren ist umkehrbar und braucht keine Bestätigung. Ist unklar, ob der Betreiber archivieren oder löschen will, frage nach und empfiehl Archivieren.

## Unterbefehl: löschen / delete

1. Sage dem Betreiber, dass Repo, Issues und Meilenstein endgültig verloren gehen (bei GitLab kann eine Warnung melden, dass es nur zum Löschen markiert wurde), und hol dir eine ausdrückliche Bestätigung für genau dieses Repo.
2. Frage, ob das verbundene lokale Verzeichnis mitgelöscht werden soll.
3. `loeschen --repo <eigentümer/name> --bestaetigen <eigentümer/name> [--dir <verzeichnis>]`. Das Skript löscht das Verzeichnis nur, wenn `origin` auf dieses Repo zeigt und nichts Ungesichertes darin liegt; sonst meldet es per Warnung, warum es das Verzeichnis stehen lässt. Gib die Warnung weiter und lösche das Verzeichnis nicht selbst.

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
| `repo_not_found` | Prüfe den Namen mit dem Betreiber (`eigentümer/name`). |
| `confirm_mismatch` | Hol dir die Bestätigung erneut und übergib bei `--bestaetigen` genau den Repo-Namen. |
| `owner_required` | Frage nach dem Eigentümer (Betreiber oder eine Organisation aus `details.orgs`). |
| `port_busy` | Schlage die Ports aus `details.free` vor und frage. |
| `no_admin_access` | Frage, in welchem Container Forgejo bzw. Gitea läuft (`--container`) oder mit welchem Befehl die CLI der Plattform aufgerufen wird (`--admin-exec`). |
| `auth_proxy` | Siehe „Anmelde-Proxy“ unter `einrichten`. |
| `ssh_key_required` | Siehe „GitLab“ unter `einrichten`. |
| `ssh_unreachable` | SSH ist nicht erreichbar. Frage, ob der Zugang (z. B. VPN) steht und wie die interne Adresse lautet (`--ssh-hostname`). |
| `gitlab_unsupported` | Bei GitLab gibt es nur `einrichten`, `verbinden` und `widerrufen`; erkläre das. |
| `repo_no_access` | Das Repo fehlt oder das Konto hat keinen Zugriff; der Betreiber legt es an bzw. klärt die Rechte. |
| `unsupported_platform` | Unter der Adresse läuft weder Forgejo noch Gitea noch GitLab; frage nach der richtigen Adresse. |
| `insecure_url` | Die Instanz ist nur per unverschlüsseltem HTTP über das Netz erreichbar. Frage nach dem SSH-Host für einen Tunnel (`--ssh-host`) oder einer HTTPS-Adresse. |
| alle anderen | Gib `message` weiter und frage, wie der Betreiber fortfahren will. |
