# Which existing integrations let Claude Code drive a Forgejo Instance?

Research for issue #4. Surveyed 2026-09-30 against primary sources (project READMEs, source files, generated CLI docs, wikis and release APIs). Local target: Forgejo `16.0.5+gitea-1.22.0` (from `GET /api/v1/version`). The `/issues/{n}/dependencies` endpoint works on it (returns `[]` for #4).

## TL;DR

| Integration | Kind | Token input | Multiple Instances | Create repo | Issues / comments | PRs | Issue dependencies | Latest release |
|---|---|---|---|---|---|---|---|---|
| **forgejo-mcp** (goern / agentic-forges) | MCP server, Forgejo-native | `FORGEJO_ACCESS_TOKEN` env or `--token`. In HTTP mode, a per-request `Authorization` header | **No**, one `--url` per process. Run one server entry per Instance | Yes (`create_repo`, `owner` = user or org), plus `create_org` | Full | Create, update, merge, review, diff | **Yes**: `list_issue_dependencies`, `list_issue_dependents`, `add_issue_dependency`, `remove_issue_dependency` (cross-repo allowed) | v3.2.0, 2026-09-16 (per project page; release host is behind a bot wall) |
| **gitea-mcp** (official Gitea) | MCP server, Gitea API | `GITEA_ACCESS_TOKEN` env or `-T`. In HTTP mode, `Authorization: Bearer/token` | **No**, one `GITEA_HOST` / `-H` per process | Yes (`create_repo`, optional `organization`) | Full (`issue_write`) | Create, merge, reviewers, reviews | Yes, via `issue_read` / `issue_write` methods | v1.7.0, 2026-08-27 |
| **tea** (official Gitea CLI) | CLI | `tea login add --url … --token …` (or OAuth, SSH key, password), stored in `$XDG_CONFIG_HOME/tea` | **Yes**: named logins, `--login <name>`, or auto-detected from the git remote | Yes (`tea repos create`, `create-from-template`, `migrate`) | Create, edit, close, comment | Create, review, approve, merge, checkout | No subcommand. Use `tea api` | v0.16.0, 2026-09-10 |
| **fj / forgejo-cli** (forgejo-contrib) | CLI, Forgejo-native | `fj auth add-key` (interactive paste) or `fj auth login` (OAuth, allow-listed Instances only) | **Yes**: per host, chosen with `-H/--host` or from the git remote | Yes (`fj repo create`, with `--push` / `--remote`) | Create, edit, labels, comment, close | Create (including AGit), merge | Not documented | v0.6.0, 2026-07-19 |
| Raw REST (`curl`, or this repo's `fj` helper script) | HTTP | `Authorization: token …` | Trivially yes | Yes | Yes | Yes | Yes | n/a |

**Answer:** Two MCP servers are maintained and cover everything this project needs: creating repos, working issues and PRs, and issue dependencies. Neither can talk to more than one Instance per server process, so you register one MCP server per Instance. For multiple Instances the CLIs (`tea`, `fj`) are better, because each keeps named per-host logins. `tea` also has an authenticated `tea api` escape hatch for anything it has no subcommand for, such as dependencies.

## 1. forgejo-mcp (Christoph Görn / "agentic-forges")

- **Where:** development moved in 2026 to `https://git.b4mad.industries/agentic-forges/forgejo-mcp`. `codeberg.org/goern/forgejo-mcp` is now a read-only mirror, and the GitHub copy is labelled "MIRROR ONLY". Source: the mirror's README banner ("📦 This project has moved…").
- **Maintenance:** active. The project page reports v3.2.0 on 2026-09-16, with 32 releases and ~1.5k commits. The Codeberg releases API stops at v2.30.2 (2026-07-13), which is when the move happened. It ships signed OCI images (cosign plus SBOM) and has a Go module path `git.b4mad.industries/agentic-forges/forgejo-mcp/v3`. The new host sits behind Anubis, so its release API couldn't be queried directly.
- **Auth:** `--url` / `FORGEJO_URL` and `--token` / `FORGEJO_ACCESS_TOKEN` (README config table).
  - In `http`/`sse` transports every request must carry its own `Authorization: token <t>` or `Bearer <t>` header. This is the "multi-tenant" mode. The server's own token is used only with `--allow-operator-token-fallback`.
  - There is an optional OAuth resource-server mode (`--auth-mode resource-server`).
  - `FORGEJO_USER_AGENT` exists for proxies that block Go's default user agent.
- **Multiple Instances:** no. "Multi-tenant" means many *users* on one Instance, since `--url` is fixed per process. For N Instances you configure N MCP servers (for example `forgejo-home`, `forgejo-work`). The `forgejo://` resource URIs are described as "instance-portable", but that describes their form, not multi-Instance routing.
- **Coverage (README tool table):**
  - **Repos:** `create_repo` (source: `operation/repo/repo.go` takes `owner` "Owner/org name"), `fork_repo`, `edit_repo`, `get_repo`, `search_repos`, `list_my_repos`, topics, branch protection, webhooks.
  - **Files:** create, update, delete, tree.
  - **Orgs:** `create_org`, `edit_org`, `delete_org`, membership.
  - **Issues:** `create_issue`, `update_issue`, `issue_state_change`, `add_issue_labels`/`remove_issue_labels`, `search_issues`, and repo/org label CRUD.
  - **Comments:** full CRUD, plus attachments.
  - **Dependencies:** `list_issue_dependencies`, `list_issue_dependents`, `add_issue_dependency`, `remove_issue_dependency`. The cross-repo form uses `depends_on_owner`/`depends_on_repo`.
  - **PRs:** `create_pull_request`, `update_pull_request`, `get_pull_request_diff`, `list_pull_request_files`, `merge_pull_request` (merge/rebase/squash, delete-branch), `create_pull_review` (APPROVED/REQUEST_CHANGES/COMMENT with inline comments).
  - **Other:** releases, wiki, Actions runs and logs (Forgejo v16+), packages, notifications.
  - **CLI mode:** the binary can also call tools without MCP, with JSON on stdout.
- **Gaps:** none found for "create repos + work issues/PRs + dependencies". The only gap is the one-Instance-per-process limit.

## 2. gitea-mcp (official, gitea.com/gitea/gitea-mcp)

- **Maintenance:** active, maintained by the Gitea org. v1.7.0 released 2026-08-27 and v1.6.0 on 2026-07-30 (gitea.com releases API).
- **Auth:** `GITEA_ACCESS_TOKEN` / `-T` and `GITEA_HOST` / `-H`, where flags win over env. In HTTP mode it accepts `Authorization: Bearer|token`.
  - The README gives a Claude Code one-liner: `claude mcp add --transport stdio --scope user gitea --env GITEA_ACCESS_TOKEN=… --env GITEA_HOST=… -- go run gitea.com/gitea/gitea-mcp@latest -t stdio`.
  - Read-only mode is `-r` / `GITEA_READONLY`. Tool filtering is `-S` / `GITEA_SCOPES` and `-O` / `GITEA_TOOLS`.
- **Multiple Instances:** no, there is one host per process.
- **Coverage (README table):**
  - `create_repo`: source `operation/repo/repo.go` has an optional `organization` param that calls `CreateOrgRepo`.
  - `fork_repo`.
  - `issue_read` / `issue_write`: "create, update, manage comments, labels and dependencies".
  - `pull_request_write`: create, update, close, reopen, merge, update branch, reviewers.
  - `pull_request_review_write`.
  - Also labels, milestones, projects, wiki, Actions, releases, files, branches and tags.
  - Tools are consolidated and action-based (a `method` parameter).
- **Forgejo compatibility:** not mentioned in the README. It targets the Gitea API, and Forgejo 16 advertises Gitea 1.22 API compatibility. Newer Gitea-only endpoints (for example Gitea projects, if called) may 404 on Forgejo. This is an inference and was not tested here.
- **Gaps:** none for the core needs, apart from single-Instance and unverified Forgejo drift.

## 3. tea (official Gitea CLI, gitea.com/gitea/tea)

- **Maintenance:** active. v0.16.0 released 2026-09-10 and v0.15.1 on 2026-08-02 (gitea.com releases API).
- **Auth:** `tea login add` with `--url/-u`, `--token/-t`, `--name/-n`, `--insecure`, `--oauth`, `--ssh-agent-key`, `--password` (which mints a token), `--scopes`, and `--no-version-check`. Logins are stored in `$XDG_CONFIG_HOME/tea` (`docs/CLI.md`, README). `--git-credentials` registers tea as a git credential helper. No env-var-only token mode is documented.
- **Multiple Instances:** yes. It keeps named logins, and every command takes `--login/-l` or `--remote/-R` to discover the login from the git remote.
- **Coverage (`docs/CLI.md`):**
  - `repos create|create-from-template|fork|migrate|delete|edit` (with `--owner` for orgs in list).
  - `issues create|edit|close|reopen`.
  - `comments add|list|edit|delete`.
  - `pulls create|review|approve|reject|merge|checkout|review-comments|resolve`.
  - Also labels, milestones, releases, orgs, actions, webhooks, wiki, and admin.
  - `--output json` on many commands.
  - **`tea api`** makes authenticated arbitrary requests (`-X`, `-f/-F`, `-d`, `--login`), much like `gh api`.
- **Gaps:** no issue-dependency subcommand. `tea api -X POST /repos/{o}/{r}/issues/{n}/dependencies` covers it. The Gitea version check can be skipped with `--no-version-check` if Forgejo's version string trips it.

## 4. fj / forgejo-cli (codeberg.org/forgejo-contrib/forgejo-cli)

- **Maintenance:** active but slower. v0.6.0 released 2026-07-19 and v0.5.0 on 2026-04-16 (Codeberg releases API). It is Forgejo-native and written in Rust. Don't confuse it with this repo's `fj` API helper script.
- **Auth (wiki "Authentication"):**
  - `fj auth add-key` means you paste an application token interactively.
  - `fj auth login` uses OAuth, but only for allow-listed Instances (Codeberg, code.forgejo.org and others). You can extend the list via `~/.config/forgejo-cli/client_ids`.
  - A localhost Instance needs `add-key`. There is no documented env-var token, which makes non-interactive setup awkward.
- **Multiple Instances:** yes. Keys are per host, chosen by `-H/--host` or inferred from the git remote.
- **Coverage (README and wiki):**
  - `fj repo create` (`--private`, `--push`, `--remote`), fork, migrate, delete, edit.
  - Issues: create, edit title/body/labels, comment, close `--with-msg`.
  - PRs: create (including AGit PRs with no fork) and merge.
  - Also orgs, teams, releases, and actions.
- **Gaps:** no documented issue dependencies and no documented generic `api` passthrough. Interactive editor defaults also need flags such as `--body` to stay non-interactive.

## 5. Other / long tail

- A search turns up several single-author Forgejo MCP servers: `raohwork/forgejo-mcp`, `Sqcows`/SquareCows `forgejo-mcp` ("103 tools"), `teran/mcp-forgejo`, `kepatrick/forgejo-mcp` (governance dashboard), `minhcuongvu`, `nsvk13`, and an npm `@ric_/forgejo-mcp`. None was evaluated in depth. They are listed so they aren't rediscovered, and they are not recommended over the two maintained servers above.
- **Forgejo itself** ships no built-in MCP endpoint. Nothing was found in release coverage through v16.0.x.
- **Raw REST** covers everything, including dependencies (verified on the local Instance), with an `Authorization: token` header. It is what this repo's `fj` helper script already does.

## Implications for igit

1. The best MCP option is **forgejo-mcp**, because it is Forgejo-native, has explicit dependency tools and supports org repo creation. It is registered once per Instance with `--url` plus `FORGEJO_ACCESS_TOKEN`. `gitea-mcp` is a close second, with official backing and a Claude Code one-liner.
2. Neither MCP server handles several Instances in one process. A multi-Instance design needs either one MCP server entry per Instance or a CLI with named logins (`tea --login`).
3. `tea` plus `tea api` is the most complete non-MCP route, and it is multi-Instance by design.
4. Installing any of these is a user-level change and was deliberately not done in this research.

## Sources

- forgejo-mcp README (Codeberg mirror): https://codeberg.org/goern/forgejo-mcp/raw/branch/main/README.md. Also `operation/repo/repo.go` in the same repo. New home: https://git.b4mad.industries/agentic-forges/forgejo-mcp
- gitea-mcp README: https://gitea.com/gitea/gitea-mcp/raw/branch/main/README.md. Also `operation/repo/repo.go`. Releases: https://gitea.com/api/v1/repos/gitea/gitea-mcp/releases
- tea README and generated CLI docs: https://gitea.com/gitea/tea (`docs/CLI.md`). Releases: https://gitea.com/api/v1/repos/gitea/tea/releases
- forgejo-cli README and wiki (Authentication, Repositories, Issues): https://codeberg.org/forgejo-contrib/forgejo-cli. Releases: https://codeberg.org/api/v1/repos/forgejo-contrib/forgejo-cli/releases
- Local Instance: `GET /api/v1/version`, `GET /api/v1/repos/dreamer/igit/issues/4/dependencies`
