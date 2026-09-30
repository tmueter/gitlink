# Gitea 28.0.0 im Vergleich zu Forgejo 16: alles, was der Skill `igit` nutzt

Ticket: „Worin unterscheidet sich die aktuelle Gitea-Version von Forgejo 16 bei allem, was der Skill nutzt?“ (Map: „Wayfinder: Skill für Forgejo und Gitea (GitLab prüfen)“)

Stand: 30.09.2026. Verglichen wurden `skill/igit/igit.py` und `docs/spec-igit-skill.md` auf `main` (Commit `a348e48`) mit Gitea **v28.0.0** und der lokalen Forgejo-Instanz **16.0.5+gitea-1.22.0**.

## Kernaussage

Der Skill läuft heute **nicht** gegen Gitea. Er erkennt Gitea gar nicht erst als Instanz, findet keinen Gitea-Container und scheitert spätestens an der Token-Verwaltung. Die gute Nachricht: Fast alles andere ist identisch, und die einzige echte Lücke hat einen sauberen Ersatz.

1. **Fehlend:** `GET/POST /admin/users/{u}/tokens` und `DELETE /admin/users/{u}/tokens/{token}` gibt es in Gitea nicht. Ersatz: `GET/POST /users/{u}/tokens` und `DELETE /users/{u}/tokens/{id-oder-name}`. Ein Site-Admin darf dort die Tokens fremder Konten verwalten, aber **nur mit Basic-Authentifizierung**. Der Header `Authorization: token …` wird mit 401 abgewiesen; `Authorization: Basic base64(<betreiber>:<admin-token>)` funktioniert, weil Gitea einen Token im Passwortfeld als Basic-Anmeldung zählt.
2. **Abweichend:** Versionserkennung. Gitea kennt `/api/forgejo/v1/version` nicht, und `/api/v1/version` liefert eine reine Versionsnummer (`28.0.0`) ohne `+gitea-…`. Die heutige Funktion `forgejo_version()` liefert für Gitea deshalb `None`.
3. **Abweichend:** Image und Umgebungsvariablen. Image `docker.gitea.com/gitea:28` statt `codeberg.org/forgejo/forgejo:16`, nur `GITEA__…` statt `FORGEJO__…`, Befehl `gitea` statt `forgejo`. Forgejo 16 versteht beides (`gitea`-Befehl und `GITEA__`-Präfix), ein gemeinsamer Weg ist also möglich.
4. **Gleich:** Pfade im rootful Image (`/data/gitea/conf/app.ini`, `/data/ssh/ssh_host_*_key.pub`), alle übrigen genutzten API-Endpunkte, alle Felder, die der Skill sendet, die Token-Scopes, `restricted`, die CLI-Befehle `admin user create/list/generate-access-token` samt `--raw`.

## Aktuelle stabile Gitea-Version

Gitea **v28.0.0**, veröffentlicht am 29.09.2026, ist die aktuelle stabile Version. Gitea ist damit von der Zählung `1.x` auf eine Hauptversion `28` umgestiegen; die Vorgängerversion war v1.27.3 vom 29.08.2026.

- Quelle: GitHub-Release-API `repos/go-gitea/gitea/releases/latest` → `v28.0.0`, `published_at 2026-09-29T23:25:53Z`, kein Pre-Release.
- Quelle: <https://docs.gitea.com/installation/install-with-docker> nennt `image: docker.gitea.com/gitea:28.0.0`.
- Quelle: Docker Hub `gitea/gitea` hat die Tags `28`, `28.0`, `28.0.0`, `latest` und die jeweiligen `-rootless`-Varianten; `docker.gitea.com/v2/gitea/manifests/28` antwortet mit 200.

Da die Version einen Tag alt ist, gilt alles Folgende für diesen Tag. Alle Quellcode-Verweise beziehen sich auf <https://github.com/go-gitea/gitea/tree/v28.0.0> (Commit `15b8a5805adf`). Abkürzung im Folgenden: `G:` = `https://github.com/go-gitea/gitea/blob/v28.0.0/`.

## Vergleich im Einzelnen

### 1. Versionserkennung und Unterscheidung Gitea/Forgejo

| Punkt | Forgejo 16 | Gitea 28.0.0 | Urteil |
|---|---|---|---|
| `GET /api/forgejo/v1/version` | 200, `{"version":"16.0.5+gitea-1.22.0"}` | Route existiert nicht; `routers/api` enthält keine `forgejo`-Route | **fehlend** |
| `GET /api/v1/version` | 200, `{"version":"16.0.5+gitea-1.22.0"}` | 200, `{"version":"<AppVer>"}`, also z. B. `28.0.0` | **abweichend** (kein `+gitea-`-Suffix) |
| Swagger `info.title` (`/swagger.v1.json`) | `Forgejo API` | `Gitea API` | abweichend |

Belege: `G:routers/api/v1/api.go` Zeile 1092 (`m.Get("/version", misc.Version)`), `G:routers/api/v1/misc/version.go` Zeile 24 (`structs.ServerVersion{Version: setting.AppVer}`), `G:templates/swagger/v1-swagger.generated.json` (`"title": "Gitea API"`). Forgejo-Werte stammen aus Aufrufen gegen die lokale Instanz.

Folge für den Skill: `forgejo_version()` in `igit.py` akzeptiert `/api/v1/version` nur, wenn die Antwort `gitea` enthält. Das trifft auf Forgejo zu (`+gitea-1.22.0`), aber nicht auf Gitea. Gitea wird deshalb als „keine Forgejo-Instanz“ abgelehnt.

Sichere Unterscheidung: Antwortet `GET /api/forgejo/v1/version` mit 200 und JSON, ist es Forgejo. Sonst, wenn `GET /api/v1/version` mit 200 und JSON antwortet, ist es Gitea (oder ein anderer Gitea-Abkömmling). Die Prüfung auf den Teilstring `gitea` in der Versionsnummer ist dafür ungeeignet, weil Gitea ihn gerade nicht liefert. [Unsicher] Andere Gitea-Abkömmlinge ohne `/api/forgejo` würden so ebenfalls als Gitea gelten; als zusätzliche Bestätigung taugt `info.title` der Swagger-Datei, sofern Swagger nicht per `ENABLE_SWAGGER=false` abgeschaltet ist.

### 2. Admin-CLI

| Befehl, wie der Skill ihn nutzt | Gitea 28.0.0 | Urteil |
|---|---|---|
| Programmname `forgejo` im Container | Nur `gitea` (`/usr/local/bin/gitea`, Wrapper für `/app/gitea/gitea`) | **abweichend** |
| `admin user list --admin` | vorhanden, Ausgabe `ID  Username  Email  IsActive` | gleich (der Parser liest Spalte 1 und 2) |
| `admin user create --admin --username --email --password --must-change-password=false` | alle Flags vorhanden, zusätzlich `--user-type User|Bot`, `--restricted`, `--access-token` | gleich |
| `admin user generate-access-token -u <u> -t <name> --scopes <liste> --raw` | alle Flags vorhanden: `--username/-u`, `--token-name/-t`, `--scopes` (Standard `all`), `--raw` gibt nur den Token aus | gleich |
| Token per CLI löschen | Kein Befehl vorhanden; `admin user` hat nur `create, list, change-password, delete, generate-access-token, must-change-password, disable-2fa, change-type` | fehlend (in Forgejo ebenfalls nicht genutzt) |

Belege: `G:cmd/admin_user.go` Zeilen 28–45, `G:cmd/admin_user_list.go` Zeilen 41–47, `G:cmd/admin_user_create.go` Zeilen 22–97, `G:cmd/admin_user_generate_access_token.go`, `G:docker/root/usr/local/bin/gitea`.

Gemeinsamer Weg: Das Forgejo-Image legt `/usr/local/bin/forgejo` als Symlink auf das Skript `gitea` an (`https://codeberg.org/forgejo/forgejo/src/branch/v16.0/forgejo/Dockerfile` Zeile 104: `RUN cd /usr/local/bin ; ln -s gitea forgejo`). `docker exec -u git <container> gitea admin …` funktioniert also in beiden Images. [Unsicher] Für eine Forgejo-Installation ohne Container (`--admin-exec`) gilt das nicht zwingend.

### 3. Container-Image, Pfade, Umgebungsvariablen

| Punkt | Forgejo 16 (Skill heute) | Gitea 28.0.0 | Urteil |
|---|---|---|---|
| Image (rootful) | `codeberg.org/forgejo/forgejo:16` | `docker.gitea.com/gitea:28` (Spiegel: `gitea/gitea:28` auf Docker Hub) | **abweichend** |
| Image (rootless) | `…:16-rootless` | `docker.gitea.com/gitea:28-rootless`; Pfade dort `/etc/gitea/app.ini` und `/var/lib/gitea`, kein eigener sshd | abweichend, vom Skill nicht genutzt |
| Container-Erkennung `Host.containers()` | sucht `forgejo` im Image-Namen | Image-Name enthält `gitea`, nicht `forgejo` | **abweichend** (Gitea-Container wird nicht gefunden) |
| `app.ini` im rootful Image | `/data/gitea/conf/app.ini` | `/data/gitea/conf/app.ini` (`GITEA_CUSTOM=/data/gitea`, Datei `${GITEA_CUSTOM}/conf/app.ini`) | gleich |
| SSH-Host-Keys | `/data/ssh/ssh_host_{ed25519,ecdsa,rsa}_key.pub` | dieselben drei Dateien, beim ersten Start erzeugt; `chown root:root`, `chmod 0600` auf alle Dateien in `/data/ssh` | gleich (Lesen per `docker exec` ohne `-u` läuft als root und klappt) |
| Präfix für Konfiguration | `FORGEJO__section__KEY` | nur `GITEA__section__KEY` (auch `…__FILE`) | **abweichend** |
| `INSTALL_LOCK`, `SECRET_KEY` | per `FORGEJO__security__…` gesetzt | `GITEA__security__INSTALL_LOCK`, `GITEA__security__SECRET_KEY`; zusätzlich setzt das Entrypoint-Skript `INSTALL_LOCK=true`, wenn beim ersten Start `SECRET_KEY` gesetzt ist | gleich bis auf das Präfix |
| `ROOT_URL`, `SSH_DOMAIN`, `SSH_PORT`, `DISABLE_REGISTRATION` | `FORGEJO__server__…`, `FORGEJO__service__…` | `GITEA__server__…`, `GITEA__service__…` | gleich bis auf das Präfix |
| Ports im Container | 3000 Web, 22 SSH | 3000 Web, 22 SSH (`EXPOSE 22 3000`) | gleich |

Belege: `G:Dockerfile` (Ende: `EXPOSE 22 3000`, `ENV GITEA_CUSTOM=/data/gitea`, `VOLUME ["/data"]`), `G:Dockerfile.rootless`, `G:docker/root/etc/s6/gitea/setup`, `G:docker/root/etc/s6/openssh/setup`, `G:docker/root/usr/local/bin/environment-to-ini` (`gitea config edit-ini --in-place --apply-env`), `G:modules/setting/config_env.go` Zeile 17 (`EnvConfigKeyPrefixGitea = "GITEA__"`), `G:cmd/config.go` Zeilen 38–53, <https://docs.gitea.com/installation/install-with-docker>.

Gemeinsamer Weg: Forgejo 16 akzeptiert beide Präfixe (`https://codeberg.org/forgejo/forgejo/src/branch/v16.0/forgejo/modules/setting/config_env.go` Zeile 17: `EnvConfigKeyPrefixGitea = "^(FORGEJO|GITEA)__"`). Eine Compose-Datei mit `GITEA__…` funktioniert also für beide.

### 4. API-Endpunkte

Grundlage: `G:templates/swagger/v1-swagger.generated.json` gegen `/swagger.v1.json` der lokalen Forgejo-16-Instanz, plus Router `G:routers/api/v1/api.go`.

| Endpunkt (wie im Skill) | Gitea 28.0.0 | Urteil |
|---|---|---|
| `GET /users/{u}` | vorhanden | gleich |
| `POST /admin/users` | vorhanden; `CreateUserOption` hat dieselben Felder wie Forgejo (`restricted`, `send_notify`, `must_change_password`, …) | gleich |
| `PATCH /admin/users/{u}` | vorhanden; Felder `login_name`, `source_id`, `restricted`, `max_repo_creation`, `allow_create_organization`, `full_name` vorhanden. Gitea hat zusätzlich `type` (`User`/`Bot`), Forgejo zusätzlich `hide_email`, `pronouns` | gleich für alles Genutzte |
| `GET /users/{u}/keys` | vorhanden | gleich |
| `POST /admin/users/{u}/keys` (`title`, `key`, `read_only`) | vorhanden, `CreateKeyOption` identisch | gleich |
| `DELETE /admin/users/{u}/keys/{id}` | vorhanden | gleich |
| `GET /admin/users/{u}/tokens` | **nicht vorhanden** | **fehlend** |
| `POST /admin/users/{u}/tokens` | **nicht vorhanden** | **fehlend** |
| `DELETE /admin/users/{u}/tokens/{token}` | **nicht vorhanden** | **fehlend** |
| `GET/POST /users/{u}/tokens`, `DELETE /users/{u}/tokens/{token}` | vorhanden, nur mit Basic-Authentifizierung, Site-Admin darf fremde Konten | Ersatz, siehe Abschnitt 5 |
| `GET /user` | vorhanden | gleich |
| `GET /user/orgs` | vorhanden; braucht Token-Scopes der Kategorien `user` **und** `organization` | gleich (Admin-Token hat beide) |
| `GET /user/repos`, `POST /user/repos` | vorhanden | gleich |
| `POST /orgs/{org}/repos` | vorhanden | gleich |
| `GET/PUT /repos/{o}/{r}/collaborators/{u}` (`permission`: `read`/`write`/`admin`) | vorhanden, `AddCollaboratorOption` identisch | gleich |
| `GET/POST /repos/{o}/{r}/milestones` (`state=all`, `limit`, `title`) | vorhanden | gleich |
| `GET/PATCH /repos/{o}/{r}` mit `archived` | vorhanden | gleich |
| `DELETE /repos/{o}/{r}` | vorhanden | gleich |

Admin-Routen in Gitea 28.0.0 unter `/admin/users/{username}`: `PATCH`, `DELETE`, `keys` (POST), `keys/{id}` (DELETE), `orgs`, `repos`, `rename`, `badges`. Kein `tokens` (`G:routers/api/v1/api.go` Zeilen 1894–1910).

Zusätzlich in Gitea 28.0.0, in Forgejo 16 nicht vorhanden: eine **Projekt-API** (`/repos/{o}/{r}/projects…`, `/orgs/{org}/projects…`, `/user/projects…`, eingeführt mit PR #38691). Der manuelle Schritt „Projektboard anlegen“ aus Abschnitt 4 der Spezifikation ließe sich unter Gitea automatisieren. Außerdem `DELETE /token` zum Löschen des gerade benutzten Tokens (`G:routers/api/v1/api.go` Zeilen 1113–1116).

### 5. Wie ein Admin unter Gitea fremde Tokens verwaltet

Das ist der einzige Punkt, an dem der Skill einen anderen Weg braucht.

Route (`G:routers/api/v1/api.go` Zeilen 1145–1149):

```go
m.Group("/tokens", func() {
    m.Combo("").Get(user.ListAccessTokens).
        Post(bind(api.CreateAccessTokenOption{}), reqToken(), user.CreateAccessToken)
    m.Combo("/{id}").Delete(reqToken(), user.DeleteAccessToken)
}, reqSelfOrAdmin(), reqBasicOrRevProxyAuth())
```

- `reqSelfOrAdmin()` lässt einen Site-Admin auf die Tokens jedes Kontos zu (`api.go` Zeilen 442–449).
- `reqBasicOrRevProxyAuth()` verlangt `ctx.IsBasicAuth` (`api.go` Zeilen 400–410). Das ist wahr, wenn die Anmeldemethode `basic` war (`G:routers/common/auth.go` Zeile 28).
- Die API prüft der Reihe nach OAuth2 (`Authorization: token …` bzw. `Bearer …`), HTTP-Signatur und Basic (`api.go` Zeilen 910–921). Ein Token im Header `Authorization: token …` meldet also die Methode `oauth2` an, und die Token-Routen antworten mit **401 „auth required“**.
- Ein Token im Basic-Header (`Benutzer:Token`, oder `Token:` bzw. `Token:x-oauth-basic`) wird von der Basic-Methode als Personal Access Token erkannt (`G:services/auth/basic.go` Zeilen 47–116). Die Anmeldemethode ist dann `basic`, und die Route ist erlaubt. Gitea testet genau das: `TestAPICreateTokenScopeEscalation` legt Tokens mit `SetBasicAuth(user.Name, writeUserToken)` an (`G:tests/integration/api_token_test.go` Zeilen 35–88).
- `TestAPIDeleteTokensPermission` belegt, dass ein Admin fremde Tokens per Name löschen darf (`api_token_test.go` Zeilen 123–147). Dieser Test meldet den Admin mit Passwort an; dass derselbe Weg mit Admin-Token im Basic-Header funktioniert, folgt aus dem Code, ist aber nicht eigens getestet. [Unsicher]
- `DELETE /users/{u}/tokens/{token}` nimmt eine ID oder, wenn der Wert keine Zahl ist, einen Namen; mehrere Treffer ergeben 422 (`G:routers/api/v1/user/app.go` Zeilen 194–216). Das entspricht dem heutigen Aufruf mit Name bzw. ID.
- `POST /users/{u}/tokens` lehnt mit 403 ab, wenn der neue Token mehr Rechte hätte als der anmeldende Token (`app.go` Zeilen 132–141). Der Admin-Lauf-Token des Skills (`write:admin,write:repository,write:user,write:issue,write:organization`) deckt die Client-Scopes (`write:repository`, `write:issue`, `read:user`) ab.
- Benötigter Scope: Kategorie `user`, also `write:user` für POST und DELETE. Der Lauf-Token hat ihn.

Konkreter Ersatz für die drei Aufrufe:

| Heute (Forgejo) | Gitea 28.0.0 |
|---|---|
| `GET /admin/users/{u}/tokens`, Header `Authorization: token <admin>` | `GET /users/{u}/tokens`, Header `Authorization: Basic base64(<betreiber>:<admin-token>)` |
| `POST /admin/users/claude-bot/tokens` | `POST /users/claude-bot/tokens`, Basic wie oben |
| `DELETE /admin/users/{u}/tokens/{name-oder-id}` | `DELETE /users/{u}/tokens/{name-oder-id}`, Basic wie oben |
| Lauf-Token am Ende löschen | wie oben, oder `DELETE /token` mit `Authorization: token <lauf-token>` |

Alternative für das Anlegen: `gitea admin user generate-access-token -u claude-bot -t igit-<client> --scopes write:repository,write:issue,read:user --raw` über `docker exec`. Für das Löschen gibt es keinen CLI-Befehl.

[Unsicher] Ob die Forgejo-16-Routen `/users/{u}/tokens` mit Basic-Token genauso funktionieren, wurde nicht geprüft. Wenn ja, könnte der Skill für beide Systeme denselben Weg nehmen. Das wäre die nächste Frage, bevor man den Code verzweigt.

### 6. Token-Scopes

| Scope | Gitea 28.0.0 |
|---|---|
| `write:admin`, `write:repository`, `write:user`, `write:issue`, `write:organization` (Lauf-Token) | alle vorhanden |
| `write:repository`, `write:issue`, `read:user` (Client-Token) | alle vorhanden |

Beleg: `G:models/auth/access_token_scope.go` Zeilen 56–84 (Kategorien `activitypub`, `admin`, `misc`, `notification`, `organization`, `package`, `issue`, `repository`, `user`, dazu `all` und `public-only`). Urteil: **gleich**. Forgejo kennt zusätzlich repository-spezifische Tokens (`CreateAccessTokenOption.repositories`), die der Skill nicht nutzt.

### 7. `restricted`-Konten

`restricted` existiert in Gitea 28.0.0 unverändert in `CreateUserOption` und `EditUserOption` (`G:modules/structs/admin_user.go` Zeilen 28–29 und 75–76) und als CLI-Flag `--restricted`. Urteil: **gleich**.

Neu in Gitea 28.0.0 ist ein eigener Kontotyp **Bot** (PR #38966: „manage bot accounts from the admin UI, API and CLI“), setzbar per `PATCH /admin/users/{u}` mit `"type": "Bot"` oder `gitea admin user create --user-type Bot`. Ein Bot-Konto darf weder Passwort noch `login_name` noch `source_id` ≠ 0 haben (`G:routers/api/v1/admin/user.go` Zeile 210). Der Skill braucht das nicht; wer es nutzen will, darf beim `PATCH` dann `login_name` nicht mitsenden.

## Was sich am Skill ändern müsste

Das ist eine Ableitung aus den Befunden, keine Entscheidung.

1. Versionserkennung zweistufig: `/api/forgejo/v1/version` → Forgejo; sonst `/api/v1/version` → Gitea.
2. Container-Erkennung: Image-Namen mit `gitea` zusätzlich zu `forgejo` akzeptieren.
3. CLI-Aufruf im Container einheitlich über `gitea` (funktioniert in beiden Images).
4. Installation: Compose-Datei mit `GITEA__…` für beide Systeme; Image je nach Wahl.
5. Token-Verwaltung unter Gitea über `/users/{u}/tokens` mit Basic-Header.

## Quellen

- GitHub-Release: <https://github.com/go-gitea/gitea/releases/tag/v28.0.0>
- Quellcode am Tag: <https://github.com/go-gitea/gitea/tree/v28.0.0>, insbesondere `routers/api/v1/api.go`, `routers/api/v1/user/app.go`, `routers/api/v1/token/token.go`, `services/auth/basic.go`, `services/auth/group.go`, `routers/common/auth.go`, `cmd/admin_user*.go`, `modules/setting/config_env.go`, `models/auth/access_token_scope.go`, `Dockerfile`, `Dockerfile.rootless`, `docker/root/…`, `tests/integration/api_token_test.go`
- Swagger am Tag: `templates/swagger/v1-swagger.generated.json`
- Doku: <https://docs.gitea.com/installation/install-with-docker>
- Docker Hub: <https://hub.docker.com/r/gitea/gitea/tags>
- Forgejo v16.0: <https://codeberg.org/forgejo/forgejo/src/branch/v16.0/forgejo/Dockerfile>, <https://codeberg.org/forgejo/forgejo/src/branch/v16.0/forgejo/modules/setting/config_env.go>
- Lokale Forgejo-Instanz (nur lesend): `GET /api/v1/version`, `GET /api/forgejo/v1/version`, `GET /swagger.v1.json`
