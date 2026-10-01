---
name: gitlink
description: Forgejo/Gitea/GitLab + Claude einrichten / set up Forgejo, Gitea or GitLab for Claude. Use when the user wants to connect Claude to a Forgejo, Gitea or self-hosted GitLab instance (einrichten, setup, install Forgejo), create a repository or connect a directory to an existing one (Repo anlegen, verbinden, create repo, connect), set issue dependencies (Abhängigkeit, blocked by), archive or delete a repository (archivieren, löschen, archive, delete), or revoke a Claude client's access (widerrufen, revoke).
---

# gitlink

Der Skill verbindet Claude mit einer Instanz von Forgejo, Gitea oder selbst gehostetem GitLab. Alles Deterministische erledigt das Skript `gitlink.py` im Basisverzeichnis dieses Skills; du stellst die Rückfragen und rufst es auf:

```
python3 <basisverzeichnis>/gitlink.py --lang <de|en> <unterbefehl> [optionen]
```

Jeder Aufruf gibt ein JSON-Objekt aus: bei `"ok": true` das Ergebnis in `result` und Hinweise in `warnings`, bei `"ok": false` einen `error` mit `details`. Geheimnisse (Tokens, Passwörter, private Schlüssel) liest und zeigst du nie; das Skript nennt nur Pfade. Öffentliche Schlüssel und Fingerprints darfst du zeigen.

## Gesprächsregeln

- **Sprache:** Antworte in der Sprache des Betreibers und übergib `--lang de` bzw. `--lang en`. Unterbefehle heißen auf Deutsch und Englisch (`einrichten`/`setup` …).
- **Eine Frage pro Schritt:** Bündle alles, was du für einen Schritt wissen musst, in eine einzige Rückfrage, und schlage für jeden Punkt einen Standardwert vor, den der Betreiber nur bestätigen muss.
- **Nur fragen, was das Skript nicht weiß:** Frag nie nach etwas, das `uebersicht` oder `finden` beantwortet.
- **Knappe Ergebnisse:** Nach jedem Befehl höchstens fünf Zeilen: was passiert ist, jede Warnung sinngemäß, und was der Betreiber jetzt tun muss, falls etwas.
- **Probleme:** Nenne die Ursache in einem Satz, dann ein bis drei kurze, einfache Lösungen, die naheliegendste zuerst. Steht in der `message` des Skripts schon eine („Lösung: …“), gib sie weiter, statt selbst nachzuforschen. Nichts Zerstörerisches ohne ausdrückliches Ja.
- **Instanz wählen:** Ist ein Befehl nur auf einer eingerichteten Instanz möglich (laut `uebersicht`), nimm sie und übergib `--instanz`. Frag nur, wenn mehrere passen.
- **Verzeichnis wählen:** Standard ist das aktuelle Verzeichnis, wenn es noch kein `origin` hat; sonst `<übergeordnetes Verzeichnis>/<repo-name>`.

## Ohne Unterbefehl

Rufe `uebersicht` auf. Zeige je Instanz Plattform und Adresse und darunter **nur** die Befehle aus `result.instances[].commands` mit ihrer `description`, dazu `result.other`. Frag dann, was der Betreiber tun will.

## einrichten / setup

1. `finden --dir <verzeichnis>`. Eine Instanz: weiter. Mehrere: frag, welche. Keine: frag in einer Frage nach der Adresse oder ob Forgejo installiert werden soll ([Sonderfälle](sonderfaelle.md#installation)). Trägt eine Instanz `data_missing`: [Sonderfälle](sonderfaelle.md#instanz-ohne-daten).
2. `einrichten --url <url>`; bei GitLab zusätzlich `--plattform gitlab`.
3. Je nach Ergebnis:
   - `missing_repos` nicht leer (Forgejo/Gitea): frag einmal, welche Repos Claude nutzen darf (Vorschlag: alle), dann `freigeben <repo> …`.
   - `ssh_key_required` (GitLab): zeig `details.public_key`, `details.title`, den Link `details.add_key_url` und `details.host_key_fingerprints` zum Vergleich mit `<url>/help/instance_configuration`; bitte den Betreiber, den Schlüssel einzutragen und die Fingerprints zu bestätigen. Danach `einrichten` wiederholen. Kommt der Fehler trotz eingetragenem Schlüssel erneut: [Sonderfälle](sonderfaelle.md#gitlab-ssh-port).
   - jeder andere Fehler: [Sonderfälle](sonderfaelle.md#fehlercodes).
4. Kurz zusammenfassen (Plattform, Konto bzw. Bot, SSH-Alias, MCP-Server), dann [Empfehlung](#empfehlung), außer bei GitLab. Den MCP-Server hat das Skript schon selbst getestet (`result.mcp_check`: Server, Anzahl Tools, angemeldetes Konto); nenne das Ergebnis in einer Zeile und teste nicht von Hand nach. Seine Tools stehen dir erst nach einem Neustart von Claude Code zur Verfügung. Ein erneutes `einrichten` prüft alles noch einmal, auch den MCP-Server.

## verbinden / connect

Verbindet ein Verzeichnis mit einem bestehenden Repo. Bei Forgejo/Gitea trägt das Skript den Bot dabei selbst ein.

1. Frag in einer Frage nach dem Repo (`eigentümer/name`, bei GitLab auch `gruppe/…/name`) und schlag das Verzeichnis vor.
2. `verbinden --repo <pfad> --dir <verzeichnis>`. Bei `git_identity_missing`: siehe [Git-Identität](#git-identität).

**Bei GitLab gilt danach:** Du leistest nur Hilfestellung. `git commit` und `git push` nur auf ausdrückliche Anforderung, keine Änderungen auf GitLab selbst. Die Regel steht auch in der `CLAUDE.md` des Verzeichnisses.

## repo (Forgejo, Gitea)

1. `orgs` aufrufen.
2. **Eine** Frage: Name (falls nicht genannt), Sichtbarkeit (Vorschlag: privat), Eigentümer nur wenn `orgs` nicht leer, Verzeichnis als Vorschlag.
3. `repo --name <name> --privat|--oeffentlich [--owner <org>] --dir <verzeichnis>`. Bei `repo_exists` frag, ob das bestehende Repo eingerichtet werden soll (`--existing-ok`). Bei `git_identity_missing`: siehe [Git-Identität](#git-identität).
4. Ist `result.initial_commit_pending` wahr, biete an, die `CLAUDE.md` als ersten Commit auf `main` zu pushen (Vorschlag: ja). Gib `result.board_instruction` weiter, dann [Empfehlung](#empfehlung).

Jedes Issue, das du danach in diesem Repo anlegst, ordnest du dem Meilenstein `result.milestone_id` zu (steht auch in der `CLAUDE.md`).

## Git-Identität

`git_identity_missing` heißt: Commits im Verzeichnis hätten weder Namen noch E-Mail; das Skript hat noch nichts geändert. Frag in **einer** Frage nach Name und E-Mail, mit `details.suggestion` als Vorschlag, und wiederhole denselben Aufruf mit `--git-name <name> --git-email <mail>`. Das Skript setzt beides nur für dieses Repo.

## abhaengigkeit / dependency (Forgejo, Gitea)

Abhängigkeiten setzt du immer über das Skript, nicht über den MCP-Server:
`abhaengigkeit --repo <repo> --issue <blockiert> [--blockiert-durch <blockierend> [--entfernen]]`; ohne `--blockiert-durch` listet es `result.blocked_by`.

## archivieren / archive (Forgejo, Gitea)

`archivieren --repo <repo>` (rückgängig mit `--rueckgaengig`); umkehrbar, ohne Rückfrage. Ist unklar, ob archivieren oder löschen gemeint ist, empfiehl Archivieren.

## löschen / delete (Forgejo, Gitea)

Eine Frage: „Repo `<repo>` samt Issues endgültig löschen? Lokales Verzeichnis `<verzeichnis>` mitlöschen?“ Nur bei ausdrücklichem Ja: `loeschen --repo <repo> --bestaetigen <repo> [--dir <verzeichnis>]`. Das Skript lässt ein Verzeichnis mit Ungesichertem stehen und sagt warum; lösch es nie selbst.

## widerrufen / revoke

`widerrufen` ohne `--client` listet in `details.clients` die Clients und in `details.this_client` den eigenen. Frag, welcher; für den eigenen zusätzlich `--lokal`. Bei GitLab gibt es nur den eigenen; das Skript nennt den Link, unter dem der Betreiber den Schlüssel in GitLab entfernt.

## Empfehlung

Einmal pro Sitzung, nach `einrichten` oder `repo` (nicht bei GitLab), in höchstens drei Zeilen. [`wayfinder`](https://github.com/mattpocock/skills/blob/main/docs/engineering/wayfinder.md) plant ein Vorhaben, das größer ist als eine Sitzung, als Karte von Entscheidungs-Issues im Repo.

- `mattpocock-skills` laut `claude plugin list` nicht installiert: empfiehl die [Skills von Matt Pocock](https://github.com/mattpocock/skills), besonders `wayfinder`, und biete `claude plugins install mattpocock-skills` an (verfügbar nach einem Neustart).
- Installiert: sag, dass der Betreiber ein großes Vorhaben mit `/mattpocock-skills:wayfinder` planen kann.

Beide Skills startet nur der Betreiber; du kannst sie nicht aufrufen (`disable-model-invocation`). Vor dem ersten Einsatz in einem Repo tippt er einmal `/mattpocock-skills:setup-matt-pocock-skills`. Es kennt Forgejo und Gitea nicht: Bei der Frage nach dem Issue-Tracker wählt er **Other** und gibt diesen Absatz an, den du mit den Werten aus `repo` füllst und ihm zum Einfügen zeigst:

> Issues liegen im {Plattform}-Repo `<eigentümer>/<name>` auf `<url>`. Lies und schreibe sie über den MCP-Server `<mcp-server>`. Ordne jedes neue Issue dem Meilenstein „<name>“ (ID <id>) zu. Blocker setzt `python3 <basisverzeichnis>/gitlink.py abhaengigkeit --repo <eigentümer>/<name> --issue <blockiert> --blockiert-durch <blockierend>`.
