# GitLab mit einem vom Betreiber gelieferten API-Key

Frage (Issue #18): Was lässt sich bei GitLab (aktuelle Version, selbst gehostet und gitlab.com) automatisieren, wenn der Betreiber einmalig einen Personal Access Token liefert? Abgebildet werden die Schritte des Skills `igit` aus [`docs/spec-igit-skill.md`](../docs/spec-igit-skill.md): Bot-Konto, Client-Schlüssel, Host-Key-Pinning, Token pro Client, Repo samt Mitarbeiter und Meilenstein, Abgleich, Archivieren, Löschen, Widerruf und MCP-Server.

Stand: GitLab-Dokumentation auf dem Branch `master` des Projekts `gitlab-org/gitlab`, abgerufen am 2026-09-30. Die jüngsten Versionsvermerke darin beziehen sich auf GitLab 19.5. Es wurde keine GitLab-Instanz angefasst, nichts installiert und kein Konto angelegt. Alle Aussagen beruhen auf der Dokumentation, nicht auf Tests.

## Quellen

Jede Quelle ist die Markdown-Datei im Repository `gitlab-org/gitlab` (Pfad unter `doc/`), die als Seite auf docs.gitlab.com erscheint.

- **[SA]** Service Accounts: `doc/user/profile/service_accounts.md` – https://docs.gitlab.com/user/profile/service_accounts/
- **[SA-API]** Service Accounts API: `doc/api/service_accounts.md` – https://docs.gitlab.com/api/service_accounts/
- **[PAT]** Personal Access Tokens: `doc/user/profile/personal_access_tokens.md` – https://docs.gitlab.com/user/profile/personal_access_tokens/
- **[UT-API]** User Tokens API: `doc/api/user_tokens.md` – https://docs.gitlab.com/api/user_tokens/
- **[PAT-API]** Personal Access Tokens API: `doc/api/personal_access_tokens.md` – https://docs.gitlab.com/api/personal_access_tokens/
- **[SCOPES]** Token-Scopes: `doc/security/tokens/access_token_scopes.md` – https://docs.gitlab.com/security/tokens/access_token_scopes/
- **[LIMITS]** Account- und Limit-Einstellungen: `doc/administration/settings/account_and_limit_settings.md` – https://docs.gitlab.com/administration/settings/account_and_limit_settings/
- **[PRAT]** Projekt-Access-Tokens: `doc/user/project/settings/project_access_tokens.md` – https://docs.gitlab.com/user/project/settings/project_access_tokens/
- **[GRAT]** Gruppen-Access-Tokens: `doc/user/group/settings/group_access_tokens.md` – https://docs.gitlab.com/user/group/settings/group_access_tokens/
- **[KEYS-API]** User SSH and GPG keys API: `doc/api/user_keys.md` – https://docs.gitlab.com/api/user_keys/
- **[DK-API]** Deploy Keys API: `doc/api/deploy_keys.md` – https://docs.gitlab.com/api/deploy_keys/
- **[SSH]** SSH-Schlüssel: `doc/user/ssh.md` – https://docs.gitlab.com/user/ssh/
- **[COM]** GitLab.com-Einstellungen: `doc/user/gitlab_com/_index.md` – https://docs.gitlab.com/user/gitlab_com/
- **[PROJ-API]** Projects API: `doc/api/projects.md` – https://docs.gitlab.com/api/projects/
- **[MS-API]** Milestones API: `doc/api/milestones.md` – https://docs.gitlab.com/api/milestones/
- **[BOARDS-API]** Project issue boards API: `doc/api/boards.md` – https://docs.gitlab.com/api/boards/
- **[BOARDS]** Issue Boards: `doc/user/project/issue_board.md` – https://docs.gitlab.com/user/project/issue_board/
- **[DEFBR]** Default Branch: `doc/user/project/repository/branches/default.md` – https://docs.gitlab.com/user/project/repository/branches/default/
- **[MCP]** GitLab MCP server: `doc/user/model_context_protocol/mcp_server.md` – https://docs.gitlab.com/user/model_context_protocol/mcp_server/
- **[MCP-TOOLS]** GitLab MCP server tools: `doc/user/model_context_protocol/mcp_server_tools.md` – https://docs.gitlab.com/user/model_context_protocol/mcp_server_tools/
- **[GLAB-MCP]** `glab mcp serve`: `gitlab-org/cli`, `docs/source/mcp/serve.md` – https://gitlab.com/gitlab-org/cli/-/blob/main/docs/source/mcp/serve.md
- **[ZER]** Community-Server `zereight/gitlab-mcp`, README – https://github.com/zereight/gitlab-mcp

## Kurzantwort

Mit einem **Admin-PAT auf einer selbst gehosteten Instanz** lässt sich der Skill fast vollständig abbilden, und zwar sauberer als bei Forgejo: GitLab hat mit **Service Accounts** einen echten Bot-Kontotyp, der seit GitLab 18.11 auch in der Free-Edition verfügbar ist, und es hat eine **API für Issue Boards**. Aufwand: **mittel**.

Mit einem **PAT eines normalen Nutzers auf gitlab.com** geht es nur, wenn der Betreiber **Owner einer Top-Level-Gruppe** ist und alle Repositories in dieser Gruppe liegen. Dann trägt ein **Gruppen-Service-Account** die Bot-Rolle. Ohne Gruppe (Repos im persönlichen Namespace) gibt es keinen Bot und keinen Token pro Client. Aufwand: **mittel bis aufwendig**, mit mehreren Stellen, an denen Zero-Touch bricht.

Die unbequemen Punkte zuerst:

1. **Der offizielle GitLab-MCP-Server ist mit dem Bot-Modell nicht kompatibel.** Er authentifiziert laut Dokumentation per OAuth 2.0 mit Dynamic Client Registration und Zustimmung im Browser. Service Accounts können sich nicht im Browser anmelden, also würde der Server als Betreiber arbeiten, nicht als Bot. Für einen Token pro Client ohne Browser braucht es einen Community-Server (z. B. `@zereight/mcp-gitlab`, Node.js).
2. **Ein normaler Nutzer kann sich per API keine weiteren Tokens ausstellen.** `POST /user/personal_access_tokens` ist auf die Scopes `k8s_proxy` und `self_rotate` beschränkt [UT-API]. Tokens für andere Konten gibt es nur als Administrator oder über die Service-Account-API als Gruppen-Owner.
3. **Der gelieferte PAT läuft standardmäßig ab** (höchstens 365 Tage, auf Instanzen mit dem Feature-Flag `buffered_token_expiration_limit` 400 Tage). Nur ein Administrator einer selbst gehosteten Instanz kann die Pflicht abschalten [PAT][LIMITS]. Weil `repo`, `archivieren`, `loeschen` und `widerrufen` Betreiberrechte brauchen, muss der Skill den PAT entweder dauerhaft speichern oder bei jedem Lauf neu erfragen. Beides weicht vom Forgejo-Modell ab, in dem der Admin-Token nur während eines Laufs existiert.
4. **Endgültiges Löschen ist auf gitlab.com nicht möglich.** `DELETE /projects/:id` markiert das Projekt nur zum Löschen; die Daten bleiben 30 Tage erhalten, `permanently_remove` ist auf gitlab.com und Dedicated deaktiviert [PROJ-API].

## Abbildung der Skill-Schritte

### Rechte des gelieferten PAT

| Variante | Nötige Scopes | Rolle | Was damit geht |
|---|---|---|---|
| Selbst gehostet, Admin | `api`; zusätzlich `admin_mode`, falls Admin Mode aktiv ist [SCOPES] | Administrator | Alles: Instanz-Service-Account, dessen PATs und SSH-Schlüssel, Projekte in jedem Namespace, Einstellungen für Token-Ablauf. |
| Selbst gehostet, normaler Nutzer | `api` | Owner einer Gruppe, und der Administrator muss „Allow top-level group owners to create service accounts“ eingeschaltet haben [SA-API] | Gruppen-Service-Account samt PATs; SSH-Schlüssel nur über den Umweg in Abschnitt „SSH“. Ohne diese Einstellung: kein Bot. |
| gitlab.com | `api` | Owner der Top-Level-Gruppe (für Service Accounts und für die Ablauf-Einstellung) [SA-API][PAT] | Gruppen-Service-Account samt PATs; Bot nur in Projekten dieser Gruppe und ihrer Untergruppen. |

`api` genügt für Projekte, Mitglieder, Meilensteine, Boards, Archivieren und Löschen, sofern die Rolle stimmt. `read_user` reicht für nichts davon.

### Bot-Identität

Drei Mechanismen kommen in Frage:

- **Service Accounts** [SA][SA-API]. Tarif: Free, Premium und Ultimate auf gitlab.com, Self-Managed und Dedicated. Auf Free seit GitLab 18.11 allgemein verfügbar (18.10 hinter dem Feature-Flag `service_accounts_available_on_free_or_unlicensed`). Grenze auf Free: 100 Service Accounts pro Top-Level-Gruppe (gitlab.com) beziehungsweise pro Instanz (Self-Managed); auf Premium und Ultimate unbegrenzt. Es gibt drei Arten:
  - *Instanz-Service-Account*: `POST /service_accounts`, nur Self-Managed und Dedicated, nur Administrator. Er kann in beliebige Projekte eingetragen werden. PATs erzeugt der Administrator mit `POST /users/:user_id/personal_access_tokens` [UT-API].
  - *Gruppen-Service-Account*: `POST /groups/:id/service_accounts`. Auf gitlab.com genügt die Owner-Rolle der Gruppe. Er kann nur in diese Gruppe und ihre Nachfahren eingetragen werden, nicht in übergeordnete Gruppen und **nicht in persönliche Namespaces**. PATs: `POST /groups/:id/service_accounts/:user_id/personal_access_tokens`, Widerruf mit `DELETE …/personal_access_tokens/:token_id`, Rotation mit `…/rotate`.
  - *Projekt-Service-Account*: `POST /projects/:id/service_accounts`, Rolle Maintainer oder Owner. Eingeführt in 18.10, allgemein verfügbar in 18.11. Wegen der Bindung an ein einzelnes Projekt passt er nicht zu einem MCP-Token pro Instanz.
- **Projekt- und Gruppen-Access-Tokens** [PRAT][GRAT]: Jeder Token erzeugt automatisch einen eigenen Bot-Nutzer (`project_<id>_bot_<zufall>` beziehungsweise `group_<id>_bot_<zufall>`). Dieser Bot kann nicht in andere Projekte oder Gruppen eingetragen werden. Auf gitlab.com brauchen beide Premium oder Ultimate; auf Self-Managed gehen sie mit jeder Lizenz. **Ungeeignet**: Ein Token pro Client hieße ein Bot pro Client und Projekt, und SSH-Schlüssel für diese Bots sind nicht dokumentiert.
- **Normales Konto als Bot** (wie bei Forgejo): `POST /users`, nur Administrator. Überflüssig, seit Service Accounts in Free verfügbar sind.

**Empfehlung:** Selbst gehostet mit Admin-PAT ein Instanz-Service-Account; sonst ein Gruppen-Service-Account der Gruppe, in der die Repositories liegen. Ein Service Account ist bereits ein nicht-interaktives Konto ohne Anmeldung im Browser; die Härtung mit `restricted`, `max_repo_creation` usw. entfällt. [Unsicher] Ob ein Service Account Projekte sieht, in die er nicht eingetragen ist (etwa interne Projekte), ist in den gelesenen Seiten nicht geregelt. Ein Instanz-Service-Account könnte bei Bedarf zusätzlich als `external` markiert werden; geprüft ist das nicht.

### SSH-Schlüssel für den Bot

- **Nutzerschlüssel am Service Account**: Die Doku verweist ausdrücklich auf die User-Keys-API; in der Oberfläche lassen sich SSH-Schlüssel von Service Accounts nicht verwalten [SA]. `POST /users/:id/keys` und `DELETE /users/:id/keys/:key_id` verlangen Administratorrechte [KEYS-API]. Mit Admin-PAT ist der Schritt also 1:1 wie bei Forgejo, einschließlich des Titels pro Client und eines optionalen `expires_at`.
- **Ohne Admin (gitlab.com)**: Der Gruppen-Owner erzeugt einen PAT des Service Accounts mit Scope `api` und hinterlegt damit den Schlüssel als der Service Account selbst über `POST /user/keys`; dafür verlangt die Doku nur Authentifizierung [KEYS-API]. [Unsicher] Dass `POST /user/keys` mit dem Token eines Service Accounts funktioniert, steht nicht ausdrücklich in der Doku, folgt aber aus dem Verweis in [SA] auf genau diese API. Das muss vor der Umsetzung geprüft werden.
- **Deploy Keys mit Schreibrecht** [DK-API]: `POST /projects/:id/deploy_keys` mit `can_push: true`, Rolle Maintainer, alle Tarife. Ein vorhandener Schlüssel wird mit `POST /projects/:id/deploy_keys/:key_id/enable` in weiteren Projekten freigeschaltet. Deploy Keys gewähren nur Git-Zugriff, keine API. Nachteile: Der Schlüssel muss in jedem Repo einzeln eingetragen werden, und der Widerruf eines Clients muss über alle Repos laufen. Das ist nur die Rückfallebene, falls Nutzerschlüssel am Service Account ohne Admin nicht gehen.
- **Standard-Branchschutz**: Der Standard ist „Fully protected“: Entwickler dürfen nicht auf den Standard-Branch pushen, Maintainer schon [DEFBR]. Damit der Bot auf `main` pushen kann, muss er Maintainer (`access_level` 40) statt Developer (30) sein, oder der Branchschutz muss pro Projekt gelockert werden. Das ist mehr Recht als das „Schreibrecht“ bei Forgejo.

### Host-Key der Instanz

- **gitlab.com**: Die Doku veröffentlicht die Fingerprints (ECDSA, ED25519, RSA) und fertige `known_hosts`-Einträge [COM]. Der Skill kann die Einträge fest einbauen oder den Scan gegen die veröffentlichten Fingerprints prüfen. Zero-Touch bleibt erhalten.
- **Selbst gehostet**: Die Fingerprints stehen auf der HTML-Seite `https://<host>/help/instance_configuration#ssh-host-keys-fingerprints` [SSH]. Eine REST-Schnittstelle dafür ist in den gelesenen Seiten nicht dokumentiert. [Unsicher] Ob diese Seite ohne Browser-Sitzung abrufbar ist, ist nicht geprüft. Ohne SSH-Zugang zum Host der Instanz (den das Forgejo-Modell voraussetzt) bleibt nur: `ssh-keyscan` und Abgleich gegen diese Seite, übertragen per HTTPS. Das ist so sicher wie das TLS-Zertifikat der Instanz. Hat der Betreiber zusätzlich SSH-Zugang zum Host, können wie bei Forgejo die Dateien `ssh_host_*_key.pub` gelesen werden (bei Linux-Paketinstallationen stellt der System-`sshd` Git-SSH bereit).

### Token pro Client

- Selbst gehostet mit Admin: `POST /users/:user_id/personal_access_tokens` für den Instanz-Service-Account, Name `igit-<client>`, Scopes `api` (für MCP-Server, die Projekte und Meilensteine anlegen) oder enger `read_api` + `write_repository`, je nach MCP-Abdeckung [UT-API][SCOPES].
- gitlab.com: `POST /groups/:id/service_accounts/:user_id/personal_access_tokens` [SA-API].
- Einschränkung auf Repositories: GitLab-PATs sind nicht auf Repositories beschränkbar; die Grenze ergibt sich wie bei Forgejo aus den Mitgliedschaften des Bot-Kontos.

### Ablaufdaten

- Standardmäßig müssen alle neuen Tokens ein Ablaufdatum haben; fehlt es, gilt heute + 365 Tage; mehr als 365 Tage (mit Flag 400) sind nicht erlaubt [PAT][LIMITS].
- **PATs von Service Accounts** können ohne Ablauf erzeugt werden, wenn die Pflicht abgeschaltet ist [PAT]:
  - gitlab.com: Owner der Top-Level-Gruppe entfernt in den Gruppeneinstellungen das Häkchen „Require expiration dates for service accounts“. Das geht per UI; [Unsicher] ob es per Gruppen-API setzbar ist, ist nicht geprüft.
  - Self-Managed EE: Administrator über die Einstellung `service_access_tokens_expiration_enforced` der Application-Settings-API [LIMITS].
  - Self-Managed CE: Das Häkchen für Service Accounts fehlt; stattdessen muss die allgemeine Pflicht „Require expiration date“ abgeschaltet werden, die dann für alle Tokens der Instanz gilt [PAT].
- Der **PAT des Betreibers** selbst läuft ab, sofern nicht ein Administrator die allgemeine Pflicht abgeschaltet hat. Auf gitlab.com ist das nicht möglich.
- Auch SSH-Schlüssel können einer Lebensdauergrenze unterliegen, wenn der Administrator (Ultimate) sie setzt [LIMITS].

### Repo anlegen, Mitarbeiter, Meilenstein

- Anlegen: `POST /projects` mit `namespace_id` (Gruppe) oder ohne (persönlicher Namespace des Betreibers) [PROJ-API]. Im Namen eines anderen Kontos: `POST /projects/user/:user_id`, nur Administrator.
- Bot eintragen: `POST /projects/:id/members` mit `user_id` und `access_level` (siehe Branchschutz oben). Gruppen-Service-Accounts lassen sich nur in Projekte ihrer Gruppe eintragen [SA-API].
- Meilenstein: `POST /projects/:id/milestones`, alle Tarife [MS-API]. Keine Abweichung zu Forgejo.
- Remote: `git@<host>:<namespace>/<projekt>.git` über den SSH-Alias wie bisher.

### Boards

Anders als Forgejo 16 hat GitLab eine Board-API in allen Tarifen: `POST /projects/:id/boards`, Listen mit `POST /projects/:id/boards/:board_id/lists` [BOARDS-API]. Mehrere Projekt-Boards sind in allen Tarifen erlaubt [BOARDS]. Ein Board auf einen Meilenstein zu beschränken (`milestone_id` am Board) sowie Assignee-, Meilenstein- und Iterationslisten gibt es nur in Premium und Ultimate. In Free zeigt das Board alle Issues des Projekts; die Listen bilden sich aus Labels. Der manuelle Schritt „Board in der Oberfläche anlegen“ entfällt damit.

### Abgleich bestehender Repositories

`GET /projects?membership=true` (bzw. `GET /groups/:id/projects`) liefert die Projekte des Betreibers, `GET /projects/:id/members/all` zeigt, ob der Bot eingetragen ist [PROJ-API]. Beim Gruppen-Service-Account kann der Abgleich nur Projekte dieser Gruppe freigeben; Projekte im persönlichen Namespace fallen heraus.

### Archivieren

`POST /projects/:id/archive` und `POST /projects/:id/unarchive`, Administrator oder Owner des Projekts, idempotent [PROJ-API]. Der Betreiber-PAT muss also vom Owner stammen; der Bot als Maintainer kann nicht archivieren. Gleichwertig zu Forgejo.

### Löschen

`DELETE /projects/:id`, Administrator oder Owner; seit 18.0 in Free [PROJ-API]. Der Aufruf markiert nur zum Löschen.
- Selbst gehostet: ein zweiter Aufruf `DELETE /projects/:id` mit `permanently_remove=true` und `full_path` löscht sofort. Die Aufbewahrungsfrist ist eine Instanzeinstellung.
- gitlab.com: Nach 30 Tagen endgültig gelöscht; sofortiges Löschen nur per Support-Ticket. Bis dahin ist der Projektpfad belegt. [Unsicher] Ob ein erneutes Anlegen unter demselben Namen in dieser Zeit scheitert, ist nicht geprüft. `loeschen` muss auf gitlab.com also als „zum Löschen markiert, endgültig am <datum>“ berichten.

### Widerruf pro Client

- Token: `DELETE /personal_access_tokens/:id` (Administrator oder Eigentümer) beziehungsweise `DELETE /groups/:id/service_accounts/:user_id/personal_access_tokens/:token_id` [PAT-API][SA-API]. Andere Tokens des Bots bleiben gültig.
- SSH-Schlüssel: `DELETE /users/:id/keys/:key_id` als Administrator, sonst `DELETE /user/keys/:key_id` mit einem kurzlebigen Token des Service Accounts [KEYS-API]. Bei Deploy Keys: pro Projekt `DELETE /projects/:id/deploy_keys/:key_id`.
- Damit ist der Widerruf eines einzelnen Clients möglich, auf gitlab.com aber nur mit Owner-Rechten und dem Umweg über einen Service-Account-Token.

## MCP-Server

| Server | Transport | Authentifizierung | Abdeckung | Passt zu `igit`? |
|---|---|---|---|---|
| Offizieller GitLab-MCP-Server, Endpunkt `https://<host>/api/v4/mcp`; Beta, seit 19.2 in Free, muss auf gitlab.com pro Top-Level-Gruppe bzw. auf Self-Managed pro Instanz freigeschaltet werden [MCP] | HTTP (empfohlen) oder stdio über `mcp-remote` (Node.js) | OAuth 2.0 mit Dynamic Client Registration und Zustimmung im Browser | Projekte, Issues/Work Items (inkl. Meilenstein-Zuordnung über `save_work_item`), Merge Requests, Repository, CI, Suche; Toolsets per Header wählbar (19.5, Flag `mcp_toolsets`) [MCP-TOOLS]. Kein Werkzeug zum Anlegen von Meilensteinen oder Boards in der Werkzeugliste. | **Nein** für das Bot-Modell: Der Browser-Schritt bricht Zero-Touch, und das OAuth-Token gehört dem zustimmenden Nutzer. [Unsicher] Ob der Endpunkt zusätzlich einen PAT per Header akzeptiert, dokumentiert GitLab nicht. |
| `glab mcp serve` (offizielle CLI) [GLAB-MCP] | stdio | Anmeldedaten von `glab` (Token) | Issues, Merge Requests, Projekte (lesen), Pipelines | Technisch ja, aber „experiment … not ready for production use“, und `glab` muss installiert sein. |
| `@zereight/mcp-gitlab` (Community) [ZER] | stdio, SSE, Streamable HTTP | `GITLAB_PERSONAL_ACCESS_TOKEN`, `GITLAB_API_URL` (selbst gehostet möglich) | Sehr breit: Projekte, Issues, Meilensteine, Wikis, Pipelines, Releases u. a.; Toolsets und `GITLAB_PERMISSION_MODE=readonly` | **Ja**, dem Muster von forgejo-mcp am nächsten: Starter liest Token aus Datei und setzt Umgebungsvariable. Aber npm-Paket, braucht Node.js; keine Prüfsumme wie beim Forgejo-Binary, sondern nur Paket-Pinning möglich. |

## Aufwandsschätzung gegenüber dem Forgejo-Adapter

Das heutige `skill/igit/igit.py` hat rund 1 200 Zeilen. Davon sind API-unabhängig und wiederverwendbar: Dateien und Modi, SSH-Config, `known_hosts`, Unterbefehlsgerüst, lokale Prüfungen vor dem Löschen, Registrierung des MCP-Servers. Forgejo-spezifisch und für GitLab neu zu schreiben sind: Instanzfindung (`/api/v4/version` statt `/api/v1/version`), der gesamte Docker-/CLI-Pfad für den Admin-Token (entfällt, weil der PAT geliefert wird), Bot-Anlage, Token- und Schlüsselverwaltung, Projekt-IDs statt `owner/name`, Rollen als `access_level`, zweistufiges Löschen, Board-Anlage, MCP-Installation über npm.

| Baustein | Self-Managed mit Admin-PAT | gitlab.com mit Gruppen-Owner-PAT |
|---|---|---|
| Instanz finden, Version prüfen | klein | klein (fest `gitlab.com`) |
| Bot | klein (Instanz-Service-Account) | klein (Gruppen-Service-Account), aber Gruppe als Pflicht-Rückfrage |
| SSH-Schlüssel pro Client | klein | mittel (Umweg über Service-Account-Token, ungeprüft; Rückfall Deploy Keys) |
| Host-Key | mittel (kein API-Endpunkt; Scan plus Abgleich per HTML-Seite oder Host-Zugang) | klein (veröffentlichte Einträge) |
| Token pro Client, Ablauf | klein, Ablauf abschaltbar | klein, Ablauf nur per Gruppeneinstellung abschaltbar |
| Repo, Mitglied, Meilenstein, Board | klein | klein; nur Gruppen-Namespaces |
| Archivieren, Löschen | klein (zweistufig) | klein, aber kein endgültiges Löschen |
| Widerruf | klein | mittel |
| MCP | mittel (Node.js-Abhängigkeit, Community-Server) | mittel |
| Umgang mit dem gelieferten PAT (Speicherung, Ablauf) | mittel | mittel |

Grob geschätzt: ein GitLab-Adapter ist etwa **60–70 % des Aufwands des Forgejo-Adapters**, weil die Docker-Installation und der CLI-Pfad wegfallen, aber zwei Rechte-Varianten, das Token-Lebenszyklus-Thema und ein zweiter MCP-Server hinzukommen. Gemeinsam genutzter Code setzt voraus, dass `igit.py` vorher eine Adapter-Schnittstelle erhält; das ist ein eigener Umbau, der in der Schätzung nicht enthalten ist.

## Stellen, an denen Zero-Touch bricht

1. **Der Betreiber muss den PAT von Hand erzeugen und übergeben.** Das ist die Grundannahme dieses Tickets, aber es ersetzt den Forgejo-Weg, bei dem das Skript den Admin-Token selbst per `docker exec` erzeugt.
2. **Ablauf des Betreiber-PAT.** Auf gitlab.com läuft er nach höchstens 365 (400) Tagen ab, und spätere Läufe von `repo`, `archivieren`, `loeschen` und `widerrufen` scheitern, bis der Betreiber einen neuen liefert. Zudem muss der PAT zwischen den Läufen gespeichert werden, was der Sicherheitsregel „Admin-Rechte nur während eines Laufs“ widerspricht.
3. **Kein Bot ohne Gruppe bzw. Admin.** Ein normaler Nutzer ohne Owner-Rolle in einer Gruppe (gitlab.com) oder ohne Freigabe durch den Administrator (Self-Managed) kann keinen Service Account anlegen und sich keine weiteren Tokens ausstellen. Repositories im persönlichen Namespace sind für einen Gruppen-Service-Account unerreichbar.
4. **Ablaufpflicht für Bot-Tokens auf gitlab.com** lässt sich nur durch den Owner in den Gruppeneinstellungen abschalten, dokumentiert nur als UI-Schritt. Sonst laufen die Client-Tokens nach einem Jahr ab, und die Spezifikation schließt Rotation aus.
5. **SSH-Schlüssel des Bots ohne Admin** hängt an der ungeprüften Annahme, dass `POST /user/keys` mit dem Token eines Service Accounts funktioniert.
6. **Host-Key auf Self-Managed** hat keinen API-Endpunkt. Ohne Host-Zugang ist das Pinning nur so gut wie der HTTPS-Abruf der Fingerprint-Seite.
7. **Offizieller MCP-Server** verlangt OAuth mit Browser-Zustimmung und würde als Betreiber statt als Bot handeln. Zero-Touch gibt es nur mit einem Community-Server, der Node.js voraussetzt.
8. **Endgültiges Löschen** ist auf gitlab.com nicht per API möglich.
9. **Branchschutz**: Ohne Maintainer-Rolle für den Bot oder gelockerten Schutz scheitert der erste Push auf den Standard-Branch.

## Einschätzung

- **Selbst gehostetes GitLab mit Admin-PAT: mittel.** Alle Schritte sind per API abgedeckt, Bot und Boards sogar besser als bei Forgejo. Aufwand entsteht beim Host-Key, beim MCP-Server (Node.js) und bei der Frage, wie der gelieferte PAT aufbewahrt wird.
- **gitlab.com (oder Self-Managed ohne Admin): aufwendig.** Es funktioniert nur für Repositories in einer Gruppe, deren Owner der Betreiber ist; mehrere Schritte hängen an ungeprüften Annahmen oder an UI-Einstellungen; endgültiges Löschen fehlt; der Betreiber-PAT läuft zwingend ab.
