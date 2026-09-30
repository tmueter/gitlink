# Forgejo automation surface for bootstrap and enrollment

Question (issue #2): using only Forgejo's admin CLI and REST API on the Instance's host, what can be done non-interactively to create users (incl. a Bot account), mint access tokens, register SSH public keys, add collaborators, create repos on behalf of a user/org, and read the Instance's SSH host key? And: can an access token be restricted to specific repositories?

Target: Forgejo **16.0.5** (`GET /api/v1/version` → `16.0.5+gitea-1.22.0`). Sources:

- **[swagger]** the live instance's spec, `http://localhost:3000/swagger.v1.json` (fetched 2026-09-30).
- **[src]** Forgejo source at tag `v16.0.5`, `https://codeberg.org/forgejo/forgejo/src/tag/v16.0.5/<path>`.
- Read-only probe of the live instance (`GET /users/dreamer/tokens`).

Nothing was created, modified or deleted on the instance.

## Short answer

Everything on the list can be scripted with a site-admin token and no code changes. The one exception is reading the SSH host key: no API returns it, so it has to be read from disk or with `ssh-keyscan` on the host. Two more gaps: there is no "bot" user type exposed, and the CLI can only mint unrestricted tokens.

**Per-repo tokens: yes, over the API.** Forgejo 16 has repository-specific access tokens. `POST /users/{username}/tokens` and `POST /admin/users/{username}/tokens` accept `"repositories": [{"owner","name"}, ...]`. Such a token:
- may only carry `read:repository`, `write:repository`, `read:issue` or `write:issue` scopes. `all`, `public-only` and every other category are rejected with 400.
- keeps full access (up to the user's own permission) to the listed repos.
- can still **read** public repos of public owners. It cannot see private repos, or repos of limited/private owners, that are not listed.
- ignores site-admin override (`AllowAdminOverride() == false`).

The CLI (`forgejo admin user generate-access-token`, `admin user create --access-token`) always makes an all-repos token (`ResourceAllRepos = true`), so a repo-limited token has to be minted over the API.

## Capability table

| Need | CLI (on host, in the container) | REST API | Privilege | Gaps |
|---|---|---|---|---|
| Create user | `forgejo admin user create --username U --email E (--password P \| --random-password) [--must-change-password=false] [--restricted] [--access-token --access-token-scopes S]` | `POST /admin/users` (`CreateUserOption`: username, email, password, must_change_password, restricted, visibility, full_name, send_notify…) | CLI: host/DB access. API: site admin + `write:admin` | No user-type field on either path, so no Bot user type (see below). CLI requires a password or `--random-password`. |
| Edit user after creation | `admin user must-change-password`, `change-password` | `PATCH /admin/users/{u}` (`EditUserOption`: prohibit_login, restricted, max_repo_creation, allow_create_organization, visibility, admin, active, …) | site admin | Can harden a Bot account (e.g. `prohibit_login`, `max_repo_creation: 0`, `allow_create_organization: false`) but cannot change its type. |
| Mint token for another user | `forgejo admin user generate-access-token -u U -t NAME --scopes S [--raw]` | `POST /admin/users/{u}/tokens` (admin, token auth OK) or `POST /users/{u}/tokens` (**requires basic auth** or reverse-proxy auth, self or admin) | CLI: host. Admin API: site admin + `write:admin` | CLI tokens are always all-repos. Token secret is returned once (`sha1` field). Names must be unique per user. |
| Register SSH key on user | none | `POST /admin/users/{u}/keys` (`CreateKeyOption`: title, key, read_only) as admin, or `POST /user/keys` as the user itself | site admin, or the user with `write:user` | No CLI. `read_only` applies to deploy keys (`POST /repos/{o}/{r}/keys`), which are the per-repo alternative to a user key. |
| Add collaborator | none | `PUT /repos/{o}/{r}/collaborators/{u}` body `{"permission":"read"\|"write"\|"admin"}` → 204 | repo admin (`reqAdmin()`) + `write:repository` | No CLI. Org repos can use teams instead. |
| Create repo for a user | none | `POST /admin/users/{u}/repos` (`CreateRepoOption`) | site admin | none |
| Create repo in an org | none | `POST /orgs/{org}/repos` | org member allowed to create repos (owner, or team with create-repo) | none |
| Read Instance SSH host key | none | **none** | host filesystem, or network access to the SSH port | See the host key section. `GET /signing-key.ssh` is the commit-signing key, **not** the host key. |

## Details and citations

### Users and the Bot account

- `POST /admin/users`: route `m.Post("", bind(api.CreateUserOption{}), admin.CreateUser)` inside the `/admin` group. That group is guarded by `tokenRequiresScopes(AccessTokenScopeCategoryAdmin), reqToken(), reqSiteAdmin()` [src `routers/api/v1/api.go` L1319–1415]. Body fields per [swagger `CreateUserOption`].
- CLI flags per [src `cmd/admin_user_create.go`]: `--username`, `--email`, `--password` / `--random-password`, `--must-change-password` (defaults true, except for the very first user), `--restricted`, `--fullname`, `--admin`, `--access-token`, `--access-token-name`, `--access-token-scopes`. There is no user-type flag.
- Forgejo does have a bot type in its model: `UserTypeBot // 4` and `IsBot()` [src `models/user/user.go` L63–74, L472]. But neither `CreateUserOption`/`EditUserOption` [swagger] nor the CLI can set it. **Gap:** the Bot account will be an ordinary individual user. You can make it bot-like with `PATCH /admin/users/{u}`: `prohibit_login: true` blocks web/password login (check separately that tokens and SSH keep working for a prohibit-login user), plus `max_repo_creation`, `allow_create_organization`, and `restricted: true`. With `restricted`, the user sees only repos/orgs it is explicitly granted, which suits a Bot account.
- CLI subcommands under `forgejo admin user`: create, list, change-password, delete, generate-access-token, must-change-password, reset-mfa, plus an authorized-integration command [src `cmd/admin_user.go`]. There is no CLI for keys, collaborators or repos.

### Access tokens and scopes

Scopes in 16.0.5 [src `models/auth/access_token_scope.go` L55–85]:

- `all`
- `public-only` (modifier: limits the token to public orgs/repos)
- `read:`/`write:` for each of `activitypub`, `admin`, `misc` (placeholder), `notification`, `organization`, `package`, `issue`, `repository`, `user`

`write` implies `read`.

- API routes:
  - `/users/{username}/tokens` POST requires `reqBasicOrRevProxyAuth(), reqToken()` under `reqSelfOrAdmin()` [src `api.go` L593–597]. A token alone cannot mint a token here; it needs username+password basic auth.
  - `/admin/users/{username}/tokens` GET/POST/DELETE sit in the admin group and accept token auth [src `api.go` L1342–1346]. **This is the non-interactive path**: an admin token can mint tokens for the Bot account without knowing the Bot's password.
- Both routes share `utils.CreateAccessToken` [src `routers/api/v1/utils/access_token.go`]:
  - rejects a duplicate name (400) and an empty scope (400).
  - with `repositories` set: resolves each `{owner,name}`. Any repo the **doer** cannot see yields "does not exist" (400). It sets `ResourceAllRepos=false`, validates, and stores `AccessTokenResourceRepo` rows in the same transaction.
  - without `repositories`, it sets `ResourceAllRepos=true`.
- Validation [src `services/authz/access_token.go` L38–84]: a repo-specific token needs ≥1 repo, cannot include `public-only`, and may only include `read:issue`, `write:issue`, `read:repository` or `write:repository`. Anything else fails with `ErrSpecifiedReposInvalidScope`. The code comment explains why: `write:organization` etc. would escape per-repo checks.
- Enforcement [src `services/authz/specific_repos_reducer.go`]:
  - listed repo: access unchanged, i.e. capped by what the user already has.
  - unlisted private repo, or repo of a non-public owner: `AccessModeNone`.
  - unlisted public repo: capped at read.
  - `AllowAdminOverride()` returns false, so admin rights do not bypass it.

  Consequence: a per-repo token for the Bot account still only reaches what the Bot itself can reach. You grant the Bot collaborator access and scope the token to the same repo(s).
- CLI: `generate-access-token` and `create --access-token` hard-code `t.ResourceAllRepos = true` with the comment "maintain legacy behaviour until new CLI options are added" [src `cmd/admin_user_generate_access_token.go` L89–91, `cmd/admin_user_create.go` L213–215]. **Gap:** the CLI cannot make per-repo tokens.
- The live instance matches the schema: `GET /users/dreamer/tokens` returns `scopes: ["all"]`, `repositories: null` for the existing tokens, and [swagger `AccessToken.repositories`] documents null as "not limited".
- Bootstrap chicken-and-egg: the first admin token has to come from the CLI (`forgejo admin user generate-access-token -u <owner> --scopes write:admin,...`) or from the UI. After that, everything else can go over the API.

### SSH keys

- `POST /admin/users/{username}/keys` → `admin.CreatePublicKey` [src `api.go` L1331–1334, `routers/api/v1/admin/user.go` L329]. Body `CreateKeyOption{title, key, read_only}` [swagger]. Admin group guards apply.
- Alternatively the Bot's own token with `write:user` can call `POST /user/keys`.
- Per-repo alternative: deploy keys, `POST /repos/{o}/{r}/keys` with `read_only`. These give SSH access to one repo only, but they belong to the repo, not a user, so pushes are not attributed to the Bot account.
- If the Instance uses OpenSSH with an `authorized_keys` file, Forgejo rewrites it itself when keys are added. `forgejo admin regenerate keys` exists for resync [src `cmd/admin.go` L45–50].

### Collaborators

- `PUT /repos/{owner}/{repo}/collaborators/{collaborator}` with `reqToken()` + `reqAdmin()` (repo admin, which site admins satisfy) [src `api.go` L816–824]. Body `AddCollaboratorOption{permission: read|write|admin}` [swagger]. Returns 204.
- `GET .../collaborators/{u}/permission` is useful for idempotent checks.

### Repositories on behalf of a user/org

- `POST /admin/users/{username}/repos` → `repo.CreateUserRepo(ctx, ctx.User(), form)`, owned by the path user [src `routers/api/v1/admin/repo.go`].
- `POST /orgs/{org}/repos` (and the legacy alias `POST /org/{org}/repos`) for org-owned repos [swagger].
- `POST /admin/users/{username}/orgs` creates an org owned by a user [swagger].

### Instance SSH host key

- No REST endpoint exposes it. The swagger lists only `/signing-key.gpg`, `/signing-key.ssh` and the per-repo `signing-key.gpg`; those are for commit signing.
- The source of truth depends on which SSH server the Instance runs:
  - **Built-in Go SSH server** (`START_SSH_SERVER=true`): keys come from `[server] SSH_SERVER_HOST_KEYS`. The default is `ssh/gitea.rsa, ssh/gogs.rsa`, resolved relative to `APP_DATA_PATH` [src `modules/setting/ssh.go` L65, L132–136].
  - **OpenSSH** (the default in the official rootful Docker image, which runs sshd under s6): standard `ssh_host_*_key.pub` files. In the Docker image these are generated under `/data/ssh/`. This comes from the image's s6 openssh setup and was not verified against this Instance's container.
- Live probe: the repo's `ssh_url` is `ssh://git@localhost:2222/...`, and `ssh-keyscan -p 2222 localhost` returns ed25519, rsa and ecdsa-sha2-nistp256 host keys. The built-in server's default is a single RSA key (`gitea.rsa`), so three standard types points to OpenSSH in the container on port 2222.
- Non-interactive options on the host, in order of trust:
  1. read the `.pub` file(s) from the data volume.
  2. `ssh-keyscan -p <SSH_PORT> localhost` run **on the host itself**. Fetched over loopback, this is not a network TOFU risk.

  Then publish the result to Claude clients for host key pinning. Tell clients the Instance's `SSH_DOMAIN`/`SSH_PORT`; the repo's `ssh_url` in `GET /repos/{o}/{r}` shows what clients will dial.
- **Gap:** a remote Claude client cannot fetch the host key authenticated from the forge. The installer on the host has to carry it across, or the owner can publish it somewhere the client already trusts, e.g. as a file in a repo fetched over HTTPS with a token.

## Gaps summary

1. There is no Bot user type via CLI/API. Use a regular user, harden it with `PATCH /admin/users/{u}` (`restricted`, `max_repo_creation`, `allow_create_organization`, possibly `prohibit_login`), and put "Bot" in the full name.
2. The CLI cannot create repo-specific tokens. Use `POST /admin/users/{bot}/tokens` with `repositories`.
3. Repo-specific tokens are limited to `repository` + `issue` scopes and still allow read of public repos.
4. `POST /users/{u}/tokens` needs basic auth. The admin variant does not.
5. There is no CLI for keys, collaborators or repos. That is API only, needing a site-admin token, which itself comes from the CLI once.
6. There is no API for the SSH host key. Read it from disk or `ssh-keyscan` on the host.
