# igit

Zero-touch integration between a self-hosted Forgejo instance and Claude clients: Claude can work against the forge without a human hand-carrying keys, tokens, or remotes.

## Language

**Instance**:
One self-hosted Forgejo server, operated by the owner for their own use.
_Avoid_: server, forge (when the specific deployment is meant)

**Owner**:
The human who operates the Instance and on whose behalf Claude works.
_Avoid_: admin, user (ambiguous with Forgejo accounts)

**Claude client**:
A machine or environment where Claude (e.g. Claude Code) runs and talks to the Instance over git and the API.
_Avoid_: agent host, workstation

**Bot account**:
The dedicated Forgejo user through which every Claude client acts; distinct from the Owner's own account so Claude's access can be audited and revoked on its own.
_Avoid_: service account, claude user

**Client key**:
The SSH key pair belonging to a Claude client, whose public half is registered on the Bot account.

**Host key pinning**:
Recording the Instance's SSH host key on a Claude client ahead of first connection, so the client never trusts an unverified host.
_Avoid_: TOFU, known_hosts setup

**Zero-touch**:
Requiring no manual action from the Owner beyond starting the installation.

## Relationships

- An **Instance** has exactly one **Bot account**
- A **Bot account** has one **Client key** per **Claude client**
- A **Claude client** pins the host key of each **Instance** it talks to

## Flagged ambiguities

- "API key" in the original idea: means a Forgejo access token owned by the **Bot account**; whether it can be scoped to one repository is unresolved.
