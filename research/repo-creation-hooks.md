# Wie kann die Instanz reagieren, wenn der Betreiber ein Repository in der UI anlegt?

Ticket: dreamer/igit#3. Ziel: Forgejo 16.0.5 (`/api/v1/version` → `16.0.5+gitea-1.22.0`).
Quellen: Forgejo-Quellcode auf Branch `v16.0/forgejo` (Links unten, abgekürzt `src:`), die `swagger.v1.json` der laufenden Instanz und lesende API-Abfragen. An der Instanz wurde nichts geändert.

`src:` = `https://codeberg.org/forgejo/forgejo/src/branch/v16.0/forgejo/`

## Antwort

Zwei Mechanismen können das Bot-Konto ohne Patch an Forgejo zu einem neuen Repo hinzufügen:

1. **Ein System-Webhook auf das `repository`-Ereignis, plus ein kleiner Empfänger**, der `PUT /repos/{owner}/{repo}/collaborators/{bot}` aufruft. Das funktioniert für Repos, die der Betreiber unter seinem persönlichen Konto anlegt. Die Zustellung ist asynchron und einmalig. Sie dauert meist deutlich unter einer Sekunde, aber eine fehlgeschlagene Zustellung wird **nicht wiederholt**.
2. **Ein Organisationsteam mit „Zugriff auf alle Repositories“**, in dem das Bot-Konto Mitglied ist. Das braucht keinen Empfänger und geschieht innerhalb der Anlage-Transaktion, also ohne Latenz und ohne Fehlerquelle. Es deckt nur Repos dieser Organisation ab, nicht die persönlichen Repos des Betreibers.

Forgejo Actions und Git-Hooks **können es nicht** (Details unten).

## Was bei der Anlage eines Repos in der UI ausgelöst wird

Der UI-Handler `CreatePost` (`src:routers/web/repo/repo.go` Z. 224–312) ruft entweder `repo_service.CreateRepository` oder `repo_service.GenerateRepository` (aus einer Vorlage) auf. Beide enden mit `notify_service.CreateRepository(...)`, nachdem die DB-Transaktion committet ist (`src:services/repository/repository.go` Z. 43–53, `src:services/repository/template.go` Z. 132). Die Notifier, die auf diesen Aufruf reagieren, sind unten aufgeführt.

### Innerhalb der Anlage-Transaktion (synchron)

`CreateRepositoryByExample` (`src:modules/repository/create.go`):

- **Organisationsteams mit `IncludesAllRepositories`**: Jedes solche Team der besitzenden Organisation wird dem Repo hinzugefügt (Z. 128–137). Das ist die oben genannte Team-Variante.
- **Default-Webhooks** werden in das neue Repo kopiert (`webhook.CopyDefaultWebhooksToRepo`, Z. 161; `src:models/webhook/webhook_system.go` Z. 70–85). Die Kopien existieren bereits, wenn der Notifier läuft, und empfangen daher auch das `repository: created`-Ereignis dieses Repos.
- Das Einzige, was in diesem Schritt sonst passiert, ist Auto-Watch (`AutoWatchNewRepos`). Es gibt keinen Einhängepunkt für Plugins oder Skripte.

### Webhook-Notifier (asynchron)

`webhookNotifier.CreateRepository` (`src:services/webhook/notifier.go` Z. 109–119) sendet das Ereignis **`repository`** mit `action: "created"`. Die Nutzlast enthält `repository` (mit vollständigem Eigentümer), `organization` (trotz des Namens der besitzende Nutzer oder die Organisation) und `sender`. `MigrateRepository` tut dasselbe (Z. 132–142). `ForkRepository` sendet `repository: created` nur, wenn der Eigentümer des Forks eine **Organisation** ist (Z. 94–107). Ein Fork in ein persönliches Konto erzeugt nur `fork` am Quell-Repo.

`PrepareWebhooks` (`src:services/webhook/webhook.go` Z. 239–279) sammelt die Empfänger:

| Hook-Art | Geltungsbereich | Sieht Anlage von… | Wo konfiguriert |
|---|---|---|---|
| **System-Webhook** (`repo_id=0, owner_id=0, is_system_webhook=true`) | ganze Instanz | jedem Repo, ob im Besitz eines Nutzers oder einer Organisation | Site-Administration → Integrationen → System-Webhooks; API `POST /admin/hooks` mit `config.is_system_webhook="true"` |
| **Eigentümer-Webhook**, Nutzerebene | ein Nutzer | Repos dieses Nutzers | Nutzereinstellungen → Webhooks; API `/user/hooks` |
| **Eigentümer-Webhook**, Organisationsebene | eine Organisation | Repos dieser Organisation | Organisationseinstellungen → Webhooks; API `/orgs/{org}/hooks` |
| **Default-Webhook** (`is_system_webhook=false`, Vorlage) | wird in jedes neue Repo kopiert | dem neuen Repo (wegen der Kopie oben) | Site-Administration → Default-Webhooks; API `POST /admin/hooks` **ohne** `is_system_webhook` |
| Repo-Webhook | ein Repo | kann nicht existieren, bevor das Repo existiert (außer als Kopie eines Default-Hooks) | n/a |

Für die Ein-Betreiber-Instanz von igit funktionieren sowohl ein **Webhook auf Nutzerebene des Betreibers** als auch ein **System-Webhook**. Ein System-Webhook deckt zusätzlich Organisationen ab, die der Betreiber später anlegt, und wird nicht wie ein Default-Webhook in jedes Repo kopiert. Diese Kopien hinterlassen eine Hook-Zeile pro Repo, und jede Kopie feuert auch bei späteren Ereignissen dieses Repos.

### Actions-Notifier: nein

`actionsNotifier.CreateRepository` (`src:services/actions/notifier.go` Z. 404–413) reicht zwar ein `repository`-Ereignis an die Actions-Pipeline weiter, aber daraus kann nichts laufen:

- `notify()` kehrt sofort zurück, wenn `repo.IsEmpty` gilt (`src:services/actions/notifier_helper.go` Z. 152). Ein frisches UI-Repo ohne Auto-Init ist leer.
- Selbst bei einem nicht-leeren Repo hat `detectMatched` keinen Fall für `HookEventRepository`. Es fällt auf `default: log.Warn("unsupported event")` durch und gibt `false` zurück (`src:modules/actions/workflows.go` Z. 231–297).
- Workflows werden vom Standard-Branch des neuen Repos selbst gelesen. Kein instanz- oder organisationsweiter Workflow könnte auf die Anlage eines *anderen* Repos reagieren.

### Git-Hooks: nein

- Ein Auto-Init- oder Vorlagen-Repo erhält seinen ersten Commit über einen internen `git push` mit `GITEA_INTERNAL_PUSH=true` (`src:services/repository/init.go` Z. 75–77, `src:modules/repository/env.go` Z. 45–49). `forgejo hook pre-receive` und `post-receive` kehren bei internen Pushes früh zurück (`src:cmd/hook.go` Z. 175–177, Z. 312–315). Die Anlage erzeugt also kein Push-Ereignis, keinen Push-Webhook und keinen push-ausgelösten Workflow.
- Eigene serverseitige Git-Hooks sind pro Repo und können daher nicht existieren, bevor das Repo existiert. Außerdem sind sie standardmäßig deaktiviert (`[security] DISABLE_GIT_HOOKS = true`, `src:modules/setting/security.go` Z. 290).

### Weitere Signale (nur per Polling)

Die Anlage schreibt eine `create_repo`-Aktion in den Aktivitäts-Feed, lesbar unter `GET /users/{username}/activities/feeds` und `/orgs/{org}/activities/feeds` (in der Live-Swagger vorhanden). Ein Poller könnte ihn als **Abgleichs-Rückfallebene** nutzen, aber er ist kein Push-Auslöser.

## Der automatische Schritt: Bot-Konto als Mitarbeiter hinzufügen

API (Live-Swagger): `PUT /repos/{owner}/{repo}/collaborators/{collaborator}` mit Body `AddCollaboratorOption {"permission": "read"|"write"|"admin"}` → `204`. Der Mitarbeiter wird direkt hinzugefügt, ohne anzunehmende Einladung. Der Aufrufer muss Repo-Admin sein, also der Betreiber oder ein Site-Admin. Das Bot-Konto kann sich nicht selbst hinzufügen. Der Empfänger braucht daher einen Token des Betreibers oder einer separaten Admin-Identität mit Scope `write:repository`. Es darf nicht der Token des Bot-Kontos sein.

Skizze des Empfängers: `POST` annehmen → `X-Forgejo-Signature` prüfen (HMAC-SHA256 des Bodys mit dem Hook-Geheimnis) → wenn `X-Forgejo-Event: repository` und `action == "created"` → `PUT .../collaborators/<bot>`. Der Aufruf ist wiederholbar (ein PUT), Wiederholungen und Abgleich können also beliebig oft laufen.

## Nötige Konfiguration

- **Webhook**: `type: "forgejo"`, `events: ["repository"]`, `config.url`, `config.content_type: "json"`, `config.secret` und **`active: true`**. `CreateHookOption.active` ist in der Swagger standardmäßig `false`, ein ohne dieses Feld angelegter Hook feuert also nie. Für einen *System*-Hook zusätzlich `config.is_system_webhook: "true"` setzen. Ohne dieses Feld legt `POST /admin/hooks` stattdessen einen *Default*-Hook an (`src:routers/api/v1/utils/hook.go` Z. 165–189).
- **`[webhook] ALLOWED_HOST_LIST`** ist standardmäßig `external` (`src:services/webhook/deliver.go` Z. 205–209, `app.example.ini` Z. 1697), was Loopback- und private Adressen blockiert. Ein Empfänger auf demselben Host oder im LAN braucht `loopback`, `private` oder einen expliziten Host-Eintrag. Andernfalls schlägt jede Zustellung fehl.
- `[webhook] DELIVER_TIMEOUT` ist standardmäßig 5 s (`src:modules/setting/webhook.go`). Der Empfänger muss innerhalb dieser Zeit antworten. Er kann den PUT direkt ausführen, was schnell geht, oder erst bestätigen und dann ausführen.
- Webhooks dürfen nicht global deaktiviert sein (`setting.DisableWebhooks`, `src:services/webhook/webhook.go` Z. 162–165).
- Team-Variante: Das Repo muss einer Organisation gehören. Das Team mit `includes_all_repositories: true` und den gewünschten Unit-Rechten anlegen, dann das Bot-Konto als Mitglied hinzufügen.

## Latenz

- **Webhook**: `PrepareWebhook` schreibt eine `hook_task`-Zeile und legt ihre ID in die prozessinterne `webhook_sender`-Queue (`src:services/webhook/webhook.go` Z. 135–141, Z. 199 ff.). Ein Worker stellt sie dann zu. In der Praxis kommt nach dem Commit der Anlage-Anfrage weniger als eine Sekunde hinzu, plus der API-Aufruf des Empfängers. Das ist nicht synchron: Der Browser des Betreibers kann die Seite des neuen Repos erreichen, bevor das Bot-Konto hinzugefügt ist.
- **Team**: null. Der Zugriff wird innerhalb der Anlage-Transaktion vergeben.

## Fehlerfälle

| Fehler | Auswirkung | Abhilfe |
|---|---|---|
| Empfänger nicht erreichbar, Nicht-2xx oder Timeout (> `DELIVER_TIMEOUT`) | Task wird als zugestellt und fehlgeschlagen markiert. **Kein automatischer Retry.** `Deliver` markiert den Task *vor* dem Senden als zugestellt (`src:services/webhook/deliver.go`, `MarkTaskDelivered`). | Manuelles erneutes Senden unter „Letzte Zustellungen“ des Hooks (`ReplayHookTask`, `src:models/webhook/hooktask.go` Z. 154); periodischer Abgleich über `/user/repos` oder den Aktivitäts-Feed |
| Forgejo stoppt zwischen Einreihen und Senden | Nicht zugestellte Tasks werden beim Start neu eingereiht (`populateWebhookSendingQueue`, `src:services/webhook/deliver.go`) | nicht nötig |
| Host durch `ALLOWED_HOST_LIST` blockiert | Jede Zustellung schlägt fehl | Liste konfigurieren |
| Hook ohne `active` angelegt | Feuert nie | `active: true` übergeben |
| `POST /admin/hooks` ohne `is_system_webhook` | Legt einen Default-Hook an. Er feuert trotzdem für neue Repos (über die Kopie), hinterlässt aber eine Hook-Kopie in jedem Repo. `GET /admin/hooks` listet nur System-Hooks, der Default-Hook taucht dort also nicht auf (`src:routers/api/v1/admin/hooks.go` Z. 40). | Flag setzen; in der Admin-UI prüfen |
| Token des Empfängers widerrufen oder ohne Scope | PUT liefert 401/403. Die Webhook-Zustellung sieht trotzdem erfolgreich aus, wenn der Empfänger vor dem API-Aufruf mit 2xx antwortet. | Den Empfänger einen Fehlerstatus zurückgeben lassen, wenn der PUT fehlschlägt, damit der Fehler im Zustellprotokoll von Forgejo erscheint |
| Persönlicher Fork | Kein `repository`-Ereignis (nur `fork` am Quell-Repo) | Zusätzlich `fork` abonnieren oder auf den Abgleich setzen |
| Repo durch Migration angelegt | `repository: created` feuert | nicht nötig |
| Team-Variante, Repo unter persönlichem Konto angelegt | Team greift nicht | Repos unter der Organisation anlegen oder den Webhook nutzen |

## Auf der laufenden Instanz abgefragt (nur lesend)

- `GET /version` → `16.0.5+gitea-1.22.0`.
- `GET /admin/hooks` → `[]`: Es gibt keine System-Webhooks. Default-Hooks listet dieser Endpunkt nicht, ob welche existieren, zeigt er also nicht.
- Die Swagger enthält `/admin/hooks`, `/orgs/{org}/hooks`, `/user/hooks`, `/repos/{o}/{r}/hooks` und `/repos/{o}/{r}/hooks/git`. Es gibt keinen Endpunkt zum erneuten Zustellen eines Webhooks; das ist nur in der UI möglich.
- `app.ini` war aus dieser Sitzung nicht lesbar, die aktuellen Werte von `ALLOWED_HOST_LIST` und `DISABLE_WEBHOOKS` wurden also nicht geprüft.
