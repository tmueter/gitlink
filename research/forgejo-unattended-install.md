# Welche Wege gibt es, Forgejo 16 nicht-interaktiv zu installieren?

Ticket: dreamer/igit#8. Ziel: Forgejo 16.0.5 (`/api/v1/version` → `16.0.5+gitea-1.22.0`).
Quellen:
- Forgejo-Quellcode, Tag `v16.0.5` (Commit `8d24b7d52df327118cd776cf461d34e52e0ec1ce`), unten abgekürzt als `src:`
- Doku auf forgejo.org (Version v16.0): [Installation](https://forgejo.org/docs/latest/admin/installation/), [Docker](https://forgejo.org/docs/latest/admin/installation/docker/), [Binary](https://forgejo.org/docs/latest/admin/installation/binary/), [Config Cheat Sheet](https://forgejo.org/docs/latest/admin/config-cheat-sheet/), [Kommandozeile](https://forgejo.org/docs/latest/admin/command-line/)
- Paketliste [delightful-forgejo](https://codeberg.org/forgejo-contrib/delightful-forgejo#packaging)
- Lesende Prüfung der laufenden lokalen Instanz. Dabei wurde nichts installiert, gestartet oder geändert.

`src:` = `https://codeberg.org/forgejo/forgejo/src/tag/v16.0.5/`

## Antwort

Offiziell gibt es nur **zwei** Installationswege: das **Container-Image** (rootful oder rootless) und das **Binary mit systemd**. Distributionspakete listet die Doku als Community-Ressourcen, die „not extensively tested to work on every release“ sind ([Installation](https://forgejo.org/docs/latest/admin/installation/)).

**Alle drei Wege** lassen sich ohne Interaktion bis zu einer lauffähigen Instanz mit erstem Admin-Konto durchziehen. Das Muster ist immer dasselbe:

1. `app.ini` mit `[security] INSTALL_LOCK = true` und einem selbst erzeugten `SECRET_KEY` vorgeben. Beim Container geht das über Umgebungsvariablen.
2. `forgejo web` starten. Mit `INSTALL_LOCK` gibt es keinen Erststart-Assistenten, die Datenbank wird beim Start migriert. `INTERNAL_TOKEN` und die JWT-Secrets erzeugt Forgejo selbst und schreibt sie in `app.ini`.
3. `forgejo admin user create --admin …` **als Run-User** ausführen, beim Container mit `docker exec -u git`.

Für Zero-Touch empfiehlt sich das **rootful Docker-Image mit Compose**. Es ist offiziell, braucht nur Docker, legt alle Zustände unter einem einzigen Bind-Mount ab, erzeugt die SSH-Host-Keys selbst und lässt sich vollständig über `FORGEJO__section__KEY` steuern. Die lokale Instanz läuft bereits so (siehe unten). Die rootless-Variante eignet sich ebenso und kommt ohne OpenSSH im Container aus. Das Binary ist nur sinnvoll, wenn Docker fehlt, denn es braucht Root für Benutzer, Verzeichnisse und die Unit.

**Zwei Fallstricke aus dem Quellcode:**
- **Ohne `SECRET_KEY` fällt Forgejo still auf einen fest einkodierten Standardwert zurück** (`"!#@FDEWREWR&*("`, `src:modules/setting/security.go` Z. 266–271). Das Container-Template schreibt eine leere Zeile `SECRET_KEY =`. Der Web-Assistent erzeugt nur dann einen neuen Schlüssel, wenn `setting.SecretKey == ""` gilt (`src:routers/install/install.go` Z. 504–508). Wegen des Fallbacks trifft das nie zu. **Die lokale Instanz hat deshalb ein leeres `SECRET_KEY`**, sie verschlüsselt 2FA-Secrets u. Ä. also mit dem öffentlich bekannten Standardschlüssel. Die Ersteinrichtung muss den Schlüssel immer explizit setzen.
- **`admin user create` migriert die Datenbank nicht.** Es ruft nur `initDB` auf (`src:cmd/cmd.go` Z. 81–95). Vorher muss also entweder `forgejo web` einmal gelaufen sein (dessen Start migriert, `src:routers/common/db.go` Z. 46–53) oder `forgejo migrate` ausgeführt werden. Laut Doku ist `migrate` genau dafür da.

## Vergleich der Wege

| | Docker rootful (`codeberg.org/forgejo/forgejo:16`) | Docker rootless (`…:16-rootless`) | Binary + systemd | Distributionspaket |
|---|---|---|---|---|
| Status | offiziell | offiziell | offiziell | Community, nicht auf jedem Release getestet |
| Voraussetzungen | Docker plus Compose, Rechte am Docker-Socket (Root oder Gruppe `docker`) | wie rootful; der Container läuft als `1000:1000` | Root für Benutzer `git`, Verzeichnisse und Unit; `git` und `git-lfs` installiert | Root und Paketmanager der Distribution |
| Datenablage | Volume `/data`: `/data/gitea/conf/app.ini`, `/data/gitea/gitea.db`, `/data/git/repositories`, `/data/ssh` | Volume `/var/lib/gitea`: `custom/conf/app.ini`, `data/gitea.db`, `git/repositories`, `ssh/` | `/var/lib/forgejo` (Daten, 750) und `/etc/forgejo/app.ini` (anfangs beschreibbar, danach 640) | je nach Paket (nicht einzeln geprüft) |
| SSH | **OpenSSH** im Container (s6 startet `sshd`), Host-Keys ed25519/RSA/ECDSA unter `/data/ssh` | **eingebauter Go-SSH-Server** (`START_SSH_SERVER = true` fest im Template), Host-Key RSA 4096 unter `ssh/gitea.rsa` | System-OpenSSH des Hosts für den Benutzer `git`; alternativ der eingebaute Server auf einem anderen Port | je nach Paket |
| Ports im Container | 3000 (HTTP), 22 (SSH) | 3000, 2222 | 3000 auf dem Host; SSH 22 über System-sshd | meist 3000 |
| Doku-Mapping | `3000:3000`, `222:22` | `3000:3000`, `222:2222` | – | – |
| Erststart ohne Assistent | Umgebungsvariablen (siehe unten) | Umgebungsvariablen | `app.ini` vorab schreiben | `app.ini` des Pakets anpassen |

Belege: Docker-Doku; `src:Dockerfile` (`EXPOSE 22 3000`, `VOLUME ["/data"]`, `GITEA_CUSTOM=/data/gitea`, Symlink `forgejo → gitea` Z. 104); `src:Dockerfile.rootless` (`EXPOSE 2222 3000`, `USER 1000:1000`, `VOLUME ["/var/lib/gitea"]`, `GITEA_APP_INI=/var/lib/gitea/custom/conf/app.ini`); `src:docker/rootless/etc/templates/app.ini` („In rootless gitea container only internal ssh server is supported“); `src:docker/root/etc/s6/openssh/setup` (Erzeugung der Host-Keys); `src:modules/ssh/ssh.go` Z. 362 (`GenKeyPair`: RSA 4096); Binary-Doku; `src:contrib/systemd/forgejo.service` (`User=git`, `ExecStart=/usr/local/bin/forgejo web --config /etc/forgejo/app.ini`, `Type=notify`).

## Container: So wird der Erststart-Assistent übersprungen

Die Setup-Skripte (rootful `src:docker/root/etc/s6/gitea/setup`, rootless `src:docker/rootless/usr/local/bin/docker-setup.sh`) werten zwei Arten von Umgebungsvariablen aus.

**1. Template-Variablen, nur beim allerersten Start** (solange noch keine `app.ini` existiert): `APP_NAME`, `DOMAIN` (nur rootful), `SSH_DOMAIN`, `HTTP_PORT`, `ROOT_URL`, `DISABLE_SSH`, `SSH_PORT`, `SSH_LISTEN_PORT`, `LFS_START_SERVER` (nur rootful), `DB_TYPE`, `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWD`, `INSTALL_LOCK`, `DISABLE_REGISTRATION`, `REQUIRE_SIGNIN_VIEW`, `SECRET_KEY`. Daraus wird per `envsubst` die `app.ini` erzeugt.
- **Ist `SECRET_KEY` gesetzt und `INSTALL_LOCK` leer, wird `INSTALL_LOCK=true` automatisch gesetzt.** Das ist der eingebaute Zero-Touch-Schalter des Images.
- Diese Variablen stehen nur in den Skripten, nicht in der Doku, sind also weniger verbindlich.

**2. `FORGEJO__SECTION__KEY` (auch `GITEA__…`) bei jedem Start.** Danach läuft immer `environment-to-ini --config <app.ini>` und überschreibt die entsprechenden Schlüssel (`src:modules/setting/config_env.go` Z. 17: Präfix `^(FORGEJO|GITEA)__`).
- `FORGEJO__SECTION__KEY__FILE=/pfad` liest den Wert aus einer Datei, nützlich für Secrets.
- Punkte im Sektionsnamen werden als `_0X2E_` kodiert, z. B. `FORGEJO__LOG_0X2E_CONSOLE__…` (`src:contrib/environment-to-ini/environment-to-ini.go`).
- Das ist der dokumentierte Weg und wirkt auch auf eine bestehende Instanz.

**Falle beim SSH-Port (rootful):** `SSH_LISTEN_PORT` ist standardmäßig `$SSH_PORT`. Dasselbe `SSH_PORT` bestimmt über `src:docker/root/etc/s6/openssh/setup` auch den Port, auf dem `sshd` im Container lauscht. Die Template-Variable `SSH_PORT=2222` verschiebt deshalb auch `sshd` auf 2222, und das Mapping `2222:22` läuft ins Leere. Für den *angezeigten* Port in Clone-URLs ist `FORGEJO__server__SSH_PORT=2222` richtig. Es ändert nur `app.ini`, `sshd` bleibt auf 22. So ist die lokale Instanz eingerichtet. Alternativ setzt man `SSH_PORT=2222` zusammen mit `SSH_LISTEN_PORT=22`.

**Run-User und Root:** Forgejo verweigert den Start als Root („Forgejo is not supposed to be run as root“, `src:modules/setting/setting.go` Z. 183–187). Mit `INSTALL_LOCK` muss außerdem der aktuelle Benutzer dem `RUN_USER` entsprechen (ebenda Z. 198–205). `docker exec` läuft im rootful Image standardmäßig als Root, CLI-Befehle brauchen daher **`docker exec -u git`**. Im rootless Image ist der Standardbenutzer bereits 1000.

### Beispiel (rootful, Compose), aus den Quellen abgeleitet und nicht ausgeführt

```yaml
services:
  server:
    image: codeberg.org/forgejo/forgejo:16
    container_name: forgejo
    restart: always
    environment:
      - USER_UID=1000            # Eigentümer von ./data auf dem Host
      - USER_GID=1000
      - FORGEJO__security__INSTALL_LOCK=true
      - FORGEJO__security__SECRET_KEY__FILE=/run/secrets/secret_key   # oder SECRET_KEY beim Erststart
      - FORGEJO__server__DOMAIN=forge.example.lan
      - FORGEJO__server__SSH_DOMAIN=forge.example.lan
      - FORGEJO__server__ROOT_URL=http://forge.example.lan:3000/
      - FORGEJO__server__SSH_PORT=2222
      - FORGEJO__service__DISABLE_REGISTRATION=true
    volumes:
      - ./data:/data
      - ./secret_key:/run/secrets/secret_key:ro
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    ports:
      - "3000:3000"
      - "2222:22"
```

Ablauf der Ersteinrichtung:

```sh
openssl rand -hex 32 > secret_key   # alternativ `forgejo generate secret SECRET_KEY` mit einem vorhandenen Binary
docker compose up -d
until curl -fsS http://localhost:3000/api/healthz; do sleep 2; done   # Start migriert die DB
docker exec -u git forgejo forgejo admin user create --admin \
  --username betreiber --email betreiber@example.lan --random-password
# Bot-Konto gleich mit Token:
docker exec -u git forgejo forgejo admin user create \
  --username claude-bot --email bot@example.lan --random-password --must-change-password=false \
  --access-token --access-token-name igit --access-token-scopes write:repository,write:issue,write:user
```

Zu `admin user create` (`src:cmd/admin_user_create.go`):
- Ohne `--must-change-password` erzwingt Forgejo beim **ersten** Konto keinen Passwortwechsel, bei allen weiteren schon. Für das Bot-Konto deshalb `--must-change-password=false` setzen.
- `--random-password` gibt das Passwort auf stdout aus.
- `--access-token` gibt den Token einmalig auf stdout aus („Access token was successfully created… <token>“). Er gilt für alle Repos (`ResourceAllRepos: true`), die Scopes sind frei wählbar.
- Der Befehl ist nicht idempotent: Existiert der Benutzer schon, schlägt `CreateUser` fehl. Die Ersteinrichtung muss vorher prüfen, z. B. mit `forgejo admin user list`.

## Binary mit systemd: Zero-Touch-Variante

Die Binary-Doku beschreibt den Weg mit Web-Assistent. Ohne Interaktion geht es so:

1. Als Root: `git` und `git-lfs` installieren, Systembenutzer `git` anlegen, `/var/lib/forgejo` (git:git, 750) und `/etc/forgejo` anlegen, Binary nach `/usr/local/bin/forgejo`, Unit aus `src:contrib/systemd/forgejo.service`.
2. `/etc/forgejo/app.ini` selbst schreiben (mindestens `RUN_USER`, `WORK_PATH`, `[server]`, `[database]`, `[security] INSTALL_LOCK=true` und `SECRET_KEY`). Die Datei muss für `git` beim ersten Start **beschreibbar** sein, weil Forgejo `INTERNAL_TOKEN` und `JWT_SECRET` hineinschreibt (`src:modules/setting/security.go` Z. 126–155 und 244–258). Danach kann sie laut Doku auf 640 gesetzt werden.
3. `sudo -u git forgejo migrate -c /etc/forgejo/app.ini`, dann `sudo -u git forgejo admin user create … -c /etc/forgejo/app.ini`, danach `systemctl enable --now forgejo`.

SSH läuft hier über den System-`sshd` (Standard-Port 22, der Benutzer `git` erhält `authorized_keys`). Alternativ `START_SSH_SERVER = true` mit einem eigenen `SSH_LISTEN_PORT` > 1024. Ports unter 1024 braucht `cap_net_bind_service`.

## Distributionspakete

Laut delightful-forgejo: Alpine (`forgejo`, `forgejo-lts`), Arch (`extra/forgejo`), Debian/Ubuntu (inoffiziell `forgejo-deb`), Fedora und COPR, FreeBSD-Port, Gentoo GURU, NixOS-Modul `services.forgejo`, Snap (inoffiziell), Termux, YunoHost, Helm-Chart.

Nicht im Detail geprüft. Allgemein gilt: Pakete liefern Benutzer und Unit mit, Zero-Touch geht dann über dieselbe `app.ini` plus `forgejo admin user create`. Weil Forgejo 16 dort oft erst verzögert ankommt und die Pfade je Paket abweichen, taugen Pakete schlecht als universeller Weg für die Ersteinrichtung. Ausnahme ist NixOS, dessen Modul ohnehin deklarativ ist.

## `app.ini`-Vorgaben für Zero-Touch

| Einstellung | Wert | Grund |
|---|---|---|
| `[security] INSTALL_LOCK` | `true` | Assistent aus, `/install` liefert 404 |
| `[security] SECRET_KEY` | zufällig (`forgejo generate secret SECRET_KEY`) | sonst gilt der fest einkodierte Standardwert (s. o.) |
| `[server] ROOT_URL` | die URL, unter der Claude-Clients die Instanz erreichen | API-Links, Clone-URLs, Webhook-Payloads. Das Template setzt leer, dann gilt `%(PROTOCOL)s://%(DOMAIN)s:%(HTTP_PORT)s/` |
| `[server] DOMAIN`, `SSH_DOMAIN` | Hostname für Claude-Clients | `SSH_DOMAIN` ist standardmäßig `DOMAIN`, das wiederum `localhost` |
| `[server] SSH_PORT` | extern gemappter Port (z. B. 2222) | erscheint in SSH-Clone-URLs und wird für Host-Key-Pinning (`[host]:port`) gebraucht |
| `[service] DISABLE_REGISTRATION` | `true` | Konten legt nur die Ersteinrichtung bzw. der Betreiber an |
| `[service] REQUIRE_SIGNIN_VIEW` | nach Bedarf | schützt anonyme Lesezugriffe (auch per API) |
| `[repository] DEFAULT_PRIVATE` | `private` (optional) | Standard `last` |
| `[openid] ENABLE_OPENID_SIGNIN` | `false` (optional) | Standard ist `!InstallLock`, also `false` bei vorgegebenem Lock (`src:modules/setting/service.go` Z. 333). Der Web-Assistent schreibt dagegen explizit `true`, siehe lokale Instanz |
| `[webhook] ALLOWED_HOST_LIST` | nur bei Bedarf | Standard `external` (`src:services/webhook/deliver.go` Z. 205–209). Nur nötig, wenn Webhooks einen Empfänger auf Loopback oder im LAN erreichen sollen (vgl. `research/repo-creation-hooks.md` auf dem Branch `research/repo-creation-hooks`), dann `loopback`/`private` |
| `[server] OFFLINE_MODE` | Standard `true` | keine CDN- oder Gravatar-Zugriffe |
| `[database] DB_TYPE` | `sqlite3` | Standard im Image, keine weitere Abhängigkeit |

## Wie die lokale Instanz läuft (lesend geprüft)

- `docker ps` ist ohne Socket-Rechte nicht möglich. Laut `systemctl` läuft `docker.service` mit einem Container, im Prozessbaum stehen `s6-supervise gitea` und `/usr/local/bin/gitea web`. Das ist das **rootful Image**.
- Die Compose-Datei liegt in `~/Claude/local_access/forgejo/docker-compose.yml`: Image `codeberg.org/forgejo/forgejo:16`, `USER_UID/GID=1001`, `FORGEJO__server__SSH_PORT=2222`, Bind-Mount `./data:/data`, Ports `3000:3000` und `2222:22`.
- `app.ini` stammt aus dem **Web-Assistenten** (enthält `APP_SLOGAN`, `[openid] ENABLE_OPENID_SIGNIN = true`, `[mailer]`, `[cron.update_checker]`). Werte: `DOMAIN`/`SSH_DOMAIN = localhost`, `ROOT_URL = http://localhost:3000/`, `SSH_PORT = 2222`, `SSH_LISTEN_PORT = 22`, `INSTALL_LOCK = true`, `DISABLE_REGISTRATION = true`, `DB_TYPE = sqlite3`.
- Secrets (nur geprüft, ob gesetzt): `INTERNAL_TOKEN`, `JWT_SECRET` und `LFS_JWT_SECRET` sind gesetzt, **`SECRET_KEY` ist leer**.
- Port 2222 meldet `SSH-2.0-OpenSSH_10.2` (OpenSSH im Container). `GET /api/healthz` liefert `pass`, `GET /install` liefert 404.

## Offene Punkte

- Die Template-Variablen der Container-Skripte (`SECRET_KEY`, `INSTALL_LOCK` usw. ohne Präfix) sind nicht dokumentiert. Die Ersteinrichtung sollte sich nur auf `FORGEJO__…` verlassen.
- Ein `SECRET_KEY` lässt sich bei der bestehenden Instanz nicht einfach nachträglich setzen: Bereits verschlüsselte Daten (2FA u. Ä.) werden dann unlesbar. Ob die Instanz solche Daten hat, wurde nicht geprüft. Das ist ein Thema für ein eigenes Ticket.
- Die Distributionspakete wurden nicht einzeln geprüft (Pfade, mitgelieferte `app.ini`, Versionsstand von Forgejo 16).
