---
name: "copilot-mcp-app"
description: "Build a Microsoft 365 Copilot declarative agent backed by a remote MCP server (an 'MCP App') that reads and writes live Dataverse / Dynamics 365 data and renders rich interactive D365-styled React widgets inside Copilot chat. Covers the MCP server with openai/outputTemplate widget binding, the Dataverse S2S client, the React widget and window.openai host bridge, the agent app package (manifest + declarativeAgent + ai-plugin), Azure Container Apps deployment, Graph app-catalog publishing, a revertible write journal for demo safety, and a local screenshot preview harness. Use whenever someone wants to build, extend, debug or demo a Copilot agent with custom UI, mentions declarative agent, MCP app, MCP server, Copilot widget, Copilot extensibility, agent app package, or wants D365 data surfaced natively in M365 Copilot chat."
---


> **Bundled skill file.** This single document contains `SKILL.md` plus all 5 reference file(s), inlined as appendices below. Cross-references have been rewritten to in-page links.
>
> **Appendices:**
> - [Agent Package](#appendix-agent-package)
> - [Demo Safety](#appendix-demo-safety)
> - [Deploy](#appendix-deploy)
> - [Mcp Server](#appendix-mcp-server)
> - [Widget](#appendix-widget)


You are building a **Copilot MCP App**: a declarative agent for Microsoft 365 Copilot whose
actions are served by a remote MCP server, and whose tool results render as an interactive
React widget *inside the Copilot conversation* — not as text, not as an Adaptive Card.

Treat this as an engineering project. Write the code, deploy it, call the live endpoints and
verify what actually renders before declaring anything done. Most failures in this stack are
silent: the agent publishes fine and simply answers in prose while your widget never appears.

Deep reference files live next to this skill. Read them on demand — do not guess when one
covers the topic:

- `~/.copilot/m-skills/copilot-mcp-app/#appendix-mcp-server` — MCP server, tool + resource
  registration, the widget binding contract, Dataverse S2S client, streamable HTTP transport, CORS
- `~/.copilot/m-skills/copilot-mcp-app/#appendix-widget` — React widget, the `window.openai`
  host bridge, single-file bundling, D365 visual shell, local preview + screenshots
- `~/.copilot/m-skills/copilot-mcp-app/#appendix-agent-package` — manifest.json,
  declarativeAgent.json, ai-plugin.json, writing instructions that actually drive tools,
  templating, publishing via Graph, and every publish error you will hit
- `~/.copilot/m-skills/copilot-mcp-app/#appendix-deploy` — bicep, Azure Container Apps,
  ACR build, the deploy script, and the Azure failure modes that are lies
- `~/.copilot/m-skills/copilot-mcp-app/#appendix-demo-safety` — revertible write journal,
  read-only guards on shared demo data, and display-name masking for public stages

---

## 1. What you are actually building

Five pieces. Keep them straight — most confusion comes from conflating the agent with the server.

```
┌──────────────────────── M365 Copilot (m365.cloud.microsoft/chat) ───────────────────────┐
│                                                                                          │
│   Declarative Agent  ── instructions, capabilities, conversation starters                │
│         │              (app package, published to the tenant app catalog via Graph)      │
│         │ actions → ai-plugin.json  { "type": "RemoteMCPServer", "url": ... }            │
│         ▼                                                                                │
│   ┌──────────────── your MCP server (Azure Container Apps, HTTPS) ──────────────┐        │
│   │  tools      →  _meta["openai/outputTemplate"] = "ui://your-app/x.html"      │        │
│   │  resources  →  that URI serves a single-file HTML bundle (mimeType          │        │
│   │                "text/html+skybridge")                                        │       │
│   │  Dataverse client (client-credentials S2S) → live D365 data                 │        │
│   └─────────────────────────────────────────────────────────────────────────────┘       │
│         │                                                                                │
│         ▼  host renders the bundle in a sandboxed iframe, injects window.openai           │
│   ┌──────────── React widget ────────────┐                                               │
│   │ reads window.openai.toolOutput        │  calls tools back via window.openai.callTool  │
│   └───────────────────────────────────────┘                                              │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**The single most important fact:** one deployed MCP server can back *many* agents. The agent
package is per-agent; the server is shared. Publishing agent B cannot affect agent A —
**but redeploying the server affects every agent that points at it.** Say this out loud to
the user before any redeploy if more than one agent is live.

---

## 2. Build order

Do it in this order. Each step is verifiable on its own; skipping ahead means debugging two
layers at once.

| # | Step | Verify before moving on |
|---|------|------------------------|
| 1 | Dataverse app registration + application user | `dv('accounts?$top=1')` returns a row |
| 2 | MCP server with **one** read-only tool, text result only | `tools/list` over HTTP returns it |
| 3 | React widget that renders a hardcoded payload | Open `dist/index.html` in a browser |
| 4 | Bind the tool to the widget (`openai/outputTemplate` + resource) | Widget renders in Copilot |
| 5 | Remaining read tools | Each returns real data |
| 6 | Write tools **+ journal** (never writes before the journal exists) | `revert` restores state |
| 7 | Deploy to Container Apps | `/health` responds, `tools/list` over HTTPS |
| 8 | Agent package + publish | Agent appears in Copilot, calls a tool |
| 9 | Preview harness + screenshots | You have *looked at* every card |

Step 4 is the one that fails. Get it working with a trivial tool before you build ten.

---

## 3. The widget binding contract

This is the part no amount of reasoning will give you. Get these four things exactly right or
Copilot silently falls back to prose.

**a. The `_meta` must be on the tool *descriptor*, not only the result.**

```ts
const WIDGET_URI = 'ui://account-planning/workspace.html';
const WIDGET_MIME = 'text/html+skybridge';

const WIDGET_META = {
  'openai/outputTemplate': WIDGET_URI,
  'openai/visibility': 'public',
} as const;

server.registerTool(
  'get_account_snapshot',
  {
    title: 'Account snapshot',
    description: '...',
    inputSchema: { account: z.string() },
    annotations: { readOnlyHint: true },
    _meta: WIDGET_META,          // ← on the descriptor. Omit this and you get text.
  },
  async ({ account }) => widgetResult(payload, 'One-line summary for the model.'),
);
```

**b. Register the URI as a resource that serves the HTML.**

```ts
server.registerResource(
  'account-planning-workspace',
  WIDGET_URI,
  { title: 'Account Planning Workspace', mimeType: WIDGET_MIME },
  async () => ({
    contents: [{
      uri: WIDGET_URI,
      mimeType: WIDGET_MIME,
      text: loadWidgetHtml(),            // the whole single-file bundle, inline
      _meta: {
        'openai/widgetCSP': {
          connect_domains: [],
          resource_domains: ['https://fonts.googleapis.com', 'https://fonts.gstatic.com'],
        },
      },
    }],
  }),
);
```

**c. The result carries data in `structuredContent`, and repeats the `_meta`.**

```ts
function widgetResult(data: unknown, summary: string) {
  return {
    content: [{ type: 'text' as const, text: summary }],
    structuredContent: {
      renderedAt: new Date().toISOString(),   // see (d)
      ...(data as Record<string, unknown>),
    },
    _meta: { ...WIDGET_META },
  };
}
```

**d. Stamp `renderedAt` on every payload.** The host *reuses a widget instance* across tool
calls. Without a server-side timestamp the widget cannot distinguish a genuinely new payload
from a re-render of the old one, and the UI freezes on whichever snapshot arrived first. The
widget picks the newer of host-pushed state and its own local state by comparing this stamp.

**One URI per card type.** The host keys widget instances by template URI. If a news tool and a
workspace tool share a URI, requesting news **overwrites the open workspace in place** instead
of posting its own card. Use a separate `ui://` URI per distinct card; they can all serve the
same bundle and switch on a `mode` field in the payload.

---

## 4. Rules that save days

**Never let the model invent numbers.** Put this in the agent instructions explicitly: *"always
call a tool and let the widget show the data."* Otherwise Copilot will happily summarise
plausible-looking figures it made up, which is fatal in a customer demo.

**The widget is the UI; the prose is the judgement.** Tool text results should be one or two
sentences of interpretation, never a restatement of the table. Tell the model this in the
instructions too, or it will read the whole card aloud.

**Write tools must return a refreshed snapshot.** After every write, re-read and return the
full payload so the widget reflects the saved state. A write that returns only text leaves the
user staring at stale data.

**Build the widget before building the image.** `server/public/widget.html` is baked into the
container. A stale bundle is invisible — everything deploys cleanly and the old UI ships.

**Rebuild `dist/` before comparing anything.** Both `server/` (`npx tsc`) and `widget/`
(`npm run build`). Comparing against a stale `dist/` has produced "no change" conclusions that
were simply wrong.

**On an error from a mutating call, read back the actual state before concluding failure.**
Both Graph and ARM in this stack commit the change and *then* fail to serialise the response.
See the reference files — this specific trap appears in both `#appendix-deploy` and `#appendix-agent-package`.

**Look at the rendered screenshot, not the DOM snapshot.** Accessibility snapshots miss
cosmetic defects — an empty chip rendering as a stray "—" is invisible in the DOM and obvious
on a projector. The preview harness in `#appendix-widget` exists for this.

**8,000-character hard cap on `instructions`.** Exceeding it is a publish-time failure. Check
it locally in your build script with a useful message.

**Teams manifest `name.short` ≤ 30 characters.**

---

## 5. Project layout

```
your-agent/
├── server/
│   ├── src/
│   │   ├── index.ts          MCP server: tools, resources, express host
│   │   ├── dataverse.ts      S2S client-credentials client + $filter encoding
│   │   ├── <domain>.ts       business logic — keep OUT of index.ts
│   │   └── journal.ts        revertible write journal (see demo-safety.md)
│   ├── public/widget.html    built widget, baked into the image
│   ├── Dockerfile
│   └── package.json
├── widget/
│   ├── src/
│   │   ├── bridge.ts         window.openai bridge — capability-detected
│   │   ├── App.tsx           root; picks newer of host/local snapshot
│   │   ├── shell.tsx         D365 chrome: AppBar, CommandBar, ProcessBar, tabs
│   │   └── <cards>.tsx
│   └── vite.config.ts        vite-plugin-singlefile — MUST inline everything
├── agent/
│   └── appPackage/           manifest.json, declarativeAgent.json, ai-plugin.json, icons
├── infra/main.bicep
├── scripts/
│   ├── bootstrap.py          discover Dataverse ids → .env
│   ├── deploy.sh             ACR build + container app roll
│   ├── publish.py            render package + Graph device-code publish
│   └── preview.mjs           local preview pages from captured fixtures
├── tests/                    test_tools.py, test_guard.py, test_agent_packages.py
└── .env                      NEVER commit — secrets + tenant ids
```

Keep `index.ts` to wiring. Domain logic belongs in its own module; a 1,600-line `index.ts`
is already at the edge of manageable.

---

## 6. Verification — what "done" means

Never declare success from a deploy exit code. Run these against the **live HTTPS endpoint**:

```bash
curl -fsS "$MCP_URL/../health"            # service up
python3 tests/test_tools.py               # tools/list count + one real call per tool
python3 tests/test_guard.py               # write guards + revert actually restore
python3 tests/test_agent_packages.py      # RENDERED package vs live MS schemas
```

`test_agent_packages.py` must validate `agent/.build/` (what ships) and not
`agent/appPackage/` (the template) — otherwise unresolved `{{PLACEHOLDER}}` tokens and
literal `\n` in instructions sail through.

Then, in Copilot itself: run the journey end to end and **look at every card**.

---

## 7. Making it demo-safe

If this touches an org with real or shared demo data — and it always does — read
`#appendix-demo-safety` **before writing the first write tool**. It covers:

- a JSONL write journal that makes every change revertible in one tool call
- a guard that makes pre-existing records read-only while still allowing the journey to run
- `list_demo_changes` / `revert_demo_changes` tools so the presenter can clean up on stage
- display-name masking, if the demo goes on a public stage and the real customer cannot be named

The ordering matters: **the journal must exist before any write tool does.** Retrofitting it
means you cannot revert the writes you already made.


---

<a id="appendix-agent-package"></a>

## Appendix: Agent Package

*Originally `reference/agent-package.md`*

## Agent app package & publishing

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

### manifest.json

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

### ai-plugin.json — wiring the MCP server

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

### declarativeAgent.json

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

### Writing instructions that actually drive the tools

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

### Rendering and publishing (`scripts/publish.py`)

#### Render

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

#### Auth — delegated device code, not app-only

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

#### Upload

```
POST   /v1.0/appCatalogs/teamsApps                        ← first publish
POST   /v1.0/appCatalogs/teamsApps/{appId}/appDefinitions ← update
Content-Type: application/zip, body = raw zip bytes
```

#### Supporting multiple agents on one server

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

### Publish errors you will hit

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

### Validating the package in CI

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


---

<a id="appendix-demo-safety"></a>

## Appendix: Demo Safety

*Originally `reference/demo-safety.md`*

## Demo safety

Demo orgs are shared. Your agent writes to Dataverse. Without the controls below, one rehearsal
quietly corrupts a colleague's demo data and nobody notices until they are on stage.

**Build the journal before the first write tool.** Retrofitting it cannot undo the writes you
have already made.

---

### 1. The write journal

Every write is appended to a JSONL journal with its prior value, so the whole demo is revertible
in one tool call.

```ts
export interface JournalEntry {
  ts: string;
  op: 'create' | 'update';
  entitySet: string;
  rowId: string;
  label?: string;                        // human label, so list_demo_changes reads nicely
  before?: Record<string, unknown>;      // for updates: values as they were BEFORE
  after?: Record<string, unknown>;
  reverted?: boolean;
}
```

Two classes of row, handled differently:

- **Agent-owned** — created by this agent. Reverting **deletes** them.
- **Protected** — pre-existed. Reverting **restores** the journalled `before` values.

Ownership is derived from Dataverse `createdby`, **not** from the journal. That matters: the
guard then survives a journal loss or a container restart.

#### Wrap every write

Two entry points: `recordCreate(entitySet, rowId, label)` after a POST, and `guardedUpdate`
for every PATCH. `guardedUpdate` is the **only** path that may touch a pre-existing row.

```ts
export async function guardedUpdate(
  entitySet: string, rowId: string, fields: Record<string, unknown>, label?: string,
): Promise<void> {
  const keys = Object.keys(fields);
  let before: Record<string, unknown> | undefined;

  if (protectExisting() && keys.length) {
    // Lookups are WRITTEN as `Nav@odata.bind` but must be READ as `_nav_value`.
    const reads = keys.map((k) => {
      const m = /^(.+)@odata\.bind$/.exec(k);
      return m ? { key: k, select: `_${m[1].toLowerCase()}_value`, nav: m[1] }
               : { key: k, select: k };
    });
    try {
      const cur = await dv<any>(
        `${entitySet}(${rowId})?$select=${reads.map((r) => r.select).join(',')}`);
      before = {};
      for (const r of reads) {
        const v = cur?.[r.select] ?? null;
        // Re-express the prior lookup as a bind so revert can write it back.
        before[r.key] = r.nav ? (v ? `/${bindSetFor(r.nav)}(${v})` : null) : v;
      }
    } catch {
      // If we cannot read the prior state we must not silently overwrite it.
      throw new Error(
        `Refusing to update ${entitySet}(${rowId}): could not read its current values to ` +
        `make the change revertible. Set AP_PROTECT_EXISTING=false to override.`);
    }
  }

  await dv(`${entitySet}(${rowId})`, { method: 'PATCH', body: fields });
  append({ ts: new Date().toISOString(), op: 'update', entitySet, rowId, label,
           before, after: fields });
}
```

Three things here are load-bearing:

- **Read the prior value before the write**, selecting exactly the fields you are about to
  change. A revert that restores fields you never touched is its own kind of damage.
- **Lookup asymmetry.** You write `fsi_Customer@odata.bind: "/accounts(guid)"` but you read
  `_fsi_customer_value`. Capture the read form and re-express it as a bind, or revert silently
  fails to restore relationships.
- **Fail closed.** If the prior state can't be read, *refuse the write*. An unrevertible change
  is worse than a failed one.

#### Storage

```ts
const JOURNAL_PATH = process.env.AP_JOURNAL_PATH
  ?? join(process.cwd(), '.demo-journal', 'writes.jsonl');
```

On Container Apps use `/tmp/journal.jsonl`. It is per-revision and lost on restart — acceptable,
because ownership comes from Dataverse. If you need it durable, write to blob storage with the
same service principal (`Storage Blob Data Contributor` on the account).

Parse tolerantly — a truncated final line must not take down the server:

```ts
function parseJsonl(text: string): JournalEntry[] {
  return text.split('\n').filter((l) => l.trim())
    .map((l) => { try { return JSON.parse(l) as JournalEntry; } catch { return null; } })
    .filter(Boolean) as JournalEntry[];
}
```

**Single replica only.** The journal is in-process; a second replica would not see the first
one's pending changes. Pin `minReplicas: maxReplicas: 1`.

---

### 2. The read-only guard

Pre-existing records are reference data. The agent may read them but must write only to records
it created in this conversation.

```ts
export const protectExisting = (): boolean =>
  (process.env.AP_PROTECT_EXISTING ?? 'true').toLowerCase() !== 'false';
```

Protection is **on unless explicitly disabled** — the safe default survives a missing env var.

Ownership is checked against the **S2S application user's `systemuser` id**, obtained from
`WhoAmI` — *not* the app registration's client id. Every row the agent creates is created by
that application user; pre-existing demo data was created by real users.

```ts
let appUserId: string | null = null;

/** The systemuser id of the S2S application user this server authenticates as. */
export async function getAppUserId(): Promise<string> {
  if (appUserId) return appUserId;
  const who = await dv<{ UserId: string }>('WhoAmI');
  appUserId = String(who.UserId).toLowerCase();
  return appUserId;
}

/**
 * Durable ownership check. The in-memory journal is lost when the container
 * restarts, but `createdby` is not. Fails *closed*: if we can't prove we
 * created the row, it is treated as protected.
 */
export async function isAgentCreated(entitySet: string, rowId: string): Promise<boolean> {
  if (isAgentOwned(entitySet, rowId)) return true;        // fast path: the journal
  try {
    const me = await getAppUserId();
    const row = await dv<any>(`${entitySet}(${rowId})?$select=_createdby_value`);
    return String(row?._createdby_value ?? '').toLowerCase() === me;
  } catch {
    return false;                                          // fail closed
  }
}
```

Journal first (cheap), Dataverse second (durable), `false` on any error. That ordering is what
keeps the guard correct across container restarts *and* fast in the common case.

Surface the refusal in the agent instructions so the model handles it gracefully rather than
retrying:

> Pre-existing account plans in this environment are demo reference data and **must never be
> modified**. You may read them, but all writes must go to a plan that you created in this
> conversation. If a write is refused because the plan is protected, explain that and offer to
> create a fresh plan instead. **Never try to work around the guard.**

#### Shared rows are the hard case

Some journeys genuinely must edit *shared, account-level* rows that pre-date the agent (share of
wallet, cross-sell, stakeholders). Blocking those guts the demo. The resolution is not to block
them but to **journal them with their prior values** so they are restorable. Protection applies
to the parent record; shared children are journalled.

---

### 3. The two presenter tools

Give the presenter a way to see and undo everything, from chat.

```ts
server.registerTool('list_demo_changes', {
  title: 'List what this agent has changed',
  description: 'Show every Dataverse record this agent has created or modified, with prior values.',
  annotations: { readOnlyHint: true },
}, async () => { /* read journal, format pending entries */ });

server.registerTool('revert_demo_changes', {
  title: 'Undo everything this agent has written',
  description:
    'Roll Dataverse back to the state it was in before this agent made any changes: restores ' +
    'modified fields to their previous values and deletes records the agent created. Use after ' +
    'a demo to leave the environment clean. Confirm with the user first.',
  inputSchema: { deleteCreated: z.boolean().optional() },
  annotations: { readOnlyHint: false, idempotentHint: true },
}, async ({ deleteCreated }) => {
  const r = await journal.revertAll({ deleteCreated: deleteCreated ?? true });
  // report restored / deleted counts AND any failures explicitly
});

```

**Report partial failure loudly.** A revert that restored 8 of 10 rows and said "done" is worse
than one that failed outright:

```
Reverted: 8 field restore(s), 2 record deletion(s).
⚠️ 1 failed:
- fsi_accountplans: 403 Forbidden
```

Add a conversation starter for it — *"What have you changed in Dataverse so far? Show me, then
revert everything."* — so cleanup is one click at the end of a demo.

---

### 4. Display-name masking for public stages

When a demo uses a real customer's data but the name cannot appear on a conference screen.

**Keep the lookups real; mask only at the point data becomes visible.** Fetching live market
data for the real company is the whole value of the integration. Substitute the display name on
the way out.

```ts
/** Inert unless AP_MASK_CONFIG is set — so the unmasked agent is byte-identical. */
export function maskerFor(accountName: string): Masker | null { … }
```

Three properties that matter:

1. **Keyed on the *Dataverse account display name*, never the real company.** The masked agent
   asks for "Northwind Gas"; the masker maps that to the real company for the upstream call and
   scrubs the real name out of the response.
2. **Inert by default.** No `AP_MASK_CONFIG` ⇒ `maskerFor()` returns `null` ⇒ the original agent
   is unaffected. Assert this in tests.
3. **`scrubList` fails closed.** Free text (news headlines, analyst notes) can name a company
   the substitution map has never seen. Items still matching a blocked term *after* scrubbing
   are **dropped entirely**. Losing a headline is recoverable; showing the real name on stage is not.

Also suppress structural identifiers, not just the name — tickers/RICs, exchange identifiers,
ISINs, permIds. A RIC like `R:CONTOSOENERGY.XX` names the company as surely as the name does.

```ts
if (mask.hideTicker) {
  if (out.entity)  out.entity  = { ...out.entity, ric: undefined, permId: undefined };
  if (out.listing) out.listing = { ...out.listing, ric: undefined, primaryRic: undefined, isin: undefined };
}
```

**Conditionally render, don't blank.** A suppressed field left in the markup renders as a stray
"—" chip. `{entity.ric ? <span…> : null}` — and verify on a *screenshot*, not a DOM snapshot.

#### Leak scan — automate it

Never eyeball this. Scan every tool's full response for every blocked term plus the identifier
fields, and run it before every rehearsal:

```python
BLOCKED = ["RealCo", "RealCo Gas", "REALCO", "R:REALCO.AD", …]
for tool in ("get_overview", "get_financials", "get_news"):
    blob = json.dumps(call(tool, {"company": "Northwind Gas"})).lower()
    hits = [t for t in BLOCKED if t.lower() in blob]
    assert not hits, f"{tool}: LEAKED {hits}"
```

Exit non-zero = do not present. Keep one source of truth for the name map (a single
`names.py`), and generate `AP_MASK_CONFIG` from it — hand-maintaining both halves guarantees
they drift.

#### Seeding the masked account

Copy the real account's rows to the masked account and scrub the copies. **Never modify the
source rows.** Assert it afterwards rather than trusting it:

```python
before = snapshot_of(REAL_ACCOUNT)
seed_masked_account()
assert snapshot_of(REAL_ACCOUNT) == before, "source data was modified"
```

---

### 5. Pre-demo checklist

```bash
curl -fsS "$HEALTH_URL"                   # server up
python3 tests/test_tools.py               # tool count + live data
python3 tests/test_guard.py               # guards hold, revert restores
python3 scripts/leakscan.py               # masking, if used — exit 1 ⇒ do not present
python3 tests/test_agent_packages.py      # rendered packages valid, agents separated
```

Then run the journey in Copilot and **look at every card** in the theme you will present in.


---

<a id="appendix-deploy"></a>

## Appendix: Deploy

*Originally `reference/deploy.md`*

## Deployment

Azure Container Apps, image built by ACR Tasks (no local Docker needed), everything described
in bicep so re-deploys are idempotent.

### Dockerfile

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev --ignore-scripts && cp -R node_modules /prod_modules \
 && npm install --ignore-scripts
COPY tsconfig.json ./
COPY src ./src
RUN npx tsc

FROM node:22-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /prod_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
COPY public ./public
EXPOSE 8080
ENV PORT=8080
CMD ["node", "dist/index.js"]
```

The `cp -R node_modules /prod_modules` trick installs prod deps, stashes them, then installs
dev deps to compile — the runtime stage gets prod-only modules without a second resolve.

`COPY public ./public` bakes the widget bundle in. **Build the widget before the image** or you
ship the previous UI with no error anywhere.

---

### bicep (`infra/main.bicep`)

Key decisions, each of which has a reason:

```bicep
var suffix  = uniqueString(resourceGroup().id)
// A Container App cannot move between environments, so an install that already
// has one running must keep using it. The overrides let deploy.sh adopt the
// existing registry and environment instead of provisioning a second pair
// beside them (which then fails with ContainerAppEnvironmentMismatch).
var acrName = empty(acrNameOverride) ? toLower('acr${baseName}${suffix}') : acrNameOverride
var envName = empty(envNameOverride) ? 'cae-${baseName}' : envNameOverride
```

```bicep
ingress: {
  external: true
  targetPort: 8080
  transport: 'auto'        // 'auto' → HTTP/2 where available; the MCP transport needs it
  allowInsecure: false
}
```

```bicep
scale: {
  // Single replica: the write journal is in-process, so a second replica
  // would not see the first one's pending changes.
  minReplicas: 1
  maxReplicas: 1
}
```

`minReplicas: 1` also avoids cold starts — a scale-from-zero wake-up mid-demo looks like a hang.

**Secrets as `secretRef`, never plain env:**

```bicep
secrets: [
  { name: 'dataverse-client-secret', value: dvClientSecret }
  { name: 'acr-password', value: acr.listCredentials().passwords[0].value }
]
env: [
  { name: 'DV_CLIENT_SECRET', secretRef: 'dataverse-client-secret' }
  { name: 'DV_URL', value: dvUrl }
]
```

**Conditional env blocks** for optional integrations, so an unconfigured feature stays off
rather than half-on:

```bicep
var hasLseg = !empty(apLsegMcpUrl) && !empty(apLsegRefreshToken)
env: concat([ /* always */ ], hasLseg ? [ /* marketdata vars */ ] : [])
```

**Outputs** the deploy script reads:

```bicep
output acrLoginServer string = acr.properties.loginServer
output acrName        string = acr.name
output mcpUrl         string = 'https://${app.properties.configuration.ingress.fqdn}/mcp'
output healthUrl      string = 'https://${app.properties.configuration.ingress.fqdn}/health'
```

---

### deploy.sh

```bash
set -euo pipefail
set -a; source "$ENV_FILE"; set +a     # ← source, never a hand-rolled parser (see below)

require DV_TENANT_ID; require DV_CLIENT_ID; require DV_CLIENT_SECRET
require DV_URL;       require AZ_SUBSCRIPTION

az account set -s "$AZ_SUBSCRIPTION"
az group create -n "$RG" -l "$LOC" -o none

# Read the current image with core `az resource show` rather than
# `az containerapp show`: the containerapp extension is preview-only and has
# shipped API versions ahead of what the service accepts, which fails the whole
# deploy on a read. Pinning the same apiVersion the bicep uses keeps this
# working regardless of which extension build happens to be installed.
APP_RID="/subscriptions/$AZ_SUBSCRIPTION/resourceGroups/$RG/providers/Microsoft.App/containerApps/<app-name>"
CURRENT_IMAGE=""
if az resource show --ids "$APP_RID" --api-version 2024-03-01 -o none 2>/dev/null; then
  CURRENT_IMAGE=$(az resource show --ids "$APP_RID" --api-version 2024-03-01 \
    --query "properties.template.containers[0].image" -o tsv 2>/dev/null || echo "")
fi

# Pass 1 provisions the registry with a placeholder image, because we cannot
# build into a registry that does not exist yet. Pass 2 replaces it.
deploy_infra "${CURRENT_IMAGE:-mcr.microsoft.com/k8se/quickstart:latest}"

ACR=$(out acrName); ACR_SERVER=$(out acrLoginServer)

# Build the widget so the image bakes in the current UI.
(cd "$ROOT/widget" && npm install --silent && npm run build --silent)

# Unique tag per build. Container Apps does not create a new revision when the
# template is byte-identical to the current one, so reusing :latest silently
# deploys nothing.
TAG="$(date -u +%Y%m%d%H%M%S)"

az acr build -r "$ACR" -t "your-app:$TAG" "$ROOT/server" -o none
deploy_infra "$ACR_SERVER/your-app:$TAG"

# Record the URL so publish.py can stamp it into the agent package.
# … write AP_MCP_URL back into .env …

curl -fsS -m 60 "$(out healthUrl)" >/dev/null && echo OK
```

#### The two-pass deploy

You cannot build into a registry that doesn't exist. Pass 1 provisions with a placeholder (or
the currently running image, on re-deploys); pass 2 rolls to the freshly built tag.

#### Unique tags are mandatory

Container Apps compares the template and **creates no revision if it is byte-identical**.
`:latest` therefore deploys nothing, silently, and you debug "my fix didn't work" for an hour.
Timestamp every tag.

#### Set env vars through bicep only

Never `az containerapp update --set-env-vars`. It works, and the next bicep deploy wipes it.
Every variable belongs in `main.bicep` with a parameter fed from `.env`.

---

### `.env` discipline

Written with shell-safe quoting (values contain spaces and JSON):

```bash
AP_MASK_CONFIG="{\"northwind gas\":{\"real\":\"Contoso Energy\"}}"
```

**Always `source` it. Never hand-roll a parser.** A custom parser that doesn't unescape `\"`
inside JSON values yields a literal `{\"northwind gas\"...}`, which parses as nothing and behaves
exactly like a code bug. That misdiagnosis has cost ~20 minutes more than once. If you must
read it in Python, mirror the quoting:

```python
def unquote_env(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
        if value and "\\" in value:
            value = value.replace('\\"', '"').replace("\\\\", "\\")
    return value
```

`chmod 600 .env`, and `.gitignore` it along with `.secrets/`, `agent/.build*/`, `agent/*.zip`.

---

### Azure failure modes that are lies

**`DeploymentFailed` / `internal server error` from ARM — check the state before reacting.**
This has reported failure while `provisioningState` was `Succeeded`, the revision had advanced,
and the new env vars were present. The deploy worked; only the response failed.

```bash
az resource show --ids "$APP_RID" --api-version 2024-03-01 \
  --query "{state:properties.provisioningState, image:properties.template.containers[0].image}"
curl -fsS "$HEALTH_URL"
```

**The `containerapp` CLI extension is preview-only and ships API versions ahead of the
service.** It has sent a retired `2025-10-02-preview`, failing every `az containerapp` call.
`az extension update` made it worse (version became `Unknown`). The fix is to not depend on it —
core `az resource show --api-version 2024-03-01` is stable.

**Transient DNS failures** resolving `login.microsoftonline.com` or `graph.microsoft.com` show
up as `[Errno 8] nodename nor servname provided`. Retry with a short loop before concluding
anything is wrong:

```bash
for i in $(seq 1 10); do
  python3 -c "import socket;socket.getaddrinfo('graph.microsoft.com',443)" 2>/dev/null && break
  sleep 6
done
```

**`ContainerAppEnvironmentMismatch`** means bicep is trying to move an existing app to a new
environment. Adopt the existing one via `envNameOverride`.

---

### Verify after every deploy

Never trust the exit code:

```bash
curl -fsS "$HEALTH_URL"                   # 1. service responds
python3 tests/mcpcall.py                  # 2. tools/list returns the expected COUNT
python3 tests/test_tools.py               # 3. one real call per tool, against live data
python3 tests/test_guard.py               # 4. write guards + revert still work
```

**With more than one agent on the server, diff before and after.** Run the live endpoint and
your local build side by side on identical inputs and confirm the only differences are the ones
you intended. That comparison is what catches a stale `dist/` — and it has.

---

### Cost

Roughly **$35–60/month**: Container Apps 0.5 vCPU / 1 GiB pinned at one replica (~$30–45), ACR
Basic (~$5), Log Analytics (~$3 at low volume). Scaling to zero saves ~$30 but adds a cold
start — keep `minReplicas: 1` for anything you demo.

Tear down: `az group delete -n "$RG" --yes --no-wait`.


---

<a id="appendix-mcp-server"></a>

## Appendix: Mcp Server

*Originally `reference/mcp-server.md`*

## MCP server

Node 22 + TypeScript + `@modelcontextprotocol/sdk` over **streamable HTTP**. This is the only
transport Copilot supports for remote MCP servers — not stdio, not SSE-only.

### Dependencies

```json
{
  "type": "module",
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.30.0",
    "express": "^5.2.1",
    "zod": "^4.6.5"
  },
  "devDependencies": {
    "@types/express": "^5.0.6",
    "@types/node": "^26.6.1",
    "tsx": "^4.23.13",
    "typescript": "^7.0.2"
  },
  "scripts": {
    "build": "tsc",
    "start": "node dist/index.js",
    "dev": "tsx watch src/index.ts"
  }
}
```

`"type": "module"` is required, and every local import must carry a `.js` extension
(`./dataverse.js`) even though the source is `.ts`.

---

### Dataverse client (`src/dataverse.ts`)

Service-to-service client credentials. Copy this close to verbatim — several details here are
non-obvious and each one has cost someone an afternoon.

```ts
export interface DvConfig {
  tenantId: string; clientId: string; clientSecret: string; dataverseUrl: string;
}

const tokenCache = new Map<string, { value: string; expiresAt: number }>();

/** Client-credentials token for an arbitrary resource (Dataverse, Storage, …). */
export async function getTokenForResource(resource: string): Promise<string> {
  const cached = tokenCache.get(resource);
  if (cached && cached.expiresAt > Date.now() + 60_000) return cached.value;

  const body = new URLSearchParams({
    client_id: config.clientId,
    client_secret: config.clientSecret,
    scope: `${resource}/.default`,
    grant_type: 'client_credentials',
  });
  const res = await fetch(
    `https://login.microsoftonline.com/${config.tenantId}/oauth2/v2.0/token`, { method: 'POST', body });
  if (!res.ok) throw new Error(`Token request failed: ${res.status} ${await res.text()}`);
  const json = await res.json() as { access_token: string; expires_in: number };
  tokenCache.set(resource, { value: json.access_token, expiresAt: Date.now() + json.expires_in * 1000 });
  return json.access_token;
}

/** Encode the querystring so spaces in $filter don't break the request. */
function encodePath(path: string): string {
  const i = path.indexOf('?');
  if (i === -1) return path;
  return `${path.slice(0, i)}?${encodeURI(path.slice(i + 1))
    .replace(/#/g, '%23').replace(/\+/g, '%2B')}`;
}

export async function dv<T = any>(path: string, opts: DvOptions = {}): Promise<T> {
  const token = await getTokenForResource(config.dataverseUrl);
  const method = opts.method ?? 'GET';
  const url = `${config.dataverseUrl}/api/data/v9.2/${encodePath(path)}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/json',
    'OData-MaxVersion': '4.0',
    'OData-Version': '4.0',
    'If-None-Match': 'null',          // ← see note below
    ...opts.headers,
  };
  let payload: string | undefined;
  if (opts.body !== undefined) {
    payload = JSON.stringify(opts.body);
    headers['Content-Type'] = 'application/json; charset=utf-8';
    if (method === 'POST' && !headers['Prefer']) headers['Prefer'] = 'return=representation';
  }
  const res = await fetch(url, { method, headers, body: payload });
  if (!res.ok) {
    throw new Error(`Dataverse ${method} ${path} failed: ${res.status} ${(await res.text()).slice(0, 600)}`);
  }
  const entityId = res.headers.get('OData-EntityId');
  const text = await res.text();
  if (!text) return { ok: true, entityId: entityId ?? undefined } as T;   // PATCH/DELETE
  return JSON.parse(text) as T;
}
```

**Non-obvious bits:**

- **`If-None-Match: null`** — without it Dataverse serves 304s from its cache and you read stale
  rows immediately after writing them. This is the single most common "my write didn't save"
  false alarm.
- **`encodePath`** — a `$filter` with spaces raises `InvalidURL` before the request leaves the
  process. Encode the querystring only, never the base path.
- **`Prefer: return=representation`** on POST so you get the created row back instead of a bare
  201 with a header.
- **`OData-EntityId` header** carries the new GUID on POST when you didn't ask for
  representation: `entityId.match(/\(([0-9a-fA-F-]{36})\)/)?.[1]`.
- **Lookups are asymmetric.** You *write* `fsi_Customer@odata.bind: "/accounts(<guid>)"` but you
  *read* `_fsi_customer_value`. Anything that round-trips a lookup (a revert, a diff, an
  optimistic UI update) must convert between the two forms explicitly.

**Formatted values.** Option sets and lookups come back as raw codes and GUIDs unless you ask:

```ts
export const FORMATTED: DvOptions = {
  headers: { Prefer: 'odata.include-annotations="OData.Community.Display.V1.FormattedValue"' },
};
export function label(row: any, field: string, fallback = ''): string {
  return row?.[`${field}@OData.Community.Display.V1.FormattedValue`] ?? fallback;
}
```

Always render the formatted label in the widget. Showing `100000001` to a customer is a bad look.

**Config loading** — environment first, local secrets file as a dev fallback:

```ts
function loadConfig(): DvConfig {
  const envCfg = {
    tenantId: process.env.DV_TENANT_ID, clientId: process.env.DV_CLIENT_ID,
    clientSecret: process.env.DV_CLIENT_SECRET, dataverseUrl: process.env.DV_URL,
  };
  if (envCfg.tenantId && envCfg.clientId && envCfg.clientSecret && envCfg.dataverseUrl) {
    return envCfg as DvConfig;
  }
  const local = join(__dirname, '..', '..', '.secrets', 'dataverse-app.json');
  if (existsSync(local)) return JSON.parse(readFileSync(local, 'utf8')) as DvConfig;
  throw new Error('Dataverse config missing. Set DV_TENANT_ID / DV_CLIENT_ID / DV_CLIENT_SECRET / DV_URL.');
}
```

---

### Dataverse setup (once per org)

1. **App registration** in Entra → client secret.
2. **Application user** in Power Platform admin centre → the org → Users → *Application users* →
   New, pick the app registration, assign **System Administrator** (or a scoped role for prod).
3. Verify end to end before writing any tool code:

```bash
node -e "import('./dist/dataverse.js').then(m=>m.dv('accounts?\$top=1').then(r=>console.log(r.value[0].name)))"
```

If this fails, nothing downstream can work. Fix it here.

---

### Server skeleton (`src/index.ts`)

```ts
import express from 'express';
import { randomUUID } from 'node:crypto';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';

const WIDGET_URI  = 'ui://your-app/workspace.html';
const WIDGET_MIME = 'text/html+skybridge';

function loadWidgetHtml(): string {
  const candidates = [
    join(__dirname, '..', 'public', 'widget.html'),        // baked into the image
    join(__dirname, '..', '..', 'widget', 'dist', 'widget.html'),  // local dev
  ];
  for (const c of candidates) if (existsSync(c)) return readFileSync(c, 'utf8');
  return '<!doctype html><html><body><p>Widget bundle not built yet.</p></body></html>';
}

export function createServer(): McpServer {
  const server = new McpServer(
    { name: 'your-app', version: '1.0.0' },
    { capabilities: { tools: {}, resources: {} } },    // resources REQUIRED for widgets
  );
  // … registerResource + registerTool, see SKILL.md §3
  return server;
}
```

#### Tool shape

```ts
server.registerTool(
  'set_account_strategy',
  {
    title: 'Set the account strategy',
    description:
      'Set the strategy (Strategic Partner / Grow / Hold / Reduce / Phase Out), growth % and ' +
      'rationale on an account plan. Returns the refreshed workspace.',
    inputSchema: {
      planId: z.string().describe('Account plan id.'),
      strategy: z.enum(['Strategic Partner', 'Grow', 'Hold', 'Reduce', 'Phase Out']),
      growthPct: z.number().optional(),
    },
    annotations: { readOnlyHint: false, idempotentHint: true },
    _meta: WIDGET_META,
  },
  async ({ planId, strategy, growthPct }) => {
    await ap.setStrategy(planId, strategy, growthPct);
    return widgetForPlan(planId, 2, `Strategy set to ${strategy}.`);
  },
);
```

**`description` is the model's only routing signal.** It must say *when to use this* and *what
comes back*, in the user's domain language. Vague descriptions are the #1 cause of "the agent
won't call my tool". Include the preconditions ("requires `accountId`") — the model reads them.

**`annotations.readOnlyHint`** lets the host skip confirmation prompts for reads. Set it
honestly; a read marked `false` makes the demo stutter with needless confirmations.

#### Helper: resolve a partial payload into a full one

Plan-scoped tools only know a `planId`, but the widget needs the whole snapshot. Resolve it
server-side rather than making the model chain calls:

```ts
async function widgetForPlan(planId: string, step: number, summary: string) {
  const plan = await ap.getPlan(planId);
  const accountId = plan._fsi_customer_value as string | null;
  if (!accountId) return { content: [{ type: 'text' as const, text: summary }] };
  const snap = await ap.getFullSnapshot(accountId, planId);
  return widgetResult({ ...snap, activeStep: step, mode: 'existing' }, summary);
}
```

---

### HTTP host

```ts
const app = express();
app.use(express.json({ limit: '4mb' }));

const ALLOWED_ORIGIN_SUFFIXES = [
  '.widget-renderer.usercontent.microsoft.com',   // ← the widget iframe sandbox
  'https://m365.cloud.microsoft',
  'https://teams.microsoft.com',
  'https://copilot.microsoft.com',
  'https://vscode.dev',
];

app.use((req, res, next) => {
  const origin = req.headers.origin;
  if (origin && ALLOWED_ORIGIN_SUFFIXES.some((s) => origin.endsWith(s) || origin === s)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
  } else {
    res.setHeader('Access-Control-Allow-Origin', '*');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,DELETE,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers',
    'Content-Type, Authorization, mcp-session-id, mcp-protocol-version, last-event-id');
  res.setHeader('Access-Control-Expose-Headers', 'mcp-session-id');   // ← or sessions break
  if (req.method === 'OPTIONS') { res.sendStatus(204); return; }
  next();
});

app.get('/health', (_req, res) => res.json({ ok: true, service: 'your-app' }));

const transports = new Map<string, StreamableHTTPServerTransport>();

app.all('/mcp', async (req, res) => {
  try {
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    let transport = sessionId ? transports.get(sessionId) : undefined;
    if (!transport) {
      transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        onsessioninitialized: (id) => { transports.set(id, transport!); },
      });
      transport.onclose = () => { if (transport!.sessionId) transports.delete(transport!.sessionId); };
      await createServer().connect(transport);
    }
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error('MCP request error:', err);
    if (!res.headersSent) {
      res.status(500).json({ jsonrpc: '2.0', error: { code: -32603, message: String(err) }, id: null });
    }
  }
});
```

**`Access-Control-Expose-Headers: mcp-session-id`** — without it the browser hides the session
header from the widget and every in-widget `callTool` opens a new session.

**Widget calls come from the iframe origin**, which is a `*.widget-renderer.usercontent.
microsoft.com` subdomain, not from `m365.cloud.microsoft`. Miss that suffix and in-widget tool
calls fail CORS while the agent's own calls work — a confusing half-working state.

**`app.all('/mcp')`** — the transport needs GET (SSE stream), POST (messages) and DELETE
(teardown) on the same path.

---

### Fail loudly on startup

If a precondition is missing, refuse to serve rather than serving something subtly broken:

```ts
journal.initJournal()
  .then(() => app.listen(PORT, () => console.log(`MCP server listening on :${PORT}/mcp`)))
  .catch((err) => {
    console.error('Failed to load the write journal:', err?.message ?? err);
    process.exit(1);   // no journal ⇒ writes are not revertible ⇒ do not serve
  });
```

---

### Testing the server directly

MCP over HTTP needs an `initialize` handshake before `tools/list`. A minimal harness:

```python
# tests/mcpcall.py
import json, urllib.request
URL = "https://<app>.azurecontainerapps.io/mcp"
HDRS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

def rpc(method, params=None, sid=None, _id=1):
    h = dict(HDRS)
    if sid: h["mcp-session-id"] = sid
    body = json.dumps({"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}).encode()
    r = urllib.request.urlopen(urllib.request.Request(URL, body, h))
    sid = r.headers.get("mcp-session-id") or sid
    raw = r.read().decode()
    # streamable HTTP may answer as SSE — take the last data: line
    for line in reversed(raw.splitlines()):
        if line.startswith("data: "):
            return json.loads(line[6:]), sid
    return json.loads(raw), sid

init, sid = rpc("initialize", {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "probe", "version": "1"},
})
tools, _ = rpc("tools/list", {}, sid, 2)
print(len(tools["result"]["tools"]), "tools")
```

Assert the **tool count** in CI. A tool that silently fails to register is otherwise invisible
until someone asks for it mid-demo.


---

<a id="appendix-widget"></a>

## Appendix: Widget

*Originally `reference/widget.md`*

## The widget

A React app, bundled to **one self-contained HTML file**, served as an MCP resource and
rendered by Copilot in a sandboxed iframe with `window.openai` injected.

### Build config — must inline everything

```ts
// widget/vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: 'dist',
    assetsInlineLimit: 100000000,     // inline every asset regardless of size
    cssCodeSplit: false,
    reportCompressedSize: false,
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
```

The iframe has no origin to fetch sibling assets from. **Any external `<script src>` or
`<link href>` produces a blank widget.** One file, no exceptions.

Build script copies the bundle where the server expects it:

```json
"build": "vite build && node -e \"const fs=require('fs');fs.mkdirSync('../server/public',{recursive:true});fs.copyFileSync('dist/index.html','dist/widget.html');fs.copyFileSync('dist/index.html','../server/public/widget.html');console.log('widget.html -> server/public')\""
```

Keep dependencies to React + ReactDOM. A component library will blow the bundle up and most
of it cannot style itself correctly inside the sandbox anyway — hand-rolled CSS matching the
Fluent/D365 palette looks better and loads instantly.

---

### The host bridge (`src/bridge.ts`)

**Capability-detect everything.** The widget must still render in a plain browser with no host
— that is how you preview and screenshot it.

```ts
declare global {
  interface Window {
    openai?: {
      toolInput?: unknown;
      toolOutput?: unknown;
      widgetState?: unknown;
      displayMode?: string;
      theme?: string;
      locale?: string;
      setWidgetState?: (s: unknown) => void | Promise<void>;
      callTool?: (name: string, args: unknown) => Promise<any>;
      sendFollowUpMessage?: (a: { prompt: string }) => void | Promise<void>;
      requestDisplayMode?: (a: { mode: string }) => void | Promise<void>;
      notifyIntrinsicHeight?: (h: number) => void;
      openExternal?: (a: { href: string }) => void;
      setOpenInAppUrl?: (url: string) => void;
    };
  }
}

const oai = () => (typeof window !== 'undefined' ? window.openai : undefined);
export const hostAvailable = () => !!oai();
```

#### Reading tool output

```ts
export function readToolOutput(): Snapshot | null {
  const o = oai()?.toolOutput as any;
  if (!o) return null;
  if (o.structuredContent) return o.structuredContent as Snapshot;   // normal shape
  if (o.account) return o as Snapshot;                                // already unwrapped
  return null;
}

/** Subscribe to host-pushed updates (new tool results, theme, display mode). */
export function useHostSnapshot(): [Snapshot | null, (s: Snapshot) => void] {
  const [snap, setSnap] = useState<Snapshot | null>(() => readToolOutput());
  useEffect(() => {
    const onSet = () => { const next = readToolOutput(); if (next) setSnap(next); };
    const events = ['openai:set_globals', 'openai:tool_response', 'openai:tool_output'];
    events.forEach((e) => window.addEventListener(e, onSet as EventListener));
    return () => events.forEach((e) => window.removeEventListener(e, onSet as EventListener));
  }, []);
  return [snap, setSnap];
}
```

Listen to **all three** event names. Which one fires depends on host version, and the payload
shape varies — tolerate both.

#### Calling tools back from the widget

```ts
export async function callTool(name: string, args: unknown): Promise<any> {
  const fn = oai()?.callTool;
  if (!fn) throw new Error('Tool calling is not available in this host.');
  return fn(name, args);
}

/** Call a tool and fold a fresh snapshot back into the UI if one comes back. */
export async function callToolAndRefresh(
  name: string, args: unknown, apply: (s: Snapshot) => void,
): Promise<string> {
  const res = await callTool(name, args);
  const sc = res?.structuredContent ?? res?.result?.structuredContent;   // both shapes
  if (sc?.account) apply(sc as Snapshot);
  return res?.content?.find?.((c: any) => c.type === 'text')?.text
      ?? res?.result?.content?.find?.((c: any) => c.type === 'text')?.text
      ?? 'Done.';
}
```

This is what makes the widget *interactive* rather than a static card — a button in the UI can
write to Dataverse and refresh itself without a chat turn.

#### Persistent state, theme, display mode, height

```ts
/** Survives re-renders and conversation scrollback. */
export function usePersistentState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    const ws = oai()?.widgetState as any;
    return ws && key in ws ? (ws[key] as T) : initial;
  });
  const set = useCallback((v: T) => {
    setValue(v);
    const ws = (oai()?.widgetState as any) ?? {};
    oai()?.setWidgetState?.({ ...ws, [key]: v });
  }, [key]);
  return [value, set];
}

export function useTheme(): 'light' | 'dark' {
  const read = (): 'light' | 'dark' => {
    const t = oai()?.theme;
    if (t === 'dark' || t === 'light') return t;
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  };
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    const on = () => setTheme(read());
    window.addEventListener('openai:set_globals', on as EventListener);
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    mq?.addEventListener?.('change', on);
    return () => {
      window.removeEventListener('openai:set_globals', on as EventListener);
      mq?.removeEventListener?.('change', on);
    };
  }, []);
  return theme;
}

/** Keep the inline iframe sized to the content — without this it clips. */
export function useAutoHeight(ref: React.RefObject<HTMLElement | null>, deps: unknown[]) {
  useEffect(() => {
    const notify = oai()?.notifyIntrinsicHeight;
    if (!notify || !ref.current) return;
    const report = () => { const h = ref.current?.scrollHeight ?? 0; if (h > 0) notify(h); };
    report();
    const ro = new ResizeObserver(report);
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, deps);
}

export const sendFollowUp = (prompt: string) => oai()?.sendFollowUpMessage?.({ prompt });
export const requestFullscreen = () => oai()?.requestDisplayMode?.({ mode: 'fullscreen' });
export const setOpenInAppUrl = (url: string) => oai()?.setOpenInAppUrl?.(url);
export function openExternal(href: string) {
  const fn = oai()?.openExternal;
  if (fn) fn({ href }); else window.open(href, '_blank', 'noopener');
}
```

**Always support dark mode.** Copilot follows the user's theme and a light-only widget on a
dark chat looks broken. Drive it with CSS custom properties and a `data-theme` attribute.

**`useAutoHeight` is not optional** — inline widgets default to a short fixed height and your
card will be cut off mid-table.

---

### App root: reconciling two sources of state

The widget receives state from two places — the host (a new tool result) and its own
`callTool` responses. They can arrive out of order. Resolve with the server's `renderedAt`
stamp:

```tsx
function newerOf(a: Snapshot | null, b: Snapshot | null): Snapshot | null {
  if (!a) return b;
  if (!b) return a;
  return (b.renderedAt ?? '') > (a.renderedAt ?? '') ? b : a;
}

export default function App() {
  const [hostSnap] = useHostSnapshot();
  const [local, setLocal] = useState<Snapshot | null>(null);
  const snap = newerOf(local, hostSnap);

  // Every fresh host payload supersedes optimistic local state and re-seeds the
  // active step, so "update the narrative" re-renders on step 2 rather than
  // leaving the user parked wherever they last were.
  const seededRef = useRef<string | null>(null);
  useEffect(() => {
    if (!hostSnap) return;
    const stamp = hostSnap.renderedAt ?? '__initial__';
    if (seededRef.current === stamp) return;
    seededRef.current = stamp;
    setLocal(null);
    if (hostSnap.activeStep) setStep(hostSnap.activeStep);
  }, [hostSnap?.renderedAt, hostSnap]);
```

Without this the widget appears to freeze: the first payload wins forever and every subsequent
tool call seems to do nothing.

#### Explicit refresh

Offer a refresh button that goes **back to Dataverse** rather than patching local state, so it
also picks up edits made in Dynamics or by a colleague outside the conversation:

```tsx
const res = await callTool('refresh_workspace', { account, plan, step });
const sc = res?.structuredContent ?? res?.result?.structuredContent;
if (sc?.account) setLocal({ ...(sc as Snapshot), activeStep: step });  // keep the user's step
```

Note `activeStep: step` — refreshing must not move the user.

---

### Making it look like Dynamics 365

What sells the demo is that it looks native. Build a small shell module:

- **`AppBar`** — waffle, app name, search, settings cluster
- **`RecordHeader`** — record title, key fields in a row, record-type chip
- **`CommandBar`** — `+ New`, Save, Refresh, Assign, Flow, overflow `…`
- **`ProcessBar`** — the BPF stage chevrons, with the active stage expanded
- **`TabStrip`** — General / Related / etc.

Palette: D365 blue `#0F6CBD`, neutral greys, 4px radii, 12–14px type, generous whitespace.
Use the `accentColor` from the Teams manifest so chat chrome and widget agree.

**Deep-link out to the real app** so the agent composes with Dynamics rather than replacing it:

```tsx
useEffect(() => {
  const url = snap?.links?.plan ?? snap?.links?.account;
  if (url) setOpenInAppUrl(url);          // wires the host's "open in app" affordance
}, [snap?.links?.plan, snap?.links?.account]);
```

Build the URL server-side:
`${DV_URL}/main.aspx?appid=${AP_APP_ID}&pagetype=entityrecord&etn=${table}&id=${guid}`

---

### Embedding the model-driven app itself: don't

Iframing a Dynamics 365 or canvas app URL inside the widget **does not work**. Dataverse sends
`X-Frame-Options`/CSP that the Copilot sandbox cannot satisfy, and the host does not currently
honour `openai/frameDomains`. The frame renders blank or refuses to load.

Build the UI natively in the widget against the same data, and use `setOpenInAppUrl` /
`openExternal` to hand off to the real app in a new tab when the user wants the full surface.

---

### Preview harness — look at it before you ship

Accessibility snapshots do not catch cosmetic defects. Build static preview pages from captured
fixtures and screenshot them.

1. **Capture real payloads** once, through the live server, into `scripts/fixtures/*.json`.
2. **`scripts/preview.mjs`** writes `preview/*.html`: the built bundle with
   `window.openai = { toolOutput: { structuredContent: FIXTURE }, theme }` injected before the
   app script. Emit a light and a dark page per card.
3. Serve and screenshot:

```bash
node scripts/preview.mjs && python3 -m http.server 8899 -d preview
# then screenshot every page, light and dark, and LOOK at them
```

Defects this catches that nothing else does: an emptied field leaving a stray "—" chip,
numbers overflowing their column, a dark-mode contrast failure, a doubled currency prefix
(`AED AED 60.0B`) buried in prose.

**Dump prose untruncated when checking it.** Truncated output has hidden a second instance of
exactly the same bug on the line below.
