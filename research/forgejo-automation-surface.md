# Forgejo-Automatisierungsfläche für Bootstrap und Registrierung

Frage (Issue #2): Was lässt sich allein mit Forgejos Admin-CLI und REST-API auf dem Host der Instanz nicht-interaktiv erledigen: Konten anlegen (inkl. Bot-Konto), Access-Tokens erzeugen, öffentliche SSH-Schlüssel hinterlegen, Mitarbeiter hinzufügen, Repos im Namen eines Kontos/einer Organisation anlegen und den SSH-Host-Key der Instanz auslesen? Und: Lässt sich ein Access-Token auf bestimmte Repositories beschränken?

Ziel: Forgejo **16.0.5** (`GET /api/v1/version` → `16.0.5+gitea-1.22.0`). Quellen:

- **[swagger]** die Spezifikation der laufenden Instanz, `http://localhost:3000/swagger.v1.json` (abgerufen am 2026-09-30).
- **[src]** Forgejo-Quellcode beim Tag `v16.0.5`, `https://codeberg.org/forgejo/forgejo/src/tag/v16.0.5/<pfad>`.
- Lesende Abfrage der laufenden Instanz (`GET /users/dreamer/tokens`).

Auf der Instanz wurde nichts angelegt, geändert oder gelöscht.

## Kurzantwort

Alles auf der Liste lässt sich mit einem Site-Admin-Token und ohne Codeänderungen skripten. Die einzige Ausnahme ist das Auslesen des SSH-Host-Keys: Keine API liefert ihn, er muss von der Platte oder per `ssh-keyscan` auf dem Host gelesen werden. Zwei weitere Lücken: Es gibt keinen zugänglichen „Bot“-Kontotyp, und die CLI kann nur unbeschränkte Tokens erzeugen.

**Repo-beschränkte Tokens: ja, über die API.** Forgejo 16 hat repository-spezifische Access-Tokens. `POST /users/{username}/tokens` und `POST /admin/users/{username}/tokens` akzeptieren `"repositories": [{"owner","name"}, ...]`. Ein solcher Token:
- darf nur die Scopes `read:repository`, `write:repository`, `read:issue` oder `write:issue` tragen. `all`, `public-only` und jede andere Kategorie werden mit 400 abgelehnt.
- behält vollen Zugriff (bis zu den eigenen Rechten des Kontos) auf die aufgeführten Repos.
- kann weiterhin öffentliche Repos öffentlicher Eigentümer **lesen**. Private Repos oder Repos eingeschränkter/privater Eigentümer, die nicht aufgeführt sind, sieht er nicht.
- ignoriert den Site-Admin-Override (`AllowAdminOverride() == false`).

Die CLI (`forgejo admin user generate-access-token`, `admin user create --access-token`) erzeugt immer einen Token für alle Repos (`ResourceAllRepos = true`), daher muss ein repo-beschränkter Token über die API erzeugt werden.

## Fähigkeitstabelle

| Bedarf | CLI (auf dem Host, im Container) | REST-API | Rechte | Lücken |
|---|---|---|---|---|
| Konto anlegen | `forgejo admin user create --username U --email E (--password P \| --random-password) [--must-change-password=false] [--restricted] [--access-token --access-token-scopes S]` | `POST /admin/users` (`CreateUserOption`: username, email, password, must_change_password, restricted, visibility, full_name, send_notify…) | CLI: Host-/DB-Zugriff. API: Site-Admin + `write:admin` | Auf keinem Weg ein Feld für den Kontotyp, also kein Bot-Kontotyp (siehe unten). Die CLI verlangt ein Passwort oder `--random-password`. |
| Konto nach Anlage bearbeiten | `admin user must-change-password`, `change-password` | `PATCH /admin/users/{u}` (`EditUserOption`: prohibit_login, restricted, max_repo_creation, allow_create_organization, visibility, admin, active, …) | Site-Admin | Kann ein Bot-Konto härten (z. B. `prohibit_login`, `max_repo_creation: 0`, `allow_create_organization: false`), aber nicht seinen Typ ändern. |
| Token für ein anderes Konto erzeugen | `forgejo admin user generate-access-token -u U -t NAME --scopes S [--raw]` | `POST /admin/users/{u}/tokens` (Admin, Token-Auth genügt) oder `POST /users/{u}/tokens` (**verlangt Basic Auth** oder Reverse-Proxy-Auth, selbst oder Admin) | CLI: Host. Admin-API: Site-Admin + `write:admin` | CLI-Tokens gelten immer für alle Repos. Das Token-Geheimnis wird einmalig zurückgegeben (Feld `sha1`). Namen müssen pro Konto eindeutig sein. |
| SSH-Schlüssel am Konto hinterlegen | keine | `POST /admin/users/{u}/keys` (`CreateKeyOption`: title, key, read_only) als Admin, oder `POST /user/keys` als das Konto selbst | Site-Admin, oder das Konto mit `write:user` | Keine CLI. `read_only` gilt für Deploy-Keys (`POST /repos/{o}/{r}/keys`), die Repo-bezogene Alternative zu einem Kontoschlüssel. |
| Mitarbeiter hinzufügen | keine | `PUT /repos/{o}/{r}/collaborators/{u}` Body `{"permission":"read"\|"write"\|"admin"}` → 204 | Repo-Admin (`reqAdmin()`) + `write:repository` | Keine CLI. Organisations-Repos können stattdessen Teams nutzen. |
| Repo für ein Konto anlegen | keine | `POST /admin/users/{u}/repos` (`CreateRepoOption`) | Site-Admin | keine |
| Repo in einer Organisation anlegen | keine | `POST /orgs/{org}/repos` | Organisationsmitglied mit Recht zur Repo-Anlage (Owner oder Team mit create-repo) | keine |
| SSH-Host-Key der Instanz lesen | keine | **keine** | Dateisystem des Hosts oder Netzwerkzugang zum SSH-Port | Siehe Abschnitt zum Host-Key. `GET /signing-key.ssh` ist der Commit-Signaturschlüssel, **nicht** der Host-Key. |

## Details und Belege

### Konten und das Bot-Konto

- `POST /admin/users`: Route `m.Post("", bind(api.CreateUserOption{}), admin.CreateUser)` in der Gruppe `/admin`. Diese Gruppe ist durch `tokenRequiresScopes(AccessTokenScopeCategoryAdmin), reqToken(), reqSiteAdmin()` geschützt [src `routers/api/v1/api.go` Z. 1319–1415]. Body-Felder laut [swagger `CreateUserOption`].
- CLI-Flags laut [src `cmd/admin_user_create.go`]: `--username`, `--email`, `--password` / `--random-password`, `--must-change-password` (Standard true, außer beim allerersten Konto), `--restricted`, `--fullname`, `--admin`, `--access-token`, `--access-token-name`, `--access-token-scopes`. Es gibt kein Flag für den Kontotyp.
- Forgejo kennt im Modell einen Bot-Typ: `UserTypeBot // 4` und `IsBot()` [src `models/user/user.go` Z. 63–74, Z. 472]. Aber weder `CreateUserOption`/`EditUserOption` [swagger] noch die CLI können ihn setzen. **Lücke:** Das Bot-Konto wird ein gewöhnliches Einzelkonto. Man kann es mit `PATCH /admin/users/{u}` bot-ähnlich machen: `prohibit_login: true` sperrt Web-/Passwort-Login (gesondert prüfen, ob Tokens und SSH für ein solches Konto weiter funktionieren), dazu `max_repo_creation`, `allow_create_organization` und `restricted: true`. Mit `restricted` sieht das Konto nur Repos/Organisationen, die ihm ausdrücklich freigegeben wurden, was zu einem Bot-Konto passt.
- CLI-Unterbefehle unter `forgejo admin user`: create, list, change-password, delete, generate-access-token, must-change-password, reset-mfa sowie ein Befehl für autorisierte Integrationen [src `cmd/admin_user.go`]. Es gibt keine CLI für Schlüssel, Mitarbeiter oder Repos.

### Access-Tokens und Scopes

Scopes in 16.0.5 [src `models/auth/access_token_scope.go` Z. 55–85]:

- `all`
- `public-only` (Modifikator: beschränkt den Token auf öffentliche Organisationen/Repos)
- `read:`/`write:` für jeweils `activitypub`, `admin`, `misc` (Platzhalter), `notification`, `organization`, `package`, `issue`, `repository`, `user`

`write` schließt `read` ein.

- API-Routen:
  - `/users/{username}/tokens` POST verlangt `reqBasicOrRevProxyAuth(), reqToken()` unter `reqSelfOrAdmin()` [src `api.go` Z. 593–597]. Ein Token allein kann hier keinen Token erzeugen; nötig ist Basic Auth mit Benutzername und Passwort.
  - `/admin/users/{username}/tokens` GET/POST/DELETE liegen in der Admin-Gruppe und akzeptieren Token-Auth [src `api.go` Z. 1342–1346]. **Das ist der nicht-interaktive Weg**: Ein Admin-Token kann Tokens für das Bot-Konto erzeugen, ohne dessen Passwort zu kennen.
- Beide Routen nutzen `utils.CreateAccessToken` [src `routers/api/v1/utils/access_token.go`]:
  - lehnt einen doppelten Namen (400) und einen leeren Scope (400) ab.
  - mit gesetztem `repositories`: löst jedes `{owner,name}` auf. Jedes Repo, das der **Aufrufer** nicht sehen kann, ergibt „does not exist“ (400). Setzt `ResourceAllRepos=false`, validiert und speichert `AccessTokenResourceRepo`-Zeilen in derselben Transaktion.
  - ohne `repositories` wird `ResourceAllRepos=true` gesetzt.
- Validierung [src `services/authz/access_token.go` Z. 38–84]: Ein repo-spezifischer Token braucht ≥1 Repo, darf `public-only` nicht enthalten und nur `read:issue`, `write:issue`, `read:repository` oder `write:repository` tragen. Alles andere schlägt mit `ErrSpecifiedReposInvalidScope` fehl. Der Code-Kommentar erklärt den Grund: `write:organization` usw. würden die Repo-Prüfungen umgehen.
- Durchsetzung [src `services/authz/specific_repos_reducer.go`]:
  - aufgeführtes Repo: Zugriff unverändert, also begrenzt durch die bestehenden Rechte des Kontos.
  - nicht aufgeführtes privates Repo oder Repo eines nicht-öffentlichen Eigentümers: `AccessModeNone`.
  - nicht aufgeführtes öffentliches Repo: höchstens Lesen.
  - `AllowAdminOverride()` gibt false zurück, Admin-Rechte umgehen die Beschränkung also nicht.

  Folge: Ein repo-beschränkter Token des Bot-Kontos erreicht nur, was das Bot-Konto selbst erreicht. Man gibt dem Bot-Konto Mitarbeiterrechte und beschränkt den Token auf dasselbe Repo bzw. dieselben Repos.
- CLI: `generate-access-token` und `create --access-token` setzen fest `t.ResourceAllRepos = true`, mit dem Kommentar „maintain legacy behaviour until new CLI options are added“ [src `cmd/admin_user_generate_access_token.go` Z. 89–91, `cmd/admin_user_create.go` Z. 213–215]. **Lücke:** Die CLI kann keine repo-beschränkten Tokens erzeugen.
- Die laufende Instanz entspricht dem Schema: `GET /users/dreamer/tokens` liefert für die vorhandenen Tokens `scopes: ["all"]`, `repositories: null`, und [swagger `AccessToken.repositories`] dokumentiert null als „nicht beschränkt“.
- Henne-Ei-Problem beim Bootstrap: Der erste Admin-Token muss über die CLI (`forgejo admin user generate-access-token -u <betreiber> --scopes write:admin,...`) oder die UI entstehen. Danach geht alles Weitere über die API.

### SSH-Schlüssel

- `POST /admin/users/{username}/keys` → `admin.CreatePublicKey` [src `api.go` Z. 1331–1334, `routers/api/v1/admin/user.go` Z. 329]. Body `CreateKeyOption{title, key, read_only}` [swagger]. Es gelten die Schutzbedingungen der Admin-Gruppe.
- Alternativ kann der eigene Token des Bot-Kontos mit `write:user` `POST /user/keys` aufrufen.
- Repo-bezogene Alternative: Deploy-Keys, `POST /repos/{o}/{r}/keys` mit `read_only`. Sie gewähren SSH-Zugriff auf genau ein Repo, gehören aber dem Repo und keinem Konto, sodass Pushes nicht dem Bot-Konto zugeordnet werden.
- Nutzt die Instanz OpenSSH mit einer `authorized_keys`-Datei, schreibt Forgejo diese beim Hinzufügen von Schlüsseln selbst neu. `forgejo admin regenerate keys` existiert zur Neusynchronisation [src `cmd/admin.go` Z. 45–50].

### Mitarbeiter

- `PUT /repos/{owner}/{repo}/collaborators/{collaborator}` mit `reqToken()` + `reqAdmin()` (Repo-Admin, was Site-Admins erfüllen) [src `api.go` Z. 816–824]. Body `AddCollaboratorOption{permission: read|write|admin}` [swagger]. Liefert 204.
- `GET .../collaborators/{u}/permission` eignet sich für idempotente Prüfungen.

### Repositories im Namen eines Kontos/einer Organisation

- `POST /admin/users/{username}/repos` → `repo.CreateUserRepo(ctx, ctx.User(), form)`, Eigentümer ist das Konto aus dem Pfad [src `routers/api/v1/admin/repo.go`].
- `POST /orgs/{org}/repos` (und der Legacy-Alias `POST /org/{org}/repos`) für Organisations-Repos [swagger].
- `POST /admin/users/{username}/orgs` legt eine Organisation mit einem Konto als Eigentümer an [swagger].

### SSH-Host-Key der Instanz

- Kein REST-Endpunkt liefert ihn. Die Swagger-Spezifikation enthält nur `/signing-key.gpg`, `/signing-key.ssh` und das repo-bezogene `signing-key.gpg`; diese dienen der Commit-Signierung.
- Die maßgebliche Quelle hängt vom SSH-Server der Instanz ab:
  - **Eingebauter Go-SSH-Server** (`START_SSH_SERVER=true`): Schlüssel aus `[server] SSH_SERVER_HOST_KEYS`. Standard ist `ssh/gitea.rsa, ssh/gogs.rsa`, relativ zu `APP_DATA_PATH` [src `modules/setting/ssh.go` Z. 65, Z. 132–136].
  - **OpenSSH** (Standard im offiziellen rootful-Docker-Image, das sshd unter s6 betreibt): die üblichen `ssh_host_*_key.pub`-Dateien. Im Docker-Image werden sie unter `/data/ssh/` erzeugt. Das stammt aus dem s6-OpenSSH-Setup des Images und wurde nicht am Container dieser Instanz verifiziert.
- Live-Abfrage: `ssh_url` des Repos ist `ssh://git@localhost:2222/...`, und `ssh-keyscan -p 2222 localhost` liefert ed25519-, rsa- und ecdsa-sha2-nistp256-Host-Keys. Der eingebaute Server nutzt standardmäßig einen einzelnen RSA-Schlüssel (`gitea.rsa`); drei Standardtypen sprechen also für OpenSSH im Container auf Port 2222.
- Nicht-interaktive Möglichkeiten auf dem Host, nach Vertrauenswürdigkeit geordnet:
  1. die `.pub`-Datei(en) vom Datenvolume lesen.
  2. `ssh-keyscan -p <SSH_PORT> localhost` **auf dem Host selbst** ausführen. Über Loopback abgerufen ist das kein Netzwerk-TOFU-Risiko.

  Das Ergebnis dann an Claude-Clients für Host-Key-Pinning weitergeben. Den Clients `SSH_DOMAIN`/`SSH_PORT` der Instanz mitteilen; `ssh_url` des Repos in `GET /repos/{o}/{r}` zeigt, was Clients ansteuern werden.
- **Lücke:** Ein entfernter Claude-Client kann den Host-Key nicht authentifiziert von der Forge abrufen. Der Installer auf dem Host muss ihn übertragen, oder der Betreiber veröffentlicht ihn an einer Stelle, der der Client bereits vertraut, z. B. als Datei in einem Repo, das per HTTPS mit Token abgerufen wird.

## Zusammenfassung der Lücken

1. Kein Bot-Kontotyp per CLI/API. Ein normales Konto verwenden, mit `PATCH /admin/users/{u}` härten (`restricted`, `max_repo_creation`, `allow_create_organization`, ggf. `prohibit_login`) und „Bot“ in den vollen Namen schreiben.
2. Die CLI kann keine repo-beschränkten Tokens erzeugen. `POST /admin/users/{bot}/tokens` mit `repositories` verwenden.
3. Repo-beschränkte Tokens sind auf `repository`- + `issue`-Scopes begrenzt und erlauben weiterhin Lesen öffentlicher Repos.
4. `POST /users/{u}/tokens` verlangt Basic Auth. Die Admin-Variante nicht.
5. Keine CLI für Schlüssel, Mitarbeiter oder Repos. Das geht nur über die API und erfordert einen Site-Admin-Token, der seinerseits einmalig über die CLI entsteht.
6. Keine API für den SSH-Host-Key. Von der Platte lesen oder `ssh-keyscan` auf dem Host.
