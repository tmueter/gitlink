# How can the Instance react when the Owner creates a repository in the UI?

Ticket: dreamer/igit#3. Target: Forgejo 16.0.5 (`/api/v1/version` → `16.0.5+gitea-1.22.0`).
Sources: Forgejo source on branch `v16.0/forgejo` (links below, abbreviated `src:`), the live instance's `swagger.v1.json`, and read-only API probes. Nothing on the instance was changed.

`src:` = `https://codeberg.org/forgejo/forgejo/src/branch/v16.0/forgejo/`

## Answer

Two mechanisms can add the Bot account to a new repo without patching Forgejo:

1. **A system webhook subscribed to the `repository` event, plus a small receiver** that calls `PUT /repos/{owner}/{repo}/collaborators/{bot}`. This works for repos the Owner creates under their personal account. Delivery is asynchronous and fire-once. It usually takes well under a second, but a failed delivery is **not retried**.
2. **An organisation team with "access to all repositories"** that has the Bot as a member. This needs no receiver and happens inside the create transaction, so there is no latency and nothing to fail. It only covers repos owned by that org, not the Owner's personal repos.

Forgejo Actions and git hooks **cannot** do it (details below).

## What fires when a repo is created in the UI

The UI handler `CreatePost` (`src:routers/web/repo/repo.go` L224–312) calls either `repo_service.CreateRepository` or `repo_service.GenerateRepository` (from a template). Both end in `notify_service.CreateRepository(...)` once the DB transaction has committed (`src:services/repository/repository.go` L43–53, `src:services/repository/template.go` L132). The notifiers that react to that call are listed below.

### Inside the create transaction (synchronous)

`CreateRepositoryByExample` (`src:modules/repository/create.go`):

- **Org teams with `IncludesAllRepositories`**: every such team of the owning org is added to the repo (L128–137). This is the "team" option above.
- **Default webhooks** are copied into the new repo (`webhook.CopyDefaultWebhooksToRepo`, L161; `src:models/webhook/webhook_system.go` L70–85). The copies already exist when the notifier runs, so they also receive this repo's `repository: created` event.
- The only other thing in this step is auto-watch (`AutoWatchNewRepos`). There is no plugin or script hook point.

### Webhook notifier (asynchronous)

`webhookNotifier.CreateRepository` (`src:services/webhook/notifier.go` L109–119) emits event **`repository`** with `action: "created"`. The payload includes `repository` (with full owner), `organization` (the owner user or org, despite the name) and `sender`. `MigrateRepository` does the same (L132–142). `ForkRepository` only emits `repository: created` when the fork's owner is an **org** (L94–107). A fork into a personal account only produces `fork` on the source repo.

`PrepareWebhooks` (`src:services/webhook/webhook.go` L239–279) collects the receivers:

| Hook kind | Scope | Sees creation of… | Where configured |
|---|---|---|---|
| **System webhook** (`repo_id=0, owner_id=0, is_system_webhook=true`) | whole instance | every repo, whether owned by a user or an org | Site admin → Integrations → System webhooks; API `POST /admin/hooks` with `config.is_system_webhook="true"` |
| **Owner webhook**, user-level | one user | repos owned by that user | User settings → Webhooks; API `/user/hooks` |
| **Owner webhook**, org-level | one org | repos owned by that org | Org settings → Webhooks; API `/orgs/{org}/hooks` |
| **Default webhook** (`is_system_webhook=false`, template) | copied into every new repo | the new repo (because of the copy above) | Site admin → Default webhooks; API `POST /admin/hooks` **without** `is_system_webhook` |
| Repo webhook | one repo | cannot exist before the repo does (except as a default-hook copy) | n/a |

For igit's single-Owner Instance, a **user-level webhook on the Owner** or a **system webhook** both work. A system webhook also covers any orgs the Owner creates later, and it is not copied into every repo the way a default webhook is. That copying leaves one hook row per repo, and each copy also fires for that repo's later events.

### Actions notifier: no

`actionsNotifier.CreateRepository` (`src:services/actions/notifier.go` L404–413) does pass a `repository` event into the Actions pipeline, but nothing can run from it:

- `notify()` returns right away if `repo.IsEmpty` (`src:services/actions/notifier_helper.go` L152). A fresh UI repo without auto-init is empty.
- Even for a non-empty repo, `detectMatched` has no case for `HookEventRepository`. It falls through to `default: log.Warn("unsupported event")` and returns `false` (`src:modules/actions/workflows.go` L231–297).
- Workflows are read from the new repo's own default branch. No instance-wide or org-wide workflow could react to a *different* repo being created.

### Git hooks: no

- An auto-init or template repo gets its first commit through an internal `git push` with `GITEA_INTERNAL_PUSH=true` (`src:services/repository/init.go` L75–77, `src:modules/repository/env.go` L45–49). `forgejo hook pre-receive` and `post-receive` return early for internal pushes (`src:cmd/hook.go` L175–177, L312–315). So no push event, push webhook or push-triggered workflow comes from creation.
- Custom server-side git hooks are per-repo, so they cannot exist before the repo does. They are also disabled by default (`[security] DISABLE_GIT_HOOKS = true`, `src:modules/setting/security.go` L290).

### Other signals (polling only)

Creation writes a `create_repo` action to the activity feed, which can be read at `GET /users/{username}/activities/feeds` and `/orgs/{org}/activities/feeds` (present in the live swagger). A poller could use this as a **reconciliation fallback**, but it is not a push trigger.

## The automatic step: adding the Bot as collaborator

API (live swagger): `PUT /repos/{owner}/{repo}/collaborators/{collaborator}` with body `AddCollaboratorOption {"permission": "read"|"write"|"admin"}` → `204`. The collaborator is added directly, with no invitation to accept. The caller must be a repo admin, meaning the Owner or a site admin. The Bot cannot add itself. So the receiver needs a token that belongs to the Owner, or to a separate admin identity, with `write:repository` scope. It must not be the Bot's token.

Receiver sketch: accept `POST` → check `X-Forgejo-Signature` (HMAC-SHA256 of the body with the hook secret) → if `X-Forgejo-Event: repository` and `action == "created"` → `PUT .../collaborators/<bot>`. Repeating the call is safe (it is a PUT), so replays and reconciliation can run as often as needed.

## Required config

- **Webhook**: `type: "forgejo"`, `events: ["repository"]`, `config.url`, `config.content_type: "json"`, `config.secret`, and **`active: true`**. `CreateHookOption.active` defaults to `false` in the swagger, so a hook created without it never fires. For a *system* hook, also set `config.is_system_webhook: "true"`. Without it, `POST /admin/hooks` creates a *default* hook instead (`src:routers/api/v1/utils/hook.go` L165–189).
- **`[webhook] ALLOWED_HOST_LIST`** defaults to `external` (`src:services/webhook/deliver.go` L205–209, `app.example.ini` L1697), which blocks loopback and private addresses. A receiver on the same host or LAN needs `loopback`, `private` or an explicit host added. Otherwise every delivery fails.
- `[webhook] DELIVER_TIMEOUT` defaults to 5 s (`src:modules/setting/webhook.go`). The receiver must respond within that time. It can do the PUT inline, which is fast, or acknowledge first and then do it.
- Webhooks must not be globally disabled (`setting.DisableWebhooks`, `src:services/webhook/webhook.go` L162–165).
- Team option: the repo must be owned by an org. Create the team with `includes_all_repositories: true` and the desired unit permissions, then add the Bot as a member.

## Latency

- **Webhook**: `PrepareWebhook` writes a `hook_task` row and pushes its ID onto the in-process `webhook_sender` queue (`src:services/webhook/webhook.go` L135–141, L199+). A worker then delivers it. In practice this adds sub-second latency after the create request commits, plus the receiver's own API call. It is not synchronous: the Owner's browser may reach the new repo page before the Bot has been added.
- **Team**: zero. Access is granted inside the create transaction.

## Failure modes

| Failure | Effect | Mitigation |
|---|---|---|
| Receiver down, non-2xx, or timeout (> `DELIVER_TIMEOUT`) | Task is marked delivered and failed. **No automatic retry.** `Deliver` marks the task delivered *before* sending (`src:services/webhook/deliver.go`, `MarkTaskDelivered`). | Manual replay from the hook's "Recent deliveries" (`ReplayHookTask`, `src:models/webhook/hooktask.go` L154); periodic reconciliation over `/user/repos` or the activity feed |
| Forgejo stops between enqueue and send | Undelivered tasks are re-queued at startup (`populateWebhookSendingQueue`, `src:services/webhook/deliver.go`) | none needed |
| Host blocked by `ALLOWED_HOST_LIST` | Every delivery fails | Configure the list |
| Hook created with `active` omitted | Never fires | Pass `active: true` |
| `POST /admin/hooks` without `is_system_webhook` | Creates a default hook. It still fires for new repos (through the copy), but leaves a hook copy in every repo. `GET /admin/hooks` lists only system hooks, so the default hook does not show up there (`src:routers/api/v1/admin/hooks.go` L40). | Set the flag; check in the admin UI |
| Receiver token revoked or lacks scope | PUT returns 401/403. Webhook delivery still looks successful if the receiver answers 2xx before calling the API. | Have the receiver return an error status when the PUT fails, so the failure shows in Forgejo's delivery log |
| Personal fork | No `repository` event fires (only `fork` on the source) | Also subscribe to `fork`, or rely on reconciliation |
| Repo created by migration | `repository: created` does fire | none needed |
| Team option, repo created under the personal account | Team does not apply | Create repos under the org, or use the webhook |

## Probed on the live instance (read-only)

- `GET /version` → `16.0.5+gitea-1.22.0`.
- `GET /admin/hooks` → `[]`: no system webhooks exist. Default hooks are not listed by this endpoint, so this does not show whether any exist.
- The swagger exposes `/admin/hooks`, `/orgs/{org}/hooks`, `/user/hooks`, `/repos/{o}/{r}/hooks` and `/repos/{o}/{r}/hooks/git`. There is no endpoint to redeliver a webhook; replay is available only in the UI.
- `app.ini` was not readable from this session, so the current `ALLOWED_HOST_LIST` and `DISABLE_WEBHOOKS` values were not checked.
