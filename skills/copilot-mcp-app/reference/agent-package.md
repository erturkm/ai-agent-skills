# Agent app package & publishing

Three JSON files plus two icons, zipped, uploaded to the tenant app catalog via Microsoft Graph.

```
agent/appPackage/
├── manifest.json           Teams/M365 app manifest — the wrapper
├── declarativeAgent.json   the agent: instructions, capabilities, starters
├── ai-plugin.json          the actions: points at your MCP server
├── color.png               192×192
└── outline.png             32×32, transparent, single colour
```

Keep these as **templates with `{{PLACEHOLDER}}` tokens** and render them into `agent/.build/`
at publish time. The committed package then carries nobody's tenant ids or URLs, and the same
repo works for any colleague who clones it.

---

## manifest.json

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/teams/v1.23/MicrosoftTeams.schema.json",
  "manifestVersion": "1.23",
  "version": "1.0.0",
  "id": "{{MANIFEST_ID}}",
  "developer": {
    "name": "Your Org",
    "websiteUrl": "{{ORG_URL}}",
    "privacyUrl": "{{ORG_URL}}",
    "termsOfUseUrl": "{{ORG_URL}}"
  },
  "icons": { "color": "color.png", "outline": "outline.png" },
  "name": {
    "short": "Account Planning",
    "full": "Account Planning Agent for Corporate Banking"
  },
  "description": {
    "short": "Run corporate-banking account planning inside Microsoft 365 Copilot.",
    "full": "Longer description — this is what users read in the agent store."
  },
  "accentColor": "#0F6CBD",
  "copilotAgents": {
    "declarativeAgents": [{ "id": "accountPlanningAgent", "file": "declarativeAgent.json" }]
  },
  "permissions": ["identity", "messageTeamMembers"],
  "validDomains": []
}
```

**Hard limits:** `name.short` ≤ **30 chars**, `description.short` ≤ 80. Both fail at publish.

**`id` must be a stable GUID per installation.** Generate once, store in `.env`. Two agents
sharing a manifest id means installing the second **replaces** the first.

**Bump `version` on every publish.** Graph returns `409 version exists` otherwise — and that
reads like "nothing to do" while your changes sit unshipped.

---

## ai-plugin.json — wiring the MCP server

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/copilot/plugin/v2.4/schema.json",
  "schema_version": "v2.4",
  "name_for_human": "Account Planning",
  "description_for_human": "Read and write corporate-banking account plans in Dynamics 365.",
  "description_for_model": "Tools for the account planning journey: search accounts, create and open plans, read the customer snapshot, set strategy, save SWOT, set wallet-share targets, review pricing, review stakeholders, read the pipeline, advance the business process flow, and list or revert demo changes. Most tools return an interactive account planning workspace widget.",
  "namespace": "accountplanning",
  "functions": [],
  "runtimes": [
    {
      "type": "RemoteMCPServer",
      "auth": { "type": "None" },
      "spec": { "url": "{{MCP_URL}}" },
      "run_for_functions": ["*"]
    }
  ]
}
```

- **`functions: []` + `run_for_functions: ["*"]`** — tools are discovered from the MCP server at
  runtime. Do not enumerate them here; the list would go stale on every server change.
- **`namespace`** must be unique per agent. Two agents on one tenant sharing a namespace collide.
- **`description_for_model`** is a second routing signal on top of each tool's own description.
  Summarise the whole toolset and **say that tools return a widget**.
- **`auth: { "type": "None" }`** means the MCP endpoint is public. The server holds the
  Dataverse credentials, so it is a confused-deputy risk — fine for a demo org, not for
  production. For production put Entra auth in front and use an OAuth runtime.

---

## declarativeAgent.json

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/copilot/declarative-agent/v1.8/schema.json",
  "version": "v1.8",
  "name": "Account Planning Agent",
  "description": "One or two sentences — shown in the agent picker.",
  "instructions": "…see below…",
  "conversation_starters": [
    { "title": "Start a fresh account plan", "text": "Let's start a fresh account plan for {{DEMO_ACCOUNT}}." }
  ],
  "capabilities": [
    { "name": "WebSearch" }, { "name": "OneDriveAndSharePoint" }, { "name": "Email" },
    { "name": "TeamsMessages" }, { "name": "People" }, { "name": "Meetings" },
    { "name": "GraphicArt" }, { "name": "CodeInterpreter" }
  ],
  "actions": [{ "id": "accountPlanning", "file": "ai-plugin.json" }]
}
```

**Capabilities (schema 1.8):** `WebSearch`, `OneDriveAndSharePoint`, `GraphConnectors`,
`GraphicArt`, `CodeInterpreter`, `Dataverse`, `TeamsMessages`, `Email`, `People`, `Meetings`,
`ScenarioModels`, `EmailActions`, `MeetingActions`.

**There is no voice capability.** Voice is a host feature, not an agent property. Dictation
works with any agent; full Copilot Voice is not extensible to custom declarative agents, and it
is the wrong fit anyway because spoken output cannot render your widget.

**The built-in `Dataverse` capability is not what you want here.** It gives the model read-only
natural-language search over tables. You are using MCP tools precisely because you need writes,
business logic, BPF transitions and a custom widget. The two can coexist but usually just
confuse routing — leave it off unless you have a reason.

Max **12** conversation starters. Write them as the sentences a real user would type.

---

## Writing instructions that actually drive the tools

**Hard cap: 8,000 characters.** Exceeding it fails at publish. Check locally:

```python
INSTRUCTION_LIMIT = 8000
n = len(da["instructions"])
if n > INSTRUCTION_LIMIT:
    sys.exit(f"instructions are {n} chars, limit {INSTRUCTION_LIMIT} — trim a section")
```

Structure that works, in priority order:

1. **Identity** — one sentence: who the agent is, what system it talks to.
2. **The journey** — numbered steps, each naming its exact tool. This is what makes the agent
   follow a process instead of improvising.
3. **The opening move** — what to do on the most common first request, as an ordered tool list.
4. **Keeping the widget live** — explicit rules (below).
5. **Data-honesty rules** — domain pitfalls the model would otherwise get wrong.
6. **Safety rules** — what must never be modified.
7. **Style** — domain vocabulary, how to round, what to flag.

Phrasings that earned their place:

> Never invent numbers — always call a tool and let the widget show the data.

> Don't dump all eight steps at once. Complete a step, summarise what changed in one or two
> sentences, then offer the next step. **The widget carries the detail — your prose should add
> judgement, not repeat the table.**

> Hold the `accountId` and `planId` and pass both on every call that accepts them.
> After every write the tool already returns a refreshed snapshot. **Let it render** — do not
> suppress it or replace it with a prose recap of the same numbers.
> If a step ends without a refreshed workspace, call `get_account_snapshot` before handing back.

Domain-honesty rules matter more than they look. Real examples that changed what the agent said:

> Lead with the trailing twelve months, not the last filed year. For most of the year the newest
> audited annual is out of date and can hide several quarters of decline.

> Never blend reported figures with consensus. Filings are in the reporting currency; IBES
> normalises to USD. A growth rate across the two is meaningless. Always state the currency.

> CDS spreads and analyst target prices are not available on this feed. If asked, say they are
> unavailable rather than estimating or substituting a peer.

**Escaping:** instructions are a single JSON string. Use `\n` escapes. A literal newline makes
the file invalid; a literal `\n` that survives into the rendered package shows up as the
characters `\n` in the agent's behaviour. Test for both.

---

## Rendering and publishing (`scripts/publish.py`)

### Render

```python
def render(cfg, var):
    mcp_url = cfg.get("AP_MCP_URL", "")
    if not mcp_url:
        sys.exit("ERROR: AP_MCP_URL is empty. Run ./scripts/deploy.sh first.")
    subs = {
        "MCP_URL": mcp_url,
        "MANIFEST_ID": manifest_id,
        "ORG_URL": cfg.get("DV_URL"),
        "DEMO_ACCOUNT": cfg.get("AP_DEMO_ACCOUNT", "Contoso"),
    }
    # … copy pkg → build, substituting in .json files …
    leftover = [k for k in subs if "{{" + k + "}}" in text]
    if leftover:
        sys.exit(f"ERROR: unresolved placeholders in {src.name}: {leftover}")
```

**Re-zip on every run.** Skipping it when "nothing changed" means you bump `version`, publish
"succeeds", and Graph reports `409 version exists` for the version still inside the stale
archive — which reads as a no-op and hides that your edits never shipped.

### Auth — delegated device code, not app-only

**App-only Graph is refused for `/appCatalogs/teamsApps`** even with `AppCatalog.ReadWrite.All`
granted. You must use a delegated flow.

- App registration needs `isFallbackPublicClient = true` (Allow public client flows)
- **Delegated** `AppCatalog.ReadWrite.All` with admin consent
- The signed-in user must be **Teams service admin or global admin**

```python
SCOPE = "https://graph.microsoft.com/AppCatalog.ReadWrite.All offline_access"
dc = post_form(f"{base}/devicecode", {"client_id": client, "scope": SCOPE})
print(dc["message"])          # user opens the URL and enters the code
# poll {base}/token with grant_type=urn:ietf:params:oauth:grant-type:device_code
```

Cache the refresh token in `.secrets/` (chmod 600) so repeat publishes are non-interactive.

### Upload

```
POST   /v1.0/appCatalogs/teamsApps                        ← first publish
POST   /v1.0/appCatalogs/teamsApps/{appId}/appDefinitions ← update
Content-Type: application/zip, body = raw zip bytes
```

### Supporting multiple agents on one server

Make the per-agent values a class so a second agent cannot overwrite the first:

```python
class Variant:
    def __init__(self, name=""):
        self.name = name.lower().lstrip("-")
        suffix     = f"-{self.name}" if self.name else ""
        key_suffix = f"_{self.name.upper()}" if self.name else ""
        self.pkg   = ROOT / "agent" / f"appPackage{suffix}"
        self.build = ROOT / "agent" / f".build{suffix}"
        self.zip   = ROOT / "agent" / f"Agent{suffix}.zip"
        self.app_id_key      = f"TEAMS_APP_ID{key_suffix}"
        self.manifest_id_key = f"TEAMS_MANIFEST_ID{key_suffix}"
```

`python3 scripts/publish.py --variant v3 --new`. Separate ids are the whole point: publishing
the second agent must be *structurally incapable* of touching the first one's definition.

If the two agents share most of their instructions, **generate** the second from the first with
a script of explicit substitutions rather than forking the files — forked copies drift. Make
each substitution fail loudly if it doesn't match exactly once:

```python
def replace_once(text, old, new, what):
    if text.count(old) != 1:
        sys.exit(f"ERROR: {what}: expected exactly 1 match, found {text.count(old)}")
    return text.replace(old, new)
```

---

## Publish errors you will hit

| Symptom | Reality |
|---|---|
| `400 "Value cannot be null (Parameter 'entity')"` | **The write usually landed.** Re-post: a `409 version exists` proves it. Graph commits then fails to serialise the response. |
| `409` conflict on `--new` | The app exists. The conflict message contains the real id as `entitlementId: <guid>` — extract it and retry as an update. |
| `201` but the returned `id` 404s on GET | The `201`'s `id` is an **entitlement id**, not the catalog app id. |
| App invisible in every catalog listing for 20+ minutes | **Graph's write store runs far ahead of its read APIs.** The app can be live in Copilot while every read API denies it exists. Trust a 409 over a 404. |
| `$top` → `400` | `$top` is **not allowed** on `/appCatalogs/teamsApps`. |
| `$filter=id eq '…'` returns empty | Silently fails for a just-created app. `externalId eq` and `startswith(displayName,…)` work, subject to the same lag. |
| `InvalidURL` from Python | Spaces in `$filter` — always `urlencode`. |
| Agent published but never calls a tool | `description_for_model` or tool descriptions too vague, **or** MCP URL unreachable. Curl `/health` first. |
| Agent answers in prose, no widget | `_meta` missing from the tool **descriptor**, or the `ui://` resource not registered. |
| New name not showing in Copilot | Catalog display name caches aggressively — often an hour. Verify via Graph, then wait. |

**The general rule: after an error from a mutating call, read back the actual state before
concluding failure.** Build that recovery into `publish.py` rather than handling it by hand each
time.

---

## Validating the package in CI

Validate **`agent/.build/`** — what actually ships — not the templates:

```python
# fetch the live schemas and validate each rendered file
# assert: no "{{" left, no literal "\\n" in instructions,
#         len(instructions) <= 8000, name.short <= 30,
#         len(conversation_starters) <= 12,
#         capability names ∈ the 1.8 allow-list
```

With more than one agent, assert separation **in both directions** — that agent B is free of
agent A's identifiers *and* that agent A still contains its own. Drift either way fails the build.
