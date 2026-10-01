# AI Agent Skills — Complete Bundle

Every skill in one file. Each section below is a complete, self-contained skill including its reference material.

Source: https://github.com/erturkm/ai-agent-skills

## Contents

- [copilot-mcp-app](#skill-copilot-mcp-app)
- [build-d365](#skill-build-d365)
- [cij-marketing](#skill-cij-marketing)
- [demo-video-producer](#skill-demo-video-producer)


---

<a id="skill-copilot-mcp-app"></a>

# Skill: `copilot-mcp-app`

> Build a Microsoft 365 Copilot declarative agent backed by a remote MCP server (an 'MCP App') that reads and writes live Dataverse / Dynamics 365 data and renders rich interactive D365-styled React widgets inside Copilot chat. Covers the MCP server with openai/outputTemplate widget binding, the Dataverse S2S client, the React widget and window.openai host bridge, the agent app package (manifest + declarativeAgent + ai-plugin), Azure Container Apps deployment, Graph app-catalog publishing, a revertible write journal for demo safety, and a local screenshot preview harness. Use whenever someone wants to build, extend, debug or demo a Copilot agent with custom UI, mentions declarative agent, MCP app, MCP server, Copilot widget, Copilot extensibility, agent app package, or wants D365 data surfaced natively in M365 Copilot chat.

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

### 1. What you are actually building

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

### 2. Build order

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

### 3. The widget binding contract

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

### 4. Rules that save days

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

### 5. Project layout

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

### 6. Verification — what "done" means

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

### 7. Making it demo-safe

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

### Appendix: Agent Package

*Originally `reference/agent-package.md`*

### Agent app package & publishing

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

#### manifest.json

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

#### ai-plugin.json — wiring the MCP server

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

#### declarativeAgent.json

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

#### Writing instructions that actually drive the tools

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

#### Rendering and publishing (`scripts/publish.py`)

##### Render

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

##### Auth — delegated device code, not app-only

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

##### Upload

```
POST   /v1.0/appCatalogs/teamsApps                        ← first publish
POST   /v1.0/appCatalogs/teamsApps/{appId}/appDefinitions ← update
Content-Type: application/zip, body = raw zip bytes
```

##### Supporting multiple agents on one server

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

#### Publish errors you will hit

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

#### Validating the package in CI

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

### Appendix: Demo Safety

*Originally `reference/demo-safety.md`*

### Demo safety

Demo orgs are shared. Your agent writes to Dataverse. Without the controls below, one rehearsal
quietly corrupts a colleague's demo data and nobody notices until they are on stage.

**Build the journal before the first write tool.** Retrofitting it cannot undo the writes you
have already made.

---

#### 1. The write journal

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

##### Wrap every write

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

##### Storage

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

#### 2. The read-only guard

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

##### Shared rows are the hard case

Some journeys genuinely must edit *shared, account-level* rows that pre-date the agent (share of
wallet, cross-sell, stakeholders). Blocking those guts the demo. The resolution is not to block
them but to **journal them with their prior values** so they are restorable. Protection applies
to the parent record; shared children are journalled.

---

#### 3. The two presenter tools

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

#### 4. Display-name masking for public stages

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

##### Leak scan — automate it

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

##### Seeding the masked account

Copy the real account's rows to the masked account and scrub the copies. **Never modify the
source rows.** Assert it afterwards rather than trusting it:

```python
before = snapshot_of(REAL_ACCOUNT)
seed_masked_account()
assert snapshot_of(REAL_ACCOUNT) == before, "source data was modified"
```

---

#### 5. Pre-demo checklist

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

### Appendix: Deploy

*Originally `reference/deploy.md`*

### Deployment

Azure Container Apps, image built by ACR Tasks (no local Docker needed), everything described
in bicep so re-deploys are idempotent.

#### Dockerfile

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

#### bicep (`infra/main.bicep`)

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

#### deploy.sh

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

##### The two-pass deploy

You cannot build into a registry that doesn't exist. Pass 1 provisions with a placeholder (or
the currently running image, on re-deploys); pass 2 rolls to the freshly built tag.

##### Unique tags are mandatory

Container Apps compares the template and **creates no revision if it is byte-identical**.
`:latest` therefore deploys nothing, silently, and you debug "my fix didn't work" for an hour.
Timestamp every tag.

##### Set env vars through bicep only

Never `az containerapp update --set-env-vars`. It works, and the next bicep deploy wipes it.
Every variable belongs in `main.bicep` with a parameter fed from `.env`.

---

#### `.env` discipline

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

#### Azure failure modes that are lies

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

#### Verify after every deploy

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

#### Cost

Roughly **$35–60/month**: Container Apps 0.5 vCPU / 1 GiB pinned at one replica (~$30–45), ACR
Basic (~$5), Log Analytics (~$3 at low volume). Scaling to zero saves ~$30 but adds a cold
start — keep `minReplicas: 1` for anything you demo.

Tear down: `az group delete -n "$RG" --yes --no-wait`.


---

<a id="appendix-mcp-server"></a>

### Appendix: Mcp Server

*Originally `reference/mcp-server.md`*

### MCP server

Node 22 + TypeScript + `@modelcontextprotocol/sdk` over **streamable HTTP**. This is the only
transport Copilot supports for remote MCP servers — not stdio, not SSE-only.

#### Dependencies

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

#### Dataverse client (`src/dataverse.ts`)

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

#### Dataverse setup (once per org)

1. **App registration** in Entra → client secret.
2. **Application user** in Power Platform admin centre → the org → Users → *Application users* →
   New, pick the app registration, assign **System Administrator** (or a scoped role for prod).
3. Verify end to end before writing any tool code:

```bash
node -e "import('./dist/dataverse.js').then(m=>m.dv('accounts?\$top=1').then(r=>console.log(r.value[0].name)))"
```

If this fails, nothing downstream can work. Fix it here.

---

#### Server skeleton (`src/index.ts`)

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

##### Tool shape

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

##### Helper: resolve a partial payload into a full one

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

#### HTTP host

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

#### Fail loudly on startup

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

#### Testing the server directly

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

### Appendix: Widget

*Originally `reference/widget.md`*

### The widget

A React app, bundled to **one self-contained HTML file**, served as an MCP resource and
rendered by Copilot in a sandboxed iframe with `window.openai` injected.

#### Build config — must inline everything

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

#### The host bridge (`src/bridge.ts`)

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

##### Reading tool output

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

##### Calling tools back from the widget

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

##### Persistent state, theme, display mode, height

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

#### App root: reconciling two sources of state

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

##### Explicit refresh

Offer a refresh button that goes **back to Dataverse** rather than patching local state, so it
also picks up edits made in Dynamics or by a colleague outside the conversation:

```tsx
const res = await callTool('refresh_workspace', { account, plan, step });
const sc = res?.structuredContent ?? res?.result?.structuredContent;
if (sc?.account) setLocal({ ...(sc as Snapshot), activeStep: step });  // keep the user's step
```

Note `activeStep: step` — refreshing must not move the user.

---

#### Making it look like Dynamics 365

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

#### Embedding the model-driven app itself: don't

Iframing a Dynamics 365 or canvas app URL inside the widget **does not work**. Dataverse sends
`X-Frame-Options`/CSP that the Copilot sandbox cannot satisfy, and the host does not currently
honour `openai/frameDomains`. The frame renders blank or refuses to load.

Build the UI natively in the widget against the same data, and use `setOpenInAppUrl` /
`openExternal` to hand off to the real app in a new tab when the user wants the full surface.

---

#### Preview harness — look at it before you ship

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


---

<a id="skill-build-d365"></a>

# Skill: `build-d365`

> Build end-to-end Microsoft Dynamics 365 / Power Platform demos programmatically on a demo tenant via the Dataverse Web API: solutions, tables, columns, relationships, forms and form XML surgery, collapsible form headers, views, model-driven apps and sitemaps, BPFs, custom HTML web resources that read and write live Dataverse data, PCF controls, Power Automate cloud flows, Copilot Studio AI agents (Standard and GitHub Copilot harness), Dataverse MCP tools, Azure AI Foundry agents, and demo data s

> **Bundled skill file.** This single document contains `SKILL.md` plus all 5 reference file(s), inlined as appendices below. Cross-references have been rewritten to in-page links.
>
> **Appendices:**
> - [Ai Agents](#appendix-ai-agents)
> - [Forms Schema Apps](#appendix-forms-schema-apps)
> - [Pcf](#appendix-pcf)
> - [Power Automate](#appendix-power-automate)
> - [Web Resources](#appendix-web-resources)


You are building a polished Microsoft Dynamics 365 / Power Platform demo on a demo tenant.
Treat it as a real engineering project, not advice — install tooling, write scripts, hit the
Dataverse Web API directly, and verify before declaring anything done.

Deep reference files live next to this skill. Read them on demand — do not guess when one covers the topic:
- `~/.copilot/m-skills/build-d365/#appendix-forms-schema-apps` — tables, columns, relationships, form XML,
  views, BPFs, appmodules/sitemaps, solution lifecycle, demo reset
- `~/.copilot/m-skills/build-d365/#appendix-power-automate` — cloud flows via `workflow.clientdata`,
  connection references, triggers, approvals, expression gotchas
- `~/.copilot/m-skills/build-d365/#appendix-ai-agents` — Copilot Studio `bot`/`botcomponent`, YAML dialect,
  tools, MCP, publishing, harness fork, Azure AI Foundry
- `~/.copilot/m-skills/build-d365/#appendix-web-resources` — HTML/JS web resources, Xrm in iframes, $batch,
  CDN/CSP, bridges, print
- `~/.copilot/m-skills/build-d365/#appendix-pcf` — PCF authoring, manifests, binding via form XML, importing
  solution zips when `pac` is broken

═══════════════════════════════════════════════════════════════════════════════
0. DISCOVER MY CONTEXT FIRST
═══════════════════════════════════════════════════════════════════════════════
Before doing anything, ask me for (and remember for the session):
  • Industry / scenario (retail banking, corporate lending, manufacturing, healthcare, aviation…)
  • Short demo name (solution display name)
  • Publisher prefix, 2–8 chars (e.g. fsi, cpc, acme) — every table, column, web resource uses `<prefix>_`
  • Demo org URL (https://orgXXXXXX.crmN.dynamics.com)
  • Whether this is a **fresh build** or an **additive change to an org that already hosts other demos**
Never hardcode a prefix, table name, org URL or GUID from another demo.

If the org already hosts other demos: run a collision guard before creating anything — hardcode the list of
new table logical names you intend to create and abort if any already exists
(`EntityDefinitions?$filter=IsCustomEntity eq true`). Two demos sharing one publisher prefix in one org is a
recurring source of damage.

═══════════════════════════════════════════════════════════════════════════════
1. ENVIRONMENT, AUTH & THE dv.py HELPER
═══════════════════════════════════════════════════════════════════════════════
Already installed on this machine (macOS arm64) — do NOT reinstall:
  • pac CLI: `~/.dotnet/tools/pac`
  • .NET runtime: `~/.dotnet` (the system `/usr/local/share/dotnet` only has older SDKs)
Before ANY pac command:
```bash
export DOTNET_ROOT="$HOME/.dotnet"
export PATH="$HOME/.dotnet:$HOME/.dotnet/tools:$PATH"
```
If pac errors "You must install or update .NET … version '10.0.0'", the exports were missing for that shell.
Never trust `command -v dotnet` — verify with `dotnet --list-sdks`.

Auth once: `pac auth create --url <ORG_URL>` (MSAL refresh token cached ~90 days). Don't re-run device code
per script.

**Every demo gets its own isolated `scripts/dv.py`** (copy, don't share across projects). It must:
  - read the active org URL from `pac auth list` (the `*` row), or take it explicitly
  - acquire a token (`az account get-access-token --resource <org>` or MSAL device code with the Azure CLI
    public client id `51f81489-12ee-4a9e-aaae-a2591f45987d`), cache it, and **trust the real expiry** — a long
    design pass can exceed a naive TTL and 401 mid-flight; force-refresh and retry once on 401
  - expose `api(method, path, body=None, headers=None)` plus `get/post/patch/delete`, `find_one(set, filter)`
    and `new_id(resp)` (parses the `OData-EntityId` / `Location` header — POST returns no body by default)
  - URL-encode `$` as `%24` (urllib will not; `$filter`/`$select`/`$expand` otherwise 400)
  - add `MSCRM.SolutionUniqueName: <solution>` on every create/update that should land in the solution
  - escape single quotes in OData filters by doubling them (`name.replace("'", "''")`)
  - **retry/backoff centrally**: 429/503/504, SQL deadlock `Sql Number: 1205`, timeouts, and 500/502 whose
    body contains "another [Import]" or "solution is currently being imported" →
    `sleep(min(60, 5 * 2**(attempt-1)))`. Publishes are environment-wide single-threaded.
  - **resilient metadata writes**: a metadata POST can exceed the client timeout and still succeed
    server-side. On exception, sleep and re-check existence (`GET EntityDefinitions(LogicalName=…)`) before
    concluding it failed.

All Dataverse work goes through dv.py. The UI is for verification, not for building — with the specific
exceptions listed in §6.

═══════════════════════════════════════════════════════════════════════════════
2. PRINCIPLES
═══════════════════════════════════════════════════════════════════════════════
• Web API > UI clicks. Tables, columns, choice sets, forms, views, web resources, workflows, appmodules,
  sitemaps, connection references, bots — all are Dataverse rows you can POST/PATCH.
• Everything goes in one solution with my publisher prefix, via the `MSCRM.SolutionUniqueName` header.
  There is no "current solution" context — pass it on every call or the component lands in Default.
• Publish after web resource / form / view / sitemap / appmodule changes. Prefer **targeted** `PublishXml`
  over `PublishAllXml` (which times out on large solutions).
• Hard-refresh the browser (Cmd/Ctrl+Shift+R) after publishing — D365 caches aggressively.
• Idempotency is mandatory: every script is find-or-create, strips its own previous injection before
  re-inserting, and can be re-run safely. Tag anything you inject into shared objects with a project-specific
  marker (e.g. tab `name="cpc_processtab_…"`) so you can find and strip it later.
• Back up before mutating anything shared: fetch and persist the current `formxml`, `sitemapxml`, flow
  `clientdata` or `layoutxml` to a timestamped file on disk first.
• **Additive by default.** Prefer creating a new named form / new tab / new app over editing a stock one.
• Never assume environment IDs. `POST /RetrieveCurrentOrganization` → `Detail.EnvironmentId`.
  The **Copilot Studio environment id ≠ Dataverse org id** — using the org id in a
  `copilotstudio.microsoft.com/environments/<id>/…` URL silently redirects to the tenant default environment.
• For demo surfaces, custom HTML web resources usually beat PCF: faster iteration, no build step, no pac
  lifecycle. Use PCF when you need a schema-bound field control or a dataset/subgrid control.
• **A green run is not evidence of a correct result.** Integer division, stale option-set mappings, currency
  mismatches, agent refusal strings and silent MCP fallbacks all return HTTP 200 with confidently wrong
  output. Verify values, not status codes.

═══════════════════════════════════════════════════════════════════════════════
3. SCHEMA, FORMS, VIEWS, APPS  (details: #appendix-forms-schema-apps)
═══════════════════════════════════════════════════════════════════════════════
**Tables/columns** — POST to `EntityDefinitions`; set `SchemaName == LogicalName` in lowercase so later
`GET EntityDefinitions(LogicalName='…')` idempotency checks match first time. Seed attribute with
`IsPrimaryName: true`. Every DisplayName/Description needs the full `Label`/`LocalizedLabel` `@odata.type`
boilerplate. Attribute `@odata.type` per kind: String/Memo/Integer/Decimal/Money (+`PrecisionSource:2`)/
Boolean (nested `BooleanOptionSetMetadata`)/DateTime (+`DateTimeBehavior`)/Picklist. **Local option sets still
require `OptionSet.Name`** — convention `{entity_logical}_{column}`. Prefer local option sets over global.

**Relationships** — POST `RelationshipDefinitions` with `OneToManyRelationshipMetadata`; this is how you create
a lookup column (there is no separate message). Keep the relationship `SchemaName` ≤ 100 chars. Default
cascade `NoCascade`/`RemoveLink`; only widen `Delete: Cascade` for genuine parent-child pairs.
**Always resolve `ReferencingEntityNavigationPropertyName` / relationship SchemaName live** from
`EntityDefinitions(LogicalName='X')/ManyToOneRelationships` — Dataverse may assign a different name than you
asked for, and `@odata.bind` casing is PascalCase (`fsi_ParentEntity@odata.bind`, not lowercase).

**Form XML** — `systemform.type` 2 = Main. Control classids you will need constantly:
```
String/Uniqueidentifier {4273EDBD-AC1D-40D3-9FB2-095C621B552D}
Memo                    {E0DECE4B-6FC8-4A8F-A065-082708572369}
Integer                 {C6D124CA-7EDA-4A60-AEA9-7FB8D318B68F}
Decimal/Double          {C3EFE0C3-0EC6-42BE-8349-CBD9079DFD8E}
Money                   {533B9E00-756B-4312-95A0-DC888637AC78}
Picklist/Status         {3EF39988-22BB-4F0B-BBBE-64B5A3748AEE}
State                   {5D68B988-0661-4DB2-BC3E-17598AD3BE6C}
Boolean                 {B0C6723A-8503-4FD7-BB28-C8A06AC933C2}
DateTime                {5B773807-9FB2-42DB-97C3-7A91EFF8ADFF}
Lookup/Customer/Owner   {270BD3DB-D9AF-4782-9025-509E298DEC0A}
Subgrid                 {E7A81278-8635-4D9E-8D4D-59480B391C5B}
Web resource / IFRAME   {9FDF5F91-88B1-47F4-AD53-C11EFC01A01D}
```
Every tab/section/cell/control needs a fresh `uuid4()` — **GUID uniqueness across a form is load-bearing**;
duplicated ids corrupt the form silently or throw "form contains errors" in the designer. A bound cell's
`control id` equals the field logical name by convention so form scripts can `getControl(name)`.
Edit by bounded regex / string slicing, never full XML re-parse. Views must exist before forms that embed
them as subgrids (subgrids need a real `ViewId` in `{braces}`).

**Form header & the collapse button** — the real client API is
`formContext.ui.headerSection.getBodyVisible() / setBodyVisible(bool)`:
```js
function toggleHeader(ctx) {
  const ui = ctx.getFormContext().ui;
  if (ui.headerSection) {
    const cur = ui.headerSection.getBodyVisible ? ui.headerSection.getBodyVisible() : true;
    ui.headerSection.setBodyVisible(!cur);
  }
}
```
This collapses the header body while keeping the header bar visible. In these demos it is triggered from a
button inside an embedded web resource (or a form-script function exposed on a public IIFE object), **not**
from a ribbon button. Header holds max 4 fields.

**Command bar** — RibbonDiffXml is effectively unused here; every entity's block is an empty stub. Interactive
actions are form-script functions exposed via an IIFE (`fsi_corporatelending.js` returning
`{convertInsightToOpportunity, generateCreditMemo, toggleHeader, …}`) and invoked from web-resource buttons.
Do that unless the user explicitly wants a native command-bar button.

**Views** — find the existing `savedquery` by `(returnedtypecode, name)` and PATCH `fetchxml` + `layoutxml`
**together** (never one without the other, or columns desync). Never create a duplicate system view.
Default filter `statecode eq 0`. `view_id()` returns `{guid}` with braces for subgrid `<ViewId>`.

**Model-driven app** — `appmodule` `{name, uniquename, clienttype: 4, webresourceid: <svg icon>,
navigationtype: 0|1}`. `navigationtype` 1 = multi-session workspace (its session rail eats vertical space —
use 0 unless the demo needs multi-session). Icons upload as `webresourcetype: 11` SVG.
**Trap:** `AddAppComponents` types `Components` as `Collection(mscrm.crmbaseentity)`; passing an entity
MetadataId resolves against the literal `entity` table, returns HTTP 200 and registers a junk no-op.
Drive table exposure through the **sitemap's `SubArea Entity="…"`** instead. `POST /appmodules` has been seen
to create the row and then throw "appmodule … Does Not Exist", leaving an invisible app — if that happens,
create the app once by hand and script everything downstream against the known `appmoduleid`.
Validate with `POST ValidateApp {"AppModuleId": id}`; publish with an `<appmodules>` + `<sitemaps>` PublishXml.

**BPFs** — there is no supported create-BPF message. A BPF is a `workflow` row with `category: 4` and it needs
**both** `clientdata` and `xaml` describing the same plan (missing `xaml` → `0x80040203`). Generate both from
one shared plan so ids never drift, then activate with `{"statecode":1,"statuscode":2}`.
A BPF is invisible on a form unless the workflow is also registered as a component of the app.

**Demo data** — seed linked chains with `@odata.bind`; prefix demo rows with `*` so they're filterable.
Build a reset script with a **hard allowlist** of table logical names (never a `startswith('fsi_')` match),
scoped to one parent record, that refuses to run unless a JSON snapshot exists on disk, and supports staged
rewind. See reference for the full pattern.

═══════════════════════════════════════════════════════════════════════════════
4. POWER AUTOMATE FLOWS  (details: #appendix-power-automate)
═══════════════════════════════════════════════════════════════════════════════
A cloud flow is a `workflow` row: `category: 5`, `type: 1`, `primaryentity` = trigger entity or `"none"`,
and `clientdata` = the **JSON-stringified** `{schemaVersion:"1.0.0.0", properties:{connectionReferences, definition}}`.
Find existing with `workflows?$filter=name eq '…' and category eq 5`.

**Upsert sequence (use this every time):**
```
if exists and statecode==1: PATCH {statecode:0, statuscode:1}   # must be OFF to edit clientdata
PATCH {clientdata, description}
PATCH {statecode:1, statuscode:2}                                # reactivate
```

**Connections.** Use `runtimeSource: "invoker"` + a named `connectionreference`, not `"embedded"` —
embedded breaks the modern designer:
```json
"shared_commondataserviceforapps": {
  "runtimeSource": "invoker",
  "connection": {"connectionReferenceLogicalName": "fsi_sharedcommondataserviceforapps_d15df"},
  "api": {"name": "shared_commondataserviceforapps"}
}
```
Declare `definition.parameters` `$connections` (Object) and `$authentication` (SecureObject), and put
`"authentication": "@parameters('$authentication')"` on **every** OpenApiConnection / OpenApiConnectionWebhook
action and connector trigger. Skip any of these and the designer 404s or refuses to save.
Pure-calculation flows can use `connectionReferences: {}`.
Create the `connectionreference` row with `connectorid: "/providers/Microsoft.PowerApps/apis/shared_x"` and a
real `connectionid`; find live connections via
`GET https://api.powerapps.com/providers/Microsoft.PowerApps/connections?api-version=2020-06-01&$filter=environment eq '<envId>'`
(filter on `properties.apiId` suffix, `statuses[].status == 'Connected'`, owner email; pick newest).

**Triggers.** Dataverse: `OpenApiConnectionWebhook` + `operationId: SubscribeWebhookTrigger` with
`subscriptionRequest/{message, entityname, scope: 4, filteringattributes, filterexpression}` — prefer
`filterexpression` over a trigger `conditions[]` block. Agent-callable flows use `kind: "Skills"` on both the
Request trigger and the Response action. Browser-callable flows use `kind: "Http"` plus
`Access-Control-Allow-Origin` on the response, with the invoke URL stored in a Dataverse config row, never
hardcoded in source.

**Approvals.** `shared_approvals` + `StartAndWaitForAnApproval`, params prefixed
`WebhookApprovalCreationInput/…`, outcome at `body/outcome`. A blocking "start and wait" cannot be called
from an agent tool — split into Flow A (Skills trigger, writes a gate row, returns immediately) and Flow B
(Dataverse Create trigger on the gate row, does the blocking approval and writes the decision back); the UI
polls Dataverse.

**Expression gotchas that produce silently wrong numbers, not errors:**
- `div(int, int)` is integer division → wrap the numerator: `div(float(x), y)`
- `abs()` does not exist in Power Automate → `if(less(X,0),mul(X,-1),X)`; unknown functions only fail at
  runtime as a generic BadGateway
- `toLower()` throws on non-strings → `toLower(trim(coalesce(string(x),'')))`
- optional Skills-trigger inputs are **absent**, not null → always `coalesce(triggerBody()?['x'], default)`
- rounding idiom: `float(formatNumber(expr,'F2'))`
- build option-set mappings from **live metadata**, and update every duplicated copy (including ones embedded
  in `$filter` strings)
- Dataverse `UpdateRecord` upserts — a PATCH with an id the caller invented silently **creates an orphan row**.
  Find-or-create on a natural key instead.
- watch for currency/unit mismatches (USD amount tested against AED thresholds routes silently wrong)

Close the Power Automate designer tab before applying programmatic PATCHes — browser autosave will clobber them.

═══════════════════════════════════════════════════════════════════════════════
5. AI AGENTS  (details: #appendix-ai-agents)
═══════════════════════════════════════════════════════════════════════════════
**Default for new demos: build agents on the GitHub Copilot harness** (the new Copilot Studio "Agents"
experience), not the Standard harness. Leave existing demos on whatever harness they already use.
`bot.template` is the discriminator: `default-2.1.0` = Standard, `cliagent-1.0.0` = GitHub Copilot harness.
Creating a bot through the `bots` API does not let you choose the harness — GitHub-Copilot-harness agents are
created in the UI, then scripted against.

**The harness routing fork — the most dangerous failure in this whole skill.** Each harness is reachable
through a different connector:

| Harness | template | Reachable via |
|---|---|---|
| Standard | `default-*` | Copilot Studio connector, `ExecuteCopilotAsyncV2` (`shared_microsoftcopilotstudio`) |
| GitHub Copilot | `cliagent-*` | Agent-node connector, `InvokeAgent` (`shared_agentnode`) |

Calling a `cliagent-*` agent through `ExecuteCopilotAsyncV2` does **not** fail. The agent replies with the
literal string *"This action doesn't support agents built with the GitHub Copilot harness"*, the connector
reports success, the run is green, and that refusal text gets written onto real records. Always branch on
`bot.template` and assert on the refusal substring as a canary in your end-to-end test.

**Rows.** `bot`: `{name, schemaname, language: 1033, template, authenticationmode: 2, runtimeprovider: 0,
configuration: <JSON with GenerativeActionsEnabled, gPTSettings, aISettings, recognizer>}`.
`botcomponent.componenttype`: **9** = dialog-shaped (topics AND tools AND connected agents — distinguished
only by the YAML `kind:` inside `data`), **15** = GPT/system instructions. `schemaname` must be
`<bot schema>.<suffix>`; link with `parentbotid@odata.bind`.

**Tool YAML shapes** — ConnectorTool (`authMode: Invoker`, `connectionReference`, `connectorId` — mandatory or
`BotDefinitionOverride has unresolved references`), WorkflowTool (`workflowId` = the workflow **primary key**,
not workflowidunique; `connectionProperties: {mode: Invoker}`), connected agent (`TaskDialog` +
`InvokeConnectedAgentTaskAction` + `dependencies`), MCP (below).

**Dataverse MCP:** `operationId` must be **`InvokeMCPPreview`**, not `InvokeMCP` — with `InvokeMCP` the row
publishes cleanly and shows in the portal but reports "no tools available" (the empty-shell symptom). The
`connectionReference` is **per agent** (`<agent schema>.shared_commondataserviceforapps.<connection-guid>`)
even when the underlying connection is shared. `connectionProperties.mode`: `Invoker` runs as the chatting
user, who may lack privileges → reads come back silently empty; `Maker` pins to the connection owner.
MCP also needs the environment feature enabled and the client app allow-listed in PPAC (Entra has no dynamic
client registration).

**Publishing:** `POST /bots(<botid>)/Microsoft.Dynamics.CRM.PvaPublish` with `{}` (fast, reliable). Verify via
`publishedon` on the bot row — the portal agent grid caches stale "Draft" for minutes. `pac copilot publish`
wants `--bot <bot-guid>` (schema name is documented but fails in practice).
Pre-publish trap: API-created action inputs default to `kind: ManualTaskInput` and fail publish with
`MissingRequiredProperty: 'Value'` — set `kind: AutomaticTaskInput` so the orchestrator fills them.

**The hard limit — tools usually cannot be fully created via the API.** The `botcomponent` row is only half
the registration; the Copilot Studio designer writes an additional binding outside `botcomponent.data`. A
byte-identical API row still throws `FlowNotFound: The flow with id <guid> was not found in the bot definition`
at runtime (surfacing to users only as "the bot can't talk right now"). Plan for adding flow/MCP tools **by
hand in the Copilot Studio UI** (or via Playwright), then patching cosmetics via API. Tell the user this is a
UI step rather than burning hours scripting it. Also: one flow can only be a tool on one agent.

**Direct invoke:**
```
POST https://{HOST}/copilotstudio/dataverse-backed/authenticated/bots/{schemaname}/conversations
body MUST be wrapped: {"activity": {...}}       # a bare activity → HTTP 400
```
HOST = environment id as raw hex, dashes stripped, split first-30 + last-2:
`f"{h[:-2]}.{h[-2:]}.environment.api.powerplatform.com"`. Scope
`https://api.powerplatform.com/CopilotStudio.Copilots.Invoke`. The caller must be **shared on the bot record**
or you get HTTP 200 with a trace activity `ErrorCode=AccessToBotDenied` — inspect the trace, not the status.

**Agent prompt/tool engineering:**
- If an agent keeps asking for an optional input despite instructions, the fix is **unbinding the input in the
  tool schema**, not more prompt text. Keep Skills-trigger `required` arrays minimal.
- Schema `description` text is read by the orchestrator — the working idiom is
  *"Optional. Omit it if you were not given a value and do not have a basis to infer one. Never ask the user for it."*
- `AutomaticTaskInput` handles JSON `number` but silently fails on `integer` — use `number` and `int()` server-side.
- Producer/consumer output↔input **name mismatches** look identical to the unbind bug — rename to match.
- A connected-agent handoff structurally ends the orchestrator's turn; the agent holding the data must persist
  it itself rather than handing back.
- Debug order: Copilot Studio **test pane** (names the exact flow GUID and failure) → the flow's 28-day run
  history → Dataverse (`flowruns` only logs scheduled runs). Build one reference tool by hand and diff.
- Generative orchestration is a **toggle** (Settings → Generative AI), not a rebuild; connected agents need it
  or the parent just answers itself.
- MCP silent-degrade: when Copilot Studio can't enumerate MCP tools (expired OAuth), the planner quietly falls
  back to the built-in `UniversalSearchTool`, returns null in ~60ms, and the flow still writes
  `status = Completed`. Diagnose via the run's `DynamicPlanReceived → value.steps`: healthy shows
  `MCP:<agent>.action.<connector>:<tool>`, broken shows `P:UniversalSearchTool`.

**Azure AI Foundry agents** (when the demo needs a raw LLM synthesizer rather than a Copilot Studio agent):
invoke through the **project-scoped** `/api/projects/{project}/openai/v1/responses`; pass `"tools": []`
explicitly or project defaults inject `web_search_preview`; scope `https://ai.azure.com/.default`.
Model quirks are real and per-model — some models 500 on the Agents API but work on chat completions, and
`json_schema`/`strict` support differs. Strict json_schema requires `additionalProperties: false` on every
object and every property listed in `required` (express optionality as nullable types).

═══════════════════════════════════════════════════════════════════════════════
6. WHEN THE UI IS UNAVOIDABLE
═══════════════════════════════════════════════════════════════════════════════
Almost everything is scriptable. These are the known exceptions — do them in the browser (Playwright is fine)
and say so up front rather than burning hours:
  • Adding flow / MCP / connector **tools to a Copilot Studio agent** (§5)
  • Creating a **GitHub Copilot harness** agent shell
  • Adding agent **knowledge sources** (public website / SharePoint / file upload)
  • Recovering from a broken `POST /appmodules` (create the app once by hand)
  • The Generative orchestration toggle

═══════════════════════════════════════════════════════════════════════════════
7. DEMO STRUCTURE THAT WORKS WELL
═══════════════════════════════════════════════════════════════════════════════
• One solution per demo, one publisher prefix, one isolated `scripts/` folder with its own `dv.py`.
• Custom tables for the domain entities of the industry — ask, don't reuse another demo's schema.
• Custom HTML web resources for the "wow" surfaces: Customer 360, cockpits, checklists, command centres.
  They read and write Dataverse via `Xrm.WebApi` and feel native.
• PCF only where a schema-bound field control or dataset/subgrid control is genuinely needed; build generic,
  field-name-parameterised dataset controls so one compiled control serves several demos.
• Power Automate flows for approvals, notifications, integrations and as agent tools.
• Copilot Studio agent(s) for the conversational/agentic story, on the GitHub Copilot harness.
• A command-centre dashboard on the home page tying it together: KPI tiles, alerts, click-through into the
  main record.
• A snapshot/reset script so the demo can be re-run cleanly.

═══════════════════════════════════════════════════════════════════════════════
8. WORKFLOW WHEN I ASK FOR SOMETHING
═══════════════════════════════════════════════════════════════════════════════
1. Inspect what exists first — table metadata, current form XML, current flow clientdata, existing bot
   components — and back up anything you're about to mutate.
2. Make the change via dv.py (POST/PATCH), scoped to my solution, idempotently.
3. Publish (targeted PublishXml; entity-scoped for form/view changes).
4. **Verify by reading the row back AND by exercising the behaviour** — not by trusting a 2xx. For flows and
   agents, run a real end-to-end test and check the *values*, not the run status.
5. Save reusable scripts under `scripts/` with ordered, descriptive names (`p0_solution.py`,
   `step9_forms_views.py`, `deploy_webresource.py`, `p32_demoreset.py`). Script order matters — a later
   blanket-rule script can silently undo an earlier narrow fix, so re-run whole sequences, not fragments.
6. On failure, read the actual error response body — Dataverse usually names the exact column or relationship
   it didn't like. Persist the attempted XML/JSON to /tmp for diffing.
7. Never touch the customer's real/pre-existing tables, forms or data without explicit confirmation.

═══════════════════════════════════════════════════════════════════════════════
START HERE
═══════════════════════════════════════════════════════════════════════════════
Ask the discovery questions in §0. Then run `pac auth list` and confirm the target org (`pac auth create` if
not). Then ask what we're building first, and lay out a short phased plan before writing code.


---

<a id="appendix-ai-agents"></a>

### Appendix: Ai Agents

*Originally `reference/ai-agents.md`*

### AI Agents on Copilot Studio / Dataverse — Field Notes from the Workspace

Sources: `agentic-credit/` (HANDOVER.md, BUILD-PLAN.md, BINDING-CHECKLIST.md, `scripts/p5*`–`p76*`), `airline-workshop/reference/copilot-studio-tool-schemas.md`, `meeting-intelligence/scripts/create_agent.py`, `CaseProcessConfigurator/`+`SalesProcessConfigurator/` (`step49`/`step52`/`step53`, `agent_invoke.py`), `market-data-hub`/`market-data-hub-v2` (`deploy_v2_agents.py`, `deploy_foundry_orchestrator.py`), `CRMCopilot/README.md`, `dataverse-generative-ui-demo/README.md`, `scripts/ivr_08_bot_topics.py`.

#### 1. Creating an agent as raw Dataverse rows

`bot` row (verified minimal set, `meeting-intelligence/scripts/create_agent.py`, `scripts/ivr_08_bot_topics.py`):
```
name, schemaname, language: 1033
template: "default-2.1.0"           # classic/Standard harness, generative actions enabled
authenticationmode: 2               # integrated/"authenticate with Microsoft" (1 also seen = "no authentication")
configuration: <JSON, see below>
runtimeprovider: 0
```
`configuration` JSON (the actual bot behavior switches):
```json
{
  "$kind": "BotConfiguration",
  "settings": {"GenerativeActionsEnabled": true},
  "isAgentConnectable": true,
  "gPTSettings": {"$kind":"GPTSettings","defaultSchemaName":"<schema>.gpt.default"},
  "aISettings": {"$kind":"AISettings","useModelKnowledge":true,
                 "isFileAnalysisEnabled":true,"isSemanticSearchEnabled":true,
                 "optInUseLatestModels":false},
  "recognizer": {"$kind":"GenerativeAIRecognizer"}
}
```
`bot.template` is the harness discriminator: `"default-2.1.0"` = **Standard** harness (Copilot Studio classic), `"cliagent-1.0.0"` = **GitHub Copilot harness** (the new Agents/"generative orchestration first" experience). Creating a bot via `bots` API does **not** expose a choice of harness — the GitHub Copilot harness agents in this workspace were all pre-existing/UI-created; nothing in the workspace shows scripting a `cliagent-*` bot into existence.

`botcomponent` numeric `componenttype` codes actually observed:
| componenttype | Meaning (observed) |
|---|---|
| 9 | Dialog-shaped component — **both** Topics (`kind: AdaptiveDialog`) *and* Tools/Actions (`kind: TaskDialog`/`ConnectorTool`/`WorkflowTool`) and **connected (child) agents** live here. Distinguished only by the YAML `kind:`/`action.kind:` inside `data`, not by componenttype. |
| 15 | GPT/instructions ("System instructions" prompt), `data` = `instructions: |+ …` plus `aISettings.model.modelNameHint`. |

Other component fields: `schemaname` must be `<bot schema>.<suffix>` (e.g. `fsi_x.gpt.default`, `fsi_x.action.MicrosoftDataverse-…`); `parentbotid@odata.bind` links it to the bot; `language: 1033`.

#### 2. The Copilot Studio YAML dialect (in `botcomponent.data`)

Topic (classic):
```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent      # or OnConversationStart / OnUnknownIntent / OnError / OnEndOfConversation for system topics
  id: main
  intent:
    displayName: <Topic Name>
    includeInOnSelectIntent: true
    triggerQueries: [<utterances>]
  actions:
    - kind: Question / SendActivity / SetVariable / InvokeFlowAction / SearchAndSummarizeContent / ConditionGroup ...
```
`InvokeFlowAction` binds `flowId` + `input.binding` (Topic./Global. vars) + `output.binding`. `SearchAndSummarizeContent` (grounded knowledge-search action) takes `userInput: =Topic.X` + `additionalInstructions:` prose and searches "connected knowledge sources."

Tools, as verified from live `botcomponent componenttype 9` records (`airline-workshop/reference/copilot-studio-tool-schemas.md`):
- **ConnectorTool** (direct connector call — 5 lines, no flow needed):
```yaml
kind: ConnectorTool
authMode: Invoker
connectionReference: <prefix>.cr.shared_sql
connectorId: /providers/Microsoft.PowerApps/apis/shared_sql
operationId: ExecuteProcedure_V2
```
`connectorId` is mandatory or you get `BotDefinitionOverride has unresolved references`. Old-style `kind: TaskDialog` with `inputs:`/`outputs:`/`action:` is for a **different (older) agent type** and is rejected on ConnectorTool-based agents.

- **WorkflowTool** (Power Automate flow as a tool):
```yaml
kind: WorkflowTool
workflowId: <workflow PRIMARY KEY, NOT workflowidunique>
toolInputs:  [{name: text, displayName: ..., description: ...}]   # names auto-gen text, text_1, text_2...
toolOutputs: [{name: text, displayName: ...}]
connectionProperties: {$kind: ConnectionProperties, mode: Invoker}
```
- **Connected (child) agent** — reverse-engineered, no prior in-org example:
```yaml
kind: TaskDialog
modelDisplayName: Structuring Agent
modelDescription: <routing text — the ONLY thing the orchestrator reads to route>
action:
  kind: InvokeConnectedAgentTaskAction
  botSchemaName: fsi_structuringAgent
  historyType: {kind: ConversationHistory}
```
with `dependencies: [{"type":"bot","schemaName":"<child schema>"}]`, schema name `<parent schema>.InvokeConnectedAgentTaskAction.<ChildNameNoSpaces>`. Tune `modelDescription` first if routing misfires.

- **Dataverse MCP tool** — see §3.

#### 3. MCP: exact working shape, and why scripted MCP tools come out empty

```yaml
kind: TaskDialog
modelDisplayName: Microsoft Dataverse MCP Server (Preview)
modelDescription: Provides Remote MCP Server access to Dataverse with preview tools
action:
  kind: InvokeExternalAgentTaskAction
  connectionReference: <agent schema>.shared_commondataserviceforapps.<connection-guid>
  connectionProperties:
    mode: Invoker            # or Maker — see below
  operationDetails:
    kind: ModelContextProtocolMetadata
    operationId: InvokeMCPPreview
```
Two hard-won facts (`agentic-credit/scripts/p9_mcp.py`):
1. **`operationId` must be `InvokeMCPPreview`, not `InvokeMCP`.** With `InvokeMCP` the row creates/publishes cleanly and shows in the portal but the tool has **"no tools available"** — a silent empty shell. This is the answer to "why scripted MCP components come out empty."
2. **The `connectionReference` is per-agent** — `<agent schema>.shared_commondataserviceforapps.<connection id>` — even though every agent points at the same underlying connection GUID. Sharing one reference across agents does not follow the product's own convention.

`connectionProperties.mode`: **Invoker** runs the MCP call as whoever is chatting to the agent — in the M365 Copilot pane that identity may lack the Dataverse privileges the maker had, so reads **silently come back empty**. **Maker** pins the call to the connection owner's identity. `p48_mcpmaker.py` flips `mode: Invoker` → `mode: Maker` with a regex anchored to the `connectionProperties:` block only (data is a mix of LF/CRLF, naive replace misses half).

Environment/tenant enablement for MCP (from `CRMCopilot/README.md`, `dataverse-generative-ui-demo/README.md`):
- Scope: `mcp.tools` at `https://<org>.crm.dynamics.com/api/mcp/mcp.tools`.
- Power Platform admin must **enable the MCP feature for the environment** and **allow-list the app registration/client ID** — Entra exposes no dynamic client registration, so pre-registration is mandatory.
- Dataverse CLI MCP client ID observed: `0c412cc3-0dd6-449b-987f-05b053db9457` (also seen as custom app `af82c075-d38d-41a2-a846-20f446faf680`, "Dataverse MCP CLI").
- Transports: local proxy (`npx @microsoft/dataverse mcp <org-url>`, works around macOS WAM broker issues) vs direct remote `/api/mcp`.
- Create/update mutations should render an **approval card before executing** — pattern used in `dataverse-generative-ui-demo`.

#### 4. WorkflowTool backing flow — cannot fully register via API

`workflow` Dataverse row: `category: 5` (Modern Flow), `type: 1` (Definition), `statecode: 1`/`statuscode: 2` (Activated), `primaryentity: none`. `clientdata.properties.definition.triggers.manual = {type: Request, kind: Skills}` ("When an agent calls the flow"); response action same `kind: Skills`. Cloud flows as Dataverse rows **bypass** the `service.flow.microsoft.com` consent failure (`AADSTS65002`) that blocks the plain Power Automate REST API.

**Critical defect (14 in HANDOVER.md):** a flow tool cannot be *fully* created through the Dataverse Web API. The `botcomponent` row is only half the registration — Copilot Studio's designer writes an additional binding **outside `botcomponent.data`**. Proof: an API row patched byte-identical to a working UI row still threw `FlowNotFound: The flow with id <guid> was not found in the bot definition` at runtime (visible in the M365 Copilot channel only as the generic "the bot can't talk for a while"). Fix used in this workspace: **re-add all flow tools through the Copilot Studio UI** (automated with Playwright), then patch in the missing `connectionProperties` block via API — necessary but not sufficient alone.

`BINDING-CHECKLIST.md` confirms the same rule generally: **"Tools added to agents through the Dataverse API in this org publish as empty shells that report 'no tools available'"** — the two remaining flow tools had to be added by hand in Copilot Studio UI, no API workaround found.

#### 5. Publishing programmatically

Bound Dataverse action, works reliably and fast (~30s for 11 agents):
```
POST /api/data/v9.2/bots(<botid>)/Microsoft.Dynamics.CRM.PvaPublish   body {}
```
Verify via `publishedon` on the `bot` row, **not** the portal grid — the agent-list grid caches stale "Draft" for several minutes after a real publish.

CLI alternative (`pac copilot publish`): flag is `--bot` (not `--schemaName`) and wants the **bot GUID** — schema name is documented as acceptable but returned `Copilot with ID '...' not found` in practice.
```bash
pac copilot publish --environment <env-guid> --bot <bot-guid>
```

**Pre-publish validation gotcha (Defect 13):** actions created via `botcomponent` default their inputs to `kind: ManualTaskInput` (expects a literal `value:`). With none supplied, publish fails: `Tool Errors (4)` / `MissingRequiredProperty: Missing required property 'Value'`, tool's Inputs panel shows ⚠. **Fix: `kind: AutomaticTaskInput`** (orchestrator fills from context). The Web API accepts/returns the broken definition silently — only the **portal's pre-publish check** surfaces it.

#### 6. Direct-invoke / runtime endpoints (verified live)

**Copilot Studio direct-invoke conversations API** (`CaseProcessConfigurator/agent_invoke.py`):
```
POST https://{HOST}/copilotstudio/dataverse-backed/authenticated/bots/{schemaname}/conversations
POST .../conversations/{conversationId}?api-version=2022-03-01-preview
```
- Body **must be wrapped**: `{"activity": {...}}` — a bare activity returns HTTP 400.
- Host derivation: raw hex of the **environment id** (not org id), dashes stripped, split into first-30-chars + last-2-chars: `f"{h[:-2]}.{h[-2:]}.environment.api.powerplatform.com"`.
- Scope: `https://api.powerplatform.com/CopilotStudio.Copilots.Invoke`.
- Access: the calling identity must be **shared on the `bot` record**, else the reply is HTTP 200 with a trace activity `ErrorCode=AccessToBotDenied` — a silent-looking success that must be caught by inspecting the activity trace, not the status code.

**Copilot Studio environment id ≠ Dataverse org id.** Using the org id in a `copilotstudio.microsoft.com/environments/<id>/…` URL silently redirects to the tenant default environment — a completely different tenant's content.

#### 7. Standard harness vs GitHub Copilot harness — the routing fork

`CaseProcessConfigurator/step49_agent_flow.py` and `step52_hybrid_test.py` document a production Power Automate flow that forks based on harness because **each is reachable through a different connector**:
| Harness | `bot.template` | Reachable via |
|---|---|---|
| Standard | `default-*` | Copilot Studio connector, `ExecuteCopilotAsyncV2` (`shared_microsoftcopilotstudio`) |
| GitHub Copilot | `cliagent-*` | Agent-node connector, `InvokeAgent` (`shared_agentnode`) — same connector the Copilot Studio workflow "Agent node" uses internally |

**The dangerous failure mode:** calling a `cliagent-*` agent through the Standard `ExecuteCopilotAsyncV2` route does **not** fail loudly. The agent answers with the literal string *"This action doesn't support agents built with the GitHub Copilot harness"* **as its own reply**, the connector reports success, the run is green, and that refusal string gets written onto downstream records (task notes, etc.) as if it were a real agent finding. The Entra direct-invoke conversations API gives the same silent refusal. Only an end-to-end functional test (not a green flow run) catches this — `step52_hybrid_test.py` asserts on `REFUSAL = "doesn't support agents built with the github copilot harness"` substring as its canary.

Practical rule embedded in flows: check `bot.template` string prefix at runtime/design-time and branch; never assume "published" implies "reachable the way you expect."

Generative orchestration (parent → connected-child delegation) is a **toggle**, not a rebuild: **Settings → Generative AI → Generative orchestration** on the parent agent + republish. Connected agents normally *require* this for automatic delegation — on Standard orchestration the parent may just answer itself instead of handing off (observed and deliberately left this way in agentic-credit).

#### 8. Azure AI Foundry agents (market-data-hub-v2 `deploy_foundry_orchestrator.py`)

- Two Foundry "Agents API" surfaces exist: legacy `/assistants`, and the new **Agents API** (`api-version=v1`, exposes agent versioning) — `PUT /agents/{name}`, `POST /agents/{name}/versions`.
- Model-vs-transport quirks (verified against a specific Foundry account, 2026-09-07): `gpt-6-astra` **500s on Agents Service** for even trivial prompts, but works fine on **direct chat completions**; `gpt-4.1`/`gpt-5-mini` work on Agents Service. `gpt-6-astra` also **rejects `reasoning.effort` and the `web_search_preview` tool**.
- Structured output support differs by model: `gpt-6-astra` supports `response_format: json_object` (valid JSON, not exact shape) but **not** `json_schema`/`strict`; `gpt-5.6-sol` and `gpt-4.1` support strict `json_schema` on the Agents API.
- **Strict `json_schema` requires `additionalProperties: false` on every object AND every property listed in `required`** (no true optionality — express optional fields as nullable types instead). A recursive `walk()` helper auto-derives the strict variant from a lenient schema.
- Invocation goes through the **project-scoped** `/openai/v1/responses` endpoint (`https://{account}.services.ai.azure.com/api/projects/{project}/openai/v1/responses`) — the same path directly under the account host (no project segment) does **not** resolve agent references.
- Explicitly pass `"tools": []` — project defaults can otherwise silently inject `web_search_preview`, which some models reject outright.
- Auth scope: `https://ai.azure.com/.default`.
- Design pattern: keep the LLM **stateless with no tools** for a pure JSON-fan-in synthesizer (no need for Agent Service threads/tool-calling machinery) — call it directly from chat completions and mirror that call from a Power Automate HTTP action so both paths stay in lockstep.
- Anti-hallucination pattern in the schema itself: every "modelled/estimated" numeric field carries a sibling `"basis": {"enum":["modelled"]}` flag so the UI can visibly badge inferred numbers, and a validation script asserts `coverage=="none"` and no invented wallet numbers when input data is empty (fail-closed, not fail-plausible).

#### 9. MCP-as-a-data-source for orchestration (market-data hub)

- Each of 6 parallel Copilot Studio specialist agents queries the **market-data MCP connector** independently, each writing its own result row (`envelope`, tools actually called, evidence count).
- **Silent-degrade gotcha:** the market-data OAuth refresh token expires periodically → connection state `Unauthorized`/`invalid_grant`. When Copilot Studio can't enumerate MCP tools, **the planner quietly falls back to the built-in `UniversalSearchTool`**, returning `{"search_result": null}` in ~60ms, and the flow still writes `status = Completed` — **a green status with an empty report**. Diagnose by inspecting the run's `DynamicPlanReceived → value.steps`: healthy shows `MCP:<agent>.action.MARKETDATA-...:<tool>`; broken shows `P:UniversalSearchTool`.
- `PublishAllXml` frequently times out on large solutions — use targeted `PublishXml` with the specific web-resource GUID instead.

#### 10. Instructions / prompt-engineering lessons for tool-calling agents (agentic-credit defects 29–35, 15–28)

- **The orchestrator's completion/auto-fill behaviour beats instruction text.** If an agent keeps asking the user for an optional input despite "never ask" instructions, the fix is **unbinding the input in the tool schema**, not more prompt wording (defect 29). Verify a literal terminal default exists before unbinding, so no real computed value is silently discarded.
- **Producer/consumer output↔input name mismatches look identical to the unbind bug** but are the wrong fix target — rename the consuming tool's input to match the producer's output name (defect 30).
- **`AutomaticTaskInput` handles JSON `number` but silently fails on `integer`** — retype every integer trigger input to `number`, wrap with `int()` server-side for Dataverse Whole Number columns (defect 16). Watch for double-wrapping `int(coalesce(int(X),0))` which throws on null.
- Power Automate expression-library gotchas that produce **silently wrong numbers, not errors**: `div()` does integer division when both operands are ints (wrap the numerator in `float()`); `abs()` **does not exist** in Power Automate (`if(less(X,0),mul(X,-1),X)` instead) — an unknown function is not rejected at save time, only throws at runtime as a generic `BadGateway`. `toLower()` throws on a non-string; canonicalize with `toLower(trim(coalesce(string(...),'')))`.
- Copilot Studio sends **only the trigger inputs the model actually filled** — `triggerBody()['x']` on an omitted optional input hard-fails; always `coalesce(triggerBody()?['x'], default)`.
- `UpdateRecord` (PATCH) **upserts** — an update flow keyed on an id the agent cannot know for a "cold" record will silently *create* an orphan row carrying that GUID. Use find-or-create keyed on a natural id instead.
- **"A green run is not evidence of a correct number."** Integer division, stale option-set/gate mapping, and currency-unit mismatches (USD amount tested against AED thresholds) all returned HTTP 200 with a confidently wrong narrated answer.
- Diagnostic order for a broken flow tool: (1) Copilot Studio **test pane** — names the exact flow GUID and failure (the M365 Copilot channel does not); (2) Power Automate **28-day run history** on the flow (the Dataverse `flowruns` table only logs *scheduled* runs, useless here); (3) build one reference tool **by hand in the UI** and diff.

#### 11. Knowledge sources

Confirmed action available in the classic YAML dialect: `kind: SearchAndSummarizeContent` with `userInput:` + `additionalInstructions:` searching "connected knowledge sources (Dataverse knowledge articles)". UI path noted (`airline-workshop/portal/labs_new.py`): Add-knowledge dialog offers **public website / SharePoint site / file upload** — file-upload path was the one actually used in that lab ("you want the file upload area, not a website or SharePoint site"). No workspace evidence of scripting knowledge-source `botcomponent` rows via API — treated as a UI-only step everywhere it appears (verify).

#### 12. Cross-cutting architectural lesson (agentic-credit's core thesis)

"A Copilot Studio agent cannot paint the Dynamics UI." The reliable pattern used throughout: agent → deterministic Power Automate flow (all math) → agent writes typed rows to app tables → a polling web resource (Xrm.WebApi or raw `fetch` to `/api/data/v9.2/<singular-logical-name>`, **not** the plural collection name) repaints the form every few seconds. **The LLM never does arithmetic** — every number is independently reproduced from a transpiled copy of the flow logic (`p3_verify.py`) and asserted against a reference calc engine, closing the credibility gap for a regulated-industry demo. Tools should be **typed and single-purpose** ("write one shape to one table") rather than a generic "write any row" action, and option-set string→integer mapping should happen **inside the flow**, never trusted to the model.


---

<a id="appendix-forms-schema-apps"></a>

### Appendix: Forms Schema Apps

*Originally `reference/forms-schema-apps.md`*

### Dataverse / Model-Driven App Technical Learnings — Field-Mined Briefing

Sources: `CaseProcessConfigurator/{dv.py,step2..21}.py`, `SalesProcessConfigurator/*` (near-identical sibling), `agentic-credit/scripts/{dvx.py,p0_solution.py,p4_ui.py,p4_app.py,p4b_wireapp.py,p32_demoreset.py}`, `corporate-lending/webresources/fsi_corporatelending.js`, `fsi-client-360/scripts/fix-form*.js`, `Bind-PCF-Surgical.ps1`.

#### 1. Auth & call plumbing (reusable helper pattern)
Every project reinvents the same thin Web API client instead of using the SDK:
```python
h = {"Authorization": "Bearer "+token(), "Accept":"application/json",
     "OData-MaxVersion":"4.0", "OData-Version":"4.0"}
if solution: h["MSCRM.SolutionUniqueName"] = SOLUTION   # scopes metadata writes to a solution
```
- Token via `az account get-access-token --resource <org> -o json`; cache and trust the **real expiry**, not request time — a design pass can run ~10 min and a naive TTL 401s mid-flight. Retry once on 401 with a forced refresh (`agentic-credit/scripts/CaseProcessConfigurator/dv.py`).
- `MSCRM.SolutionUniqueName` header is the mechanism that adds newly created components to a specific unmanaged solution automatically (`solution=True` flag threaded through every `post`/`patch`).
- Metadata POSTs can exceed client timeouts and still succeed server-side — `dvx.py`'s `_resilient()` wraps every table/column/relationship write: on exception, sleep and re-check existence (`EntityDefinitions(LogicalName=...)` GET) before deciding it actually failed. This is a real, recurring trap.
- `find_one(entityset, filt)` and `new_id(resp)` (parses `OData-EntityId`/`_location` header) are the two idiomatic helpers used everywhere for idempotent upsert-by-query.

#### 2. Table & column creation (EntityDefinitions)
Minimal entity body actually used in production scripts:
```json
{
 "@odata.type": "Microsoft.Dynamics.CRM.EntityMetadata",
 "SchemaName": "cpc_caseprocesstemplate", "LogicalName": "cpc_caseprocesstemplate",
 "DisplayName": {label}, "DisplayCollectionName": {label}, "Description": {label},
 "OwnershipType": "UserOwned", "IsActivity": false, "HasNotes": true, "HasActivities": false,
 "Attributes": [{
   "@odata.type": "Microsoft.Dynamics.CRM.StringAttributeMetadata",
   "SchemaName": "cpc_name", "LogicalName": "cpc_name",
   "DisplayName": {label}, "IsPrimaryName": true,
   "RequiredLevel": {"Value":"ApplicationRequired"},
   "MaxLength": 200, "FormatName": {"Value":"Text"}
 }]
}
```
- **SchemaName == LogicalName** is set explicitly and identically everywhere (lowercase prefix); Dataverse lower-cases LogicalName regardless, so scripts pre-lowercase to make idempotency-checks (`GET EntityDefinitions(LogicalName='...')`) match on first try.
- Primary name attribute doesn't need `PrimaryNameAttribute` on the entity body if the single seed attribute has `IsPrimaryName: true` — Dataverse infers it. `dvx.py`'s variant explicitly sets `"PrimaryNameAttribute": primary_schema.lower()` too (belt-and-braces).
- Label helper used everywhere:
```python
def label(text, lcid=1033):
    return {"@odata.type":"Microsoft.Dynamics.CRM.Label",
            "LocalizedLabels":[{"@odata.type":"Microsoft.Dynamics.CRM.LocalizedLabel","Label":text,"LanguageCode":lcid}]}
```
- Column `@odata.type` per kind (all confirmed live):
  - String: `StringAttributeMetadata` + `MaxLength` + `FormatName:{Value:"Text"|"Url"}`
  - Memo: `MemoAttributeMetadata` + `MaxLength` + `Format:"TextArea"`
  - Integer: `IntegerAttributeMetadata` + `MinValue`/`MaxValue` + `Format:"None"`
  - Decimal: `DecimalAttributeMetadata` + `Precision`, `MinValue`, `MaxValue`
  - Money: `MoneyAttributeMetadata` + `Precision` + `PrecisionSource:2` (uses currency precision, not a fixed value)
  - Boolean: `BooleanAttributeMetadata` + nested `OptionSet:{"@odata.type":"BooleanOptionSetMetadata","TrueOption":{Value:1,Label},"FalseOption":{Value:0,Label}}`
  - DateTime: `DateTimeAttributeMetadata` + `Format:"DateAndTime"|"DateOnly"` + `DateTimeBehavior:{Value:"UserLocal"}`
  - Local choice/picklist: `PicklistAttributeMetadata` + `OptionSet:{"@odata.type":"OptionSetMetadata","OptionSetType":"Picklist","IsGlobal":false,"Name":"<entity>_<field>","DisplayName":label,"Options":[{Value,Label}...]}` — **Name is required even for a local option set** and by convention is `{entity_logical}_{column_name}`.
  - `DefaultFormValue` on the attribute (not the option set) sets the default selection.
- Idempotency pattern used by every step script: `try: GET EntityDefinitions(...)/Attributes(LogicalName=...) ; except RuntimeError: create`. `dv.get`/`dv.call` raises `RuntimeError` on any non-2xx, so a 404 is caught the same way as any other error — fine here because "doesn't exist" is the only expected failure mode at this stage.
- `dv.publish_all()` → `POST PublishAllXml` with empty body `{}` is called once at the end of every step, not per-object; per-object publish is reserved for form/view edits that must be visible before the next step reads them.

#### 3. Relationships / lookups
`RelationshipDefinitions` POST for 1:N (this is literally how a lookup column is created — there is no separate "create lookup attribute" message):
```json
{
 "@odata.type": "Microsoft.Dynamics.CRM.OneToManyRelationshipMetadata",
 "SchemaName": "cpc_caseprocesstemplate_matchrule_template",
 "ReferencedEntity": "cpc_caseprocesstemplate",
 "ReferencingEntity": "cpc_matchrule",
 "CascadeConfiguration": {"Assign":"NoCascade","Delete":"RemoveLink","Merge":"NoCascade",
                           "Reparent":"NoCascade","Share":"NoCascade","Unshare":"NoCascade"},
 "Lookup": {"@odata.type":"Microsoft.Dynamics.CRM.LookupAttributeMetadata",
            "SchemaName":"cpc_template","LogicalName":"cpc_template",
            "DisplayName": {label}, "RequiredLevel": {"Value":"ApplicationRequired"}},
 "AssociatedMenuConfiguration": {"Behavior":"UseCollectionName","Group":"Details","Order":10000,"IsCustomizable":true}
}
```
- `SchemaName` for the relationship is truncated to 100 chars in code (`rel[:100]`) — Dataverse silently rejects longer schema names; this was clearly hit and hardened for.
- Cascade config default is all `NoCascade`/`RemoveLink`; the CPC script explicitly upgrades `Delete` to `Cascade` only for parent-child pairs that are both custom tables and where the suffix is `template`/`package` (deleting a template cascades its match rules and tasks; deleting a package cascades its items) — a deliberate, narrow whitelist rather than a blanket cascade.
- Existence check for a lookup is done via `Attributes(LogicalName='<lookup>')` on the **referencing** entity, exactly like a normal column — confirms lookups are just attributes from the read side.
- `RelationshipName`/`ReferencingEntityNavigationPropertyName` for subgrids and `@odata.bind` is looked up **after the fact** by scanning `ManyToOneRelationships` and matching on `ReferencingAttribute`:
```python
r = dv.get(f"EntityDefinitions(LogicalName='{referencing}')/ManyToOneRelationships"
           f"?$select=SchemaName,ReferencingAttribute")["value"]
```
This SchemaName is what's placed in a subgrid's `<RelationshipName>` form-XML parameter and in an `@odata.bind` on create — scripts never hardcode it; they always resolve it live because the schema name Dataverse assigns can differ from what was requested if there was a naming collision.

#### 4. Form XML editing (surgical, not maker UI)
Full custom forms are built programmatically from Python string templates (`CaseProcessConfigurator/step9_forms_views.py`), not exported/re-imported. Key control classids hardcoded and reused across every project in this workspace:
```
String/Uniqueidentifier : {4273EDBD-AC1D-40D3-9FB2-095C621B552D}
Memo                    : {E0DECE4B-6FC8-4A8F-A065-082708572369}
Integer                 : {C6D124CA-7EDA-4A60-AEA9-7FB8D318B68F}
Decimal/Double          : {C3EFE0C3-0EC6-42BE-8349-CBD9079DFD8E}
Money                   : {533B9E00-756B-4312-95A0-DC888637AC78}
Picklist/Status         : {3EF39988-22BB-4F0B-BBBE-64B5A3748AEE}
State                   : {5D68B988-0661-4DB2-BC3E-17598AD3BE6C}
Boolean                 : {B0C6723A-8503-4FD7-BB28-C8A06AC933C2}  (also seen as {67FAC785-CD58-4F9F-ABB3-4B7DDC6ED5ED} in BPF designer XAML)
DateTime                : {5B773807-9FB2-42DB-97C3-7A91EFF8ADFF}
Lookup/Customer/Owner   : {270BD3DB-D9AF-4782-9025-509E298DEC0A}
Subgrid                 : {E7A81278-8635-4D9E-8D4D-59480B391C5B}
Web resource / iframe   : {9FDF5F91-88B1-47f4-AD53-C11EFC01A01D}
```
- Every tab/section/cell/control emits a fresh `{uuid.uuid4()}` — **GUID uniqueness across a form is load-bearing**; reusing an id (e.g. copy-pasted section) causes silent designer corruption or "form contains errors" on next maker-UI open.
- Minimum valid `<form>` skeleton used to create a brand-new systemform-like body:
```xml
<form><tabs>...</tabs>
  <header id="{guid}" columns="111"><rows /></header>
  <footer id="{guid}" columns="111"><rows /></footer>
</form>
```
- Cell for a bound field: `<cell id="{guid}" showlabel="true" locklevel="0"><labels>...</labels><control id="<fieldlogicalname>" classid="<classid>" datafieldname="<fieldlogicalname>" disabled="false" /></cell>` — note `control id` equals the field logical name by convention (must be unique per form, and matches the field so form scripts can `getControl(fieldname)`).
- Subgrid cell requires `RelationshipName`, `TargetEntityType`, `ViewId` (a real `savedqueryid` wrapped in braces) as `<parameters>` — views must be created/patched **before** forms that embed them as subgrids, hence the explicit ordering comment "views first (needed by subgrids)" in step9.
- **Safe surgical edit of an OOB form** (`step10_case_form.py` splicing a tab into stock "Case"/"Case for Interactive experience"/"Case for Multisession experience" forms):
  1. GET `systemforms?$filter=objecttypecode eq 'incident' and type eq 2` (type 2 = Main form).
  2. Tag the injected tab's `name` attribute with a project-specific marker prefix (`cpc_processtab_...`).
  3. Idempotent re-run: regex-strip any existing tagged tab (`<tab name="cpc_processtab_.*?</tab>`) before re-inserting, so the script can be run repeatedly without duplicate tabs.
  4. Insert right before `</tabs>` via string slicing (`formxml.rindex("</tabs>")`), never full XML re-parse/re-serialize — avoids attribute-order/whitespace churn that could break form-designer diffing.
  5. `dv.patch(systemforms(id), {"formxml": xml}, solution=True)` then one `dv.publish_all()` at the very end (batched across all target forms), not per form.
- Splicing into an **existing** section/tab (not appending a whole new tab) is done with regex bounded to `<section name="X">...</section>` / `<tab name="X">...</tab>`, locating `</rows>` and inserting new `<row>` blocks just before it (`step18_case_widgets.py`). Also demonstrates removing OOB fields and any section left with empty `<rows/>` or `<rows></rows>` afterward, to avoid orphaned blank sections.
- **Idempotent field/section removal helper pattern** (regex, not XML DOM):
```python
tab = re.sub(rf'<row>(?:(?!</row>).)*?datafieldname="{field}"(?:(?!</row>).)*?</row>', "", tab, flags=re.S)
```
This non-greedy negative-lookahead pattern is the standard trick used repeatedly to remove a `<row>` containing a specific field/section without a full XML parser, tolerant of arbitrary nested attribute XML inside the row.
- Backups before any live formxml PATCH are standard practice: `corporate-lending/tmp/opp_form_orig.xml`, `CaseProcessConfigurator/backup-caseform-20260904-1015.xml`, `corporate-lending/backups/collab-preC-*` — always fetch and persist the full `formxml` string to disk before any patch, so a bad splice can be reverted verbatim.

#### 5. PCF binding via `<controlDescriptions>` (not the maker UI)
`Bind-PCF-Surgical.ps1` and `fsi-client-360/scripts/fix-form*.js` show the actual mechanics of binding a PCF control to a field/view by raw XML edit, with heavy trial/error on parameter typing:
```xml
<controlDescriptions>
  <controlDescription forControl="con_name">
    <customControl name="Coverage.CoverageNoteHeroCard" formFactor="2">
      <parameters><noteTitle>con_name</noteTitle>...</parameters>
    </customControl>
    <customControl name="Coverage.CoverageNoteHeroCard" formFactor="0">...</customControl>
    <customControl name="Coverage.CoverageNoteHeroCard" formFactor="1">...</customControl>
  </controlDescription>
</controlDescriptions>
```
- `formFactor` 0/1/2 = Desktop/Phone/Tablet — all three must be present or the PCF silently doesn't render on some clients.
- `controlDescriptions` block goes **before** `</form>`, sibling to `<tabs>`, never inside a tab.
- Prior block must be stripped by regex (`<controlDescriptions>[\s\S]*?</controlDescriptions>`) before re-inserting — repeated binding attempts otherwise accumulate duplicate blocks.
- View-level PCF (gallery control) binds the same way but inside `layoutxml` before `</grid>`, with `forControl=""` (whole-grid control, not one column).
- `fsi-client-360/scripts/fix-form2.js` is a live record of **guessing the `boundField`/`accentColor` parameter type attribute** (`type="multiple"` vs `"Multiple"` vs `"SingleLineOfText"` vs `"SingleLine.Text"` vs omitted) — none of these are documented reliably; the working recipe had to be brute-forced variant by variant and the failing ones logged (verify exact required casing per PCF property type before reuse — it's control-manifest-dependent, not a universal Dataverse rule).
- Publish after any formxml/layoutxml change is scoped to the entity, not global: `PublishXml` with `<importexportxml><entities><entity>{entity}</entity></entities></importexportxml>`.

#### 6. Views (savedquery)
```python
fetch = f'<fetch version="1.0" output-format="xml-platform" mapping="logical" no-lock="false">' \
        f'<entity name="{entity}"><attribute name="{entity}id" />{attrs}{order}{filter}</entity></fetch>'
layout = f'<grid name="resultset" object="1" jump="{columns[0]}" select="1" icon="1" preview="1">' \
         f'<row name="result" id="{entity}id">{cells}</row></grid>'
```
- Default active-record filter used everywhere when none specified: `<filter type="and"><condition attribute="statecode" operator="eq" value="0" /></filter>`.
- Views are located and patched by `(returnedtypecode, name)` pair — **never create new savedqueries for a system view**, always find the existing one from the entity's default view set and PATCH `fetchxml`+`layoutxml` together (never one without the other, or the grid columns and fetch attributes desync).
- `querytype` values referenced: `0` = public/Main saved view (used in `fsi-client-360`/`Bind-PCF-Surgical.ps1` filters `querytype eq 0`).
- `view_id()` helper returns a `{guid}` string (braces included) because that's the literal format the subgrid `<ViewId>` parameter expects.

#### 7. Business Process Flows — no supported "create BPF" API
`bpfgen.py`'s docstring nails the core gotcha: **Dataverse exposes no supported message to create a BPF.** A BPF is a `workflow` row with `category: 4`, and it requires **both** a `clientdata` JSON blob **and** an `xaml` blob describing the same stage/step plan — POSTing category-4 without `xaml` fails with `0x80040203` ("workflowstep"). The script builds both from one shared numbered plan (`_plan()`) so stage/step ids/guids never drift between the two representations.
```python
dv.post("workflows", {
  "workflowid": wid, "name": name, "uniquename": unique, "description": description,
  "category": 4, "type": 1, "mode": 0, "scope": 4,
  "primaryentity": entity, "ondemand": False, "istransacted": True,
  "businessprocesstype": 0, "languagecode": 1033,
  "clientdata": _clientdata(...), "xaml": _xaml(...),
})
```
Then explicitly activate: `PATCH workflows(id) {"statecode":1,"statuscode":2}` — created BPFs are Draft by default and inert until activated.
- Reading `processstages` after creation resolves real stage GUIDs: `GET processstages?$filter=_processid_value eq {workflowid}`.
- **A BPF is invisible on a form unless it's also a component of the model-driven app the form is opened in** — a separate step (`step21_app_bpf.py`) explicitly adds the workflow (`componenttype 29`(verify) / `@odata.type: Microsoft.Dynamics.CRM.workflow`) via `AddAppComponents` to every app where the entity is worked, and verifies each app individually afterward because `appmodulecomponents` collections are large enough that a broad retrieve can silently miss just-added rows (must re-query per-component-id, not rely on a full list fetch).
- `stagecategory` option values assumed stable across orgs: `qualify=0, develop=1, propose=2, close=3, identify=4, research=5, resolve=6`.

#### 8. Model-driven app + sitemap
Minimal appmodule body:
```json
{"name": APP_NAME, "uniquename": APP_UNIQUE, "clienttype": 4,
 "webresourceid": <icon-webresourceid>, "navigationtype": 0}
```
- `navigationtype: 0` = classic single-session shell; `1` = multi-session (Customer Service Workspace-style) — explicitly avoided in CPC because "its session/tab rail eats vertical space we want for the designer canvas" — a real, documented design tradeoff.
- Custom SVG app icon uploaded as a webresource of `webresourcetype: 11` (SVG), name convention `<prefix>_/icons/<name>.svg`, base64-encoded content, then referenced via `appmodules.webresourceid`.
- Sitemap upsert pattern: `sitemaps` row keyed by `sitemapname`; SiteMap XML root `<SiteMap IntroducedVersion="9.0">` (or `"7.0.0.0"` seen elsewhere — inconsistent across projects, doesn't seem to matter (verify)); `Area`/`Group`/`SubArea` all need unique `Id`, `SubArea` needs `Client="All,Outlook,OutlookLaptopClient,OutlookWorkstationClient,Web"` and `Entity="<logicalname>"`.
- `AddAppComponents` payload: `{"AppId": appid, "Components":[{"@odata.type":"Microsoft.Dynamics.CRM.sitemap","sitemapid":...},{"@odata.type":"Microsoft.Dynamics.CRM.entity","entityid": <EntityDefinitions MetadataId>}, ...]}` — entity components are referenced by **MetadataId**, not LogicalName, resolved via `GET EntityDefinitions(LogicalName='x')?$select=MetadataId`.
- **Sharp trap found in production (`p4b_wireapp.py`):** `AddAppComponents`'s `Components` collection is typed `Collection(mscrm.crmbaseentity)`. Passing an entity-metadata id there resolves it as a record in the literal `entity` **table**, not entity metadata — it returns HTTP 200 but registers a junk/no-op component. The workaround used: skip `AddAppComponents` for tables entirely and drive app entity exposure purely through the sitemap's `SubArea Entity="..."` references, which is what actually governs app navigation. Verified live in browser.
- Alternate low-level path: `appmodulecomponents` entity directly, with `appmoduleidunique@odata.bind` + `objectid` (raw GUID, not MetadataId for forms/views) + `componenttype` codes seen: sitemap `62`, entity `1`, systemform `60`, workflow (BPF) `29`(verify).
- **`POST /appmodules` can be broken/non-atomic on some orgs**: `p4b_wireapp.py` documents a case where the app row is created, then the same call throws "Entity 'appmodule' With Id = X Does Not Exist" and the new app becomes invisible to retrieve-multiple — recovery was to create the app once by hand in make.powerapps.com, then script everything downstream (sitemap swap, component registration, publish) against the known appmoduleid.
- `ValidateApp` (`POST ValidateApp {"AppModuleId": id}`) is called after publish to sanity-check the built app and surface a JSON `AppValidationResponse`.
- Publish scoped to the app + sitemap only: `PublishXml` with `<importexportxml><appmodules><appmodule>{id}</appmodule></appmodules><sitemaps><sitemap>{id}</sitemap></sitemaps></importexportxml>`.
- Publish lock/backoff pattern seen: retry loop catching `0x80071151` or HTTP 429, sleeping 20s, up to 6 attempts.

#### 9. Command bar / ribbon — actually NOT used
Across `corporate-lending/pkg/repo/src/customizations.xml` every entity's `<RibbonDiffXml>` is an **empty stub** (`<CustomActions/>`, `<Templates><RibbonTemplates Id="Mscrm.Templates"/></Templates>`, `<CommandDefinitions/>`). None of the surveyed projects author ribbon buttons via RibbonDiffXml. Instead, "command"-like actions are wired as:
- Form OnLoad-registered JS functions exposed as a public object (`fsi_corporatelending.js` IIFE returning `{convertInsightToOpportunity, generateCreditMemo, toggleHeader, ...}`), invoked from **embedded web-resource iframe buttons**, not native command bar buttons.
- The **header collapse pattern** actually implemented (`fsi_corporatelending.js`):
```js
function toggleHeader(ctx) {
  const fc = ctx.getFormContext();
  const ui = fc.ui;
  if (ui.headerSection) {
    const cur = ui.headerSection.getBodyVisible ? ui.headerSection.getBodyVisible() : true;
    ui.headerSection.setBodyVisible(!cur);
  }
}
```
Called from a custom button in a web resource, not a ribbon command — `formContext.ui.headerSection.getBodyVisible()/setBodyVisible(bool)` is the real client API for collapsing/expanding the header body while leaving the header bar itself visible.
- Conclusion (mark as a workspace-wide pattern, verify against other orgs): this workspace consistently prefers **form-script + embedded web-resource UI** over RibbonDiffXml/modern command bar for interactive actions, likely because ribbon changes require a full solution publish + designer round-trip that's harder to script/iterate on headlessly.

#### 10. Solution lifecycle
- Publisher+solution creation is minimal and idempotent-checked by `uniquename` first:
```python
body = {'uniquename': SOLUTION, 'friendlyname': 'FSI Agentic Credit', 'version': '1.0.0.0',
        'description': '...', 'publisherid@odata.bind': f'/publishers({PUBLISHER_ID})'}
```
- **Collision-guard pattern before creating a new additive solution** (`p0_solution.py`): hardcode the exact list of new table logical names the project is about to introduce, and abort if any already exists in `EntityDefinitions` (`IsCustomEntity eq true`) — protects against silently colliding with another demo's tables sharing the same publisher prefix (`fsi_`).
- Preflight backup before any change: snapshot existing `systemforms` for the target entity, existing `solutions` list, existing `fsi_` tables, and existing `appmodules` to a timestamped JSON file — a manual "get-ids"/rollback aid rather than an automated revert.
- **Two solutions sharing the same system forms is the real trap called out explicitly**: every downstream form-editing step filters target forms by exact `name` (`"Case for Interactive experience"`, `"Case"`, `"Case for Multisession experience"`) rather than by solution, because system forms (`type eq 2`, main form) are **shared singletons across all solutions on the same entity** — patching them from solution A's script silently mutates what solution B thinks is "its" form. All scripts here explicitly comment "Additive — does not modify any existing form" and instead create a **brand-new named form** (`FORM_NAME = 'Contoso Bank Agentic Credit'`) rather than touching the shared stock form, specifically to sidestep this.
- Solution scoping is done per-call via `MSCRM.SolutionUniqueName` header, not by switching a "current solution" context — every write must pass it explicitly or it lands in Default/Active solution.

#### 11. Data seeding / demo lifecycle at scale
- Bulk create/patch uses raw sequential POST/PATCH via the same thin client (no evidence of `$batch`/`ExecuteMultiple` batching in these scripts; they rely on the `_resilient` retry-on-timeout pattern instead of true batching)(verify if larger seed scripts elsewhere use $batch).
- **Safe, reversible demo-data reset** (`p32_demoreset.py`) is the standout pattern:
  - Hard allowlist of exact table logical names ever touched (`AGENTIC`), explicitly **not** a `startswith('fsi_')` prefix match, with an `assert_safe()` that aborts if the allowlist ever collides with a separately maintained `PROTECTED` set of pre-existing customer tables.
  - Every delete/restore is scoped to one parent record via `_fsi_opportunity_value eq {id}` filter — never table-wide.
  - `reset` refuses to run unless a JSON snapshot exists on disk (or `--force`), so a demo can always be put back.
  - `snapshot` strips system columns before saving (`k.startswith('fsi_') and k != pk`), keeping only writable business columns plus a `__id` for traceability.
  - `restore` re-creates via `POST` with an explicit `@odata.bind` back to the parent (`'fsi_Opportunity@odata.bind': '/opportunities(%s)' % opp`) rather than trying to preserve original GUIDs.
  - Staged partial reset (`--stage N`) via a `STAGE` dict mapping table→phase number, so a demo can be rewound to "just before structuring" etc., not only to fully empty.

#### 12. Misc / smaller facts
- `webresourcetype` codes confirmed in use: `1` = HTML, `3` = JScript, `11` = SVG.
- Label/localized-label boilerplate (`Label`/`LocalizedLabel` `@odata.type`s) is required on **every** DisplayName/Description field, not optional shorthand.
- `RequiredLevel` shorthand seen: `{"Value":"None"|"ApplicationRequired","CanBeChanged":true,"ManagedPropertyLogicalName":"canmodifyrequirementlevelsettings"}` — the managed-property fields are included even on unmanaged/new attributes in the `dvx.py` helper, defensively, though likely unnecessary at create time (verify necessity).
- Global option sets are avoided in all surveyed scripts — every choice column here is local (`IsGlobal: false`) with a per-entity/per-attribute `OptionSet.Name`.


---

<a id="appendix-pcf"></a>

### Appendix: Pcf

*Originally `reference/pcf.md`*

### PCF (Power Apps Component Framework) Controls — Field Notes

Mined from: pcf/ (herocard, CoverageNotesGallery), corporate-lending/pcf (fsiPremiumGrid,
PipelineDealTracker, customer360), fsi-client-360/Solution, CaseProcessConfigurator (Modern SLA Timer),
Bind-PCF-Surgical.ps1, Bind-CoverageTeamNotesPCF.ps1, northwind/fabrikam customer360 pcf.

#### 1. Project layout & toolchain

- Standard `pac pcf init` layout: `<name>.pcfproj` at the PCF folder root + a subfolder named after the
  constructor containing `ControlManifest.Input.xml` and `index.ts`.
- `.pcfproj` is an MSBuild project targeting **net462** (`TargetFramework=net462`) using
  `Microsoft.PowerApps.MSBuild.Pcf` (`Version="1.*"`) + `Microsoft.NETFramework.ReferenceAssemblies`.
  This is unrelated to the .NET SDK that `pac` itself needs — don't conflate the two runtimes.
- Solution packaging uses a `.cdsproj` with `Microsoft.PowerApps.MSBuild.Solution` and
  `<SolutionRootPath>src</SolutionRootPath>`; it references the PCF project, so building the `.cdsproj`
  emits the packaged zip under `bin/<Config>/`.
- npm toolchain: `pcf-scripts` / `pcf-start` (`build`, `clean`, `rebuild`, `start`, `start:watch`,
  `refreshTypes`), TypeScript ^5.8, `@types/powerapps-component-framework ^1.3.x`.

##### macOS toolchain chain (documented in setup.sh)
1. Homebrew
2. **.NET SDK** required by `pac` — installed via `brew install --cask dotnet-sdk` or
   `dotnet-install.sh --channel <ver> --install-dir "$HOME/.dotnet"`, with `$HOME/.dotnet` prepended to PATH
   and persisted to `.zshrc`.
3. `pac` CLI installed only after verifying the SDK version is actually present
   (`dotnet --list-sdks | grep '^8\.'`) — **do not trust `command -v dotnet`**; a different/older dotnet
   earlier on PATH is the classic cause of pac misbehaving.
   On this machine pac needs the `~/.dotnet` runtime:
   `export DOTNET_ROOT="$HOME/.dotnet"; export PATH="$HOME/.dotnet:$HOME/.dotnet/tools:$PATH"`.
4. Node 20 LTS for PCF authoring (separate from the .NET chain).
5. Python 3 for the Dataverse helper scripts.

If pac is broken and can't be fixed quickly, prefer an HTML web resource for the demo, or import a
pre-built solution zip via the Web API (§5).

#### 2. ControlManifest.Input.xml patterns

**Field-bound control** (`usage="bound"`): one property per field — `OptionSet`, `SingleLine.Text`,
`DateAndTime.DateAndTime`, `Multiple` (memo), exactly one `required="true"` for the field it replaces.
No `feature-usage` needed if it only reads bound values.

**Dataset control**: `<data-set name="notes" display-name-key="Notes"/>` with no columns declared (columns
come from the bound view at runtime) + `<feature-usage><uses-feature name="Utility" required="true"/></feature-usage>`.

**Generic, entity-agnostic dataset control** (the reuse pattern that pays off across demos): one
`<data-set>` plus many `usage="input"` `SingleLine.Text` / `Whole.None` / `Enum` properties whose
`default-value` is a *logical field name* (`default-value="fsi_name"`, `default-value="estimatedclosedate"`).
The control resolves them at runtime via `context.parameters.titleField.raw`, so the SAME compiled control
works across differently shaped entities/environments without a rebuild.

Other manifest facts:
- `Enum` properties use nested `<value name="..." display-name-key="...">token</value>` children.
- **Bump `version` on every manifest/resource change** or Dataverse keeps serving cached control metadata;
  publish + hard refresh alone will not pick it up.
- Keep `<external-service-usage enabled="false">` with no `<domain>` children unless the control really calls
  a third-party endpoint — flipping it to true reclassifies the control as premium.
- `<feature-usage>` is commented out in the scaffold; explicitly uncomment `WebAPI` / `Utility` / `Device.*`
  if you call `context.webAPI`, `context.utils` or `openDatasetItem`.

#### 3. Runtime patterns (index.ts)

- Lifecycle: `init(context, notifyOutputChanged, state, container)` -> cache context/container;
  `updateView(context)` re-renders on every value/dataset refresh; `getOutputs()` returns `{}` for read-only
  display controls; `destroy()` clears `container.innerHTML`.
- Field controls: prefer `prop.formatted` over `prop.raw`
  (`prop.formatted !== undefined ? prop.formatted : String(prop.raw)`) so OptionSet/DateTime render as
  display text, not codes/ISO strings.
- Dataset controls: check `ds.loading`; iterate `ds.sortedRecordIds` / `ds.records[id]`; wrap
  `rec.getFormattedValue(name)` in try/catch (columns can be absent depending on the bound view); page with
  `ds.paging.hasNextPage` + `ds.paging.loadNextPage()`; make rows clickable with
  `ds.openDatasetItem(rec.getNamedReference())`.
- **Prefix-agnostic column resolution**: scan `ds.columns` for a name ending in `_<suffix>` or exactly equal,
  instead of hardcoding the publisher prefix — the same compiled control then works in orgs using `con_`,
  `fsi_`, etc.
- Responsive layouts: `context.mode.trackContainerResize(true)` in `init` to receive
  `allocatedWidth`/`allocatedHeight` updates.
- These controls build raw DOM/innerHTML (no React/Fluent) and escape HTML by hand (`& < > "`). Percentage
  and bubble visuals are plain CSS bars — no charting library bundled. Bundling heavy libs (amCharts) into a
  PCF is possible but inflates the bundle; prefer separate JS web resources for HTML pages.

#### 4. Binding a PCF to a form/view — the "surgical" pattern

The dominant technique in this workspace is **not `pac pcf push`** but direct Web API PATCH of
`systemforms.formxml` / `savedqueries.layoutxml`.

**Field-level binding** — inject before `</form>`, sibling to `<tabs>` (never inside a tab):
```xml
<controlDescriptions>
  <controlDescription forControl="con_name">
    <customControl name="Coverage.CoverageNoteHeroCard" formFactor="0">
      <parameters>
        <noteTitle>con_name</noteTitle>
        <coverageTeam>con_coverageteam</coverageTeam>
      </parameters>
    </customControl>
    <!-- repeat identically for formFactor 1 and 2 -->
  </controlDescription>
</controlDescriptions>
```
`formFactor` 0/1/2 = Web/Tablet/Phone — **all three must be present** or the control silently doesn't render
on some clients.

**View / whole-grid binding**: same block inside `layoutxml` before `</grid>`, with `forControl=""` and
usually empty `<parameters/>`.

**Subgrid-on-form dataset binding** (richest real example — Modern SLA Timer): bind to the subgrid control's
`uniqueid`, not a field name.
```xml
<control id="ModernSlaTimerGrid" classid="{E7A81278-8635-4D9E-8D4D-59480B391C5B}"
         indicationOfSubgrid="true" uniqueid="{GUID}">
```
The matching `<controlDescription forControl="{same uniqueid}">` contains **two** customControl entries:
one keyed by the subgrid's own classid carrying the native subgrid `<parameters>` (ViewId, RelationshipName,
TargetEntityType, paging) as fallback, and one `<customControl name="{prefix}sla.ModernSlaTimerControl">`
per form factor carrying `<data-set name="dataSetGrid_1">` (the dataset name must match the manifest) plus
static params like `<Update_Frequency static="true" type="Enum">10</Update_Frequency>`.

**Safety rules for XML surgery**
- Fetch and persist the current `formxml`/`layoutxml` to disk before any PATCH (verbatim revert).
- Strip any prior `<controlDescriptions>[\s\S]*?</controlDescriptions>` before re-inserting — repeated runs
  otherwise accumulate duplicate blocks.
- Use string slicing / bounded regex, never full XML re-parse + re-serialize (avoids attribute-order and
  whitespace churn that breaks designer diffing).
- Write the attempted XML to `/tmp/*-tried.xml` on failure — the Dataverse error body tells you almost
  nothing about a bad form-XML splice.
- **A PATCH to formxml/layoutxml is invisible until you publish**:
  `POST /PublishXml` with `<importexportxml><entities><entity>{logicalname}</entity></entities></importexportxml>`.
- Parameter type attributes for PCF properties (`type="multiple"` vs `"Multiple"` vs `"SingleLine.Text"` vs
  omitted) are poorly documented and manifest-dependent — expect to brute-force the working variant and log
  failures (verify per control).

#### 5. Deploying when pac is unavailable

Base64 the exported solution zip and POST to `ImportSolution`:
```json
{ "CustomizationFile": "<base64>", "OverwriteUnmanagedCustomizations": true,
  "PublishWorkflows": true, "ImportJobId": "<new-guid>", "HoldingSolution": false,
  "SkipProductUpdateDependencies": true, "ConvertToManaged": false }
```
- Wrap the POST in try/except: it sometimes fails HTTP-wise while the import proceeds server-side. Poll anyway.
- Poll `importjobs({jid})?$select=progress,completedon,startedon` every ~15s (up to ~30 min) until
  `completedon` is set, then GET `importjobs({jid})/data` and scan the result XML for `errorcode="0x..."`
  values that aren't `0x0` — a job can "complete" with failed components.
- Re-query `solutions?$filter=uniquename eq '...'` afterwards to confirm the installed `version` matches.
- Publish/customization operations are environment-wide single-threaded: while any solution import runs, other
  publishes return 429/500 containing "another [Import]" / "solution is currently being imported". Handle this
  centrally in the shared HTTP helper with exponential backoff (`5 * 2**(attempt-1)`, capped 60s), plus
  429/503/504, SQL deadlock 1205 and timeouts.

#### 6. When PCF beats an HTML web resource (evidenced)

- No supported "compact" mode exists for stacked quick-view SLA cards — a dataset PCF bound to a single
  `slakpiinstance` subgrid rendered all KPI instances as compact cards in one control and reclaimed vertical
  form space two stacked quick-view forms couldn't.
- Reuse over rewrite: the same installed PCF was reused across two unrelated entities (Case's
  `slakpiinstance_incident` and Task's `slakpiinstance_task`) by *mirroring task deadlines into real
  `slakpiinstance` rows* rather than authoring a second look-alike widget — "make my data look like the shape
  the PCF already understands" avoids a manifest/version bump entirely.
- Generic dataset PCFs with `usage="input"` field-name parameters are the multi-demo reuse strategy behind the
  Customer360 / PremiumGrid control family shared across Contoso Bank, fsi-client-360, Northwind and Fabrikam variants.


---

<a id="appendix-power-automate"></a>

### Appendix: Power Automate

*Originally `reference/power-automate.md`*

### Power Automate Cloud Flows via Dataverse Web API — Technical Learnings

#### 1. Minimal `workflow` row shape for a modern cloud flow

```json
POST /api/data/v9.2/workflows
Headers: { "MSCRM.SolutionUniqueName": "<SolutionUniqueName>", "Prefer": "return=representation" }
Body:
{
  "name": "Contoso Bank - Credit Approval Teams (V2)",
  "uniquename": "fsi_FABCreditApprovalTeamsV2",
  "description": "...",
  "category": 5,          // 5 = Modern Flow (cloud flow)
  "type": 1,              // 1 = Definition
  "primaryentity": "none",// or the trigger entity logical name for Dataverse triggers
  "statecode": 0,         // 0 = Draft/Off, 1 = Activated
  "statuscode": 1,        // 1 with statecode 0; 2 with statecode 1 (Activated)
  "clientdata": "<JSON-stringified clientdata object, see below>"
}
```
- `category eq 5` is the correct OData filter to find existing cloud flows by name (used for idempotent upsert): `workflows?$filter=name eq '...' and category eq 5`.
- Update existing: `PATCH workflows(<id>)` with the same `MSCRM.SolutionUniqueName` header so it stays solution-aware.
- POST does not return the body by default — you must read `OData-EntityId` from response headers or set `Prefer: return=representation` to get `workflowid` back directly. One helper (`dv.py`) captures `OData-EntityId` as `loc` and returns `{status, entity_id}` when body is empty.
- Activation is a **separate PATCH**: `{"statecode": 1, "statuscode": 2}`. Multiple scripts deliberately create in Draft (`statecode:0/statuscode:1`) first so connections can be wired, then activate. One robust upsert pattern used repeatedly (`agentic-credit/scripts/p36_approvals.py::upsert_flow`):
  ```
  if exists and statecode==1: PATCH -> statecode:0, statuscode:1   # must deactivate before editing clientdata
  PATCH -> clientdata, description
  PATCH -> statecode:1, statuscode:2                                # reactivate
  ```
  **Gotcha (implicit): you generally must turn a flow OFF before PATCHing its `clientdata`**, then turn it back ON — some scripts skip this and rely on Dataverse allowing edits while active, but the safe pattern used across agentic-credit always deactivates first.

#### 2. `clientdata` payload schema (exact shape used everywhere)

```json
{
  "schemaVersion": "1.0.0.0",
  "properties": {
    "connectionReferences": { "<connector-shortname>": { ... } },
    "definition": { /* Logic Apps workflow definition, see below */ }
  }
}
```
- `clientdata` on the `workflow` row must be the **JSON-stringified** version of this whole object (`json.dumps(clientdata)`), not a nested JSON value.
- `properties.connectionReferences` is keyed by the connector's short name (e.g. `shared_commondataserviceforapps`, `shared_teams`, `shared_approvals`), matching the `connectionName` used inside `host` blocks in the definition.

##### Two binding modes for `connectionReferences` — this is the single most important gotcha found:
```json
// Mode A: "embedded" — quick/demo-only, renders but the OLD designer breaks on it (verify: seen described as breaking new designer in comment, but used successfully in several demos)
"shared_commondataserviceforapps": {
  "runtimeSource": "embedded",
  "connection": {},
  "api": { "name": "shared_commondataserviceforapps" }
}

// Mode B: "invoker" + a named Dataverse connectionreference row — the fix; renders correctly in the modern designer and lets connections be managed/shared centrally
"shared_commondataserviceforapps": {
  "runtimeSource": "invoker",
  "connection": { "connectionReferenceLogicalName": "fsi_sharedcommondataserviceforapps_d15df" },
  "api": { "name": "shared_commondataserviceforapps" }
}
```
Direct comment from `corporate-lending/scripts/create_credit_approval_flow_v2.py` (lines 7-8): *"Uses runtimeSource = 'invoker' + named connection references (renders in the new designer; old flow used 'embedded' which broke it)"*. When using `invoker` mode, every `OpenApiConnection`/`OpenApiConnectionWebhook` action must also carry an explicit `"authentication"` block (see §5) — trigger and action both need it.

- A third pattern for "zero-connector" pure-calculation flows: `connectionReferences: {}` (empty object) — used for the 7 deterministic credit-calc flows in agentic-credit that only do arithmetic with workflow expressions, no connectors at all.

#### 3. `connectionreference` Dataverse row — creating/binding

```json
POST /api/data/v9.2/connectionreferences
Headers: { "MSCRM.SolutionUniqueName": "<Solution>", "Prefer": "return=representation" }
Body:
{
  "connectionreferencedisplayname": "FSI Agentic Credit Approvals",
  "connectionreferencelogicalname": "fsi_agenticcreditapprovals",
  "connectorid": "/providers/Microsoft.PowerApps/apis/shared_approvals",
  "connectionid": "<the actual PowerApps connection GUID/name string>"
}
```
- Lookup existing: `connectionreferences?$select=connectionreferenceid,connectionid&$filter=connectionreferencelogicalname eq '<name>'`
- Repoint (idempotent) pattern: if row exists but `connectionid` differs, `PATCH connectionreferences(<id>)` with `{"connectionid": conn_name}`; else create with the body above.
- **Finding a live connection to bind:** query the PowerApps Connections API directly (not Dataverse):
  ```
  GET https://api.powerapps.com/providers/Microsoft.PowerApps/connections?api-version=2020-06-01&$filter=environment eq '<envId>'
  Authorization: Bearer <token for https://api.powerapps.com>
  ```
  Filter candidates by: `properties.apiId` ends with the connector shortname (e.g. `shared_approvals`), `properties.statuses[].status == 'Connected'`, and `properties.createdBy.email` matches the intended owner; sort by `createdTime` and pick newest. This is how automated scripts pick "the Approvals connection owned by the approver" without any manual UI step.

#### 4. Trigger patterns

##### Dataverse trigger (row created/modified/deleted)
```json
"When_a_row_is_added_modified_or_deleted": {
  "type": "OpenApiConnectionWebhook",
  "inputs": {
    "host": {
      "connectionName": "shared_commondataserviceforapps",
      "operationId": "SubscribeWebhookTrigger",
      "apiId": "/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps"
    },
    "parameters": {
      "subscriptionRequest/message": 3,           // 1=Create, 2=Delete(?), 3=Update — verify exact enum; 1 used for Create elsewhere
      "subscriptionRequest/entityname": "fsi_creditapproval",
      "subscriptionRequest/scope": 4,              // 4 = Organization
      "subscriptionRequest/filteringattributes": "fsi_teamsapprovalstatus",
      "subscriptionRequest/filterexpression": "fsi_teamsapprovalstatus eq 100000001"  // (optional, more precise gating than conditions[])
    },
    "authentication": { "type": "Raw", "value": "@json(decodeBase64(triggerOutputs().headers['X-MS-APIM-Tokens']))['$ConnectionKey']" }
  },
  "conditions": [ { "expression": "@equals(triggerOutputs()?['body/fsi_teamsapprovalstatus'], 100000001)" } ]
}
```
- `subscriptionRequest/message: 1` used elsewhere for **Create** trigger (`agentic-credit/p36_approvals.py`, gate table trigger).
- Two filtering styles seen: (a) `conditions[]` block on the trigger itself (older/simpler), (b) `subscriptionRequest/filterexpression` OData-style filter (more precise, avoids extra runs). Prefer (b) for invoker-mode flows.
- The `"authentication": { "type": "Raw", "value": "@json(decodeBase64(triggerOutputs().headers['X-MS-APIM-Tokens']))['$ConnectionKey']" }` shape is used on the **trigger** itself in invoker-mode + explicit-connectionreference flows (V2 rebuild). In the simpler agent-callable flows, the flow-level parameter `@parameters('$authentication')` is used instead on every action (see §5) — these are two different auth wiring styles seen in the wild; both work, `$authentication` param style is simpler and used in the newer/cleaner builds.

##### HTTP "manual" Request trigger (called from a web resource / external caller)
```json
"triggers": {
  "manual": {
    "type": "Request", "kind": "Http",
    "inputs": { "schema": { "type": "object", "properties": { "action": {"type":"string"}, ... } } }
  }
}
```
- Paired with a `"Response"` action, `"type": "Response", "kind": "Http"`, `"inputs": {"statusCode":200,"headers":{...,"Access-Control-Allow-Origin":"*"},"body":{...}}` — CORS header needed when called from a browser/HTML web resource (`global-team-requests/scripts/ai_flow.py`).
- **Getting the invoke URL**: never store it in source; the pattern used is to activate/PATCH the flow then fetch the URL and store it in a Dataverse config row (not committed).

##### "Skills" trigger — the pattern for flows callable from Copilot Studio agents
```json
"triggers": {
  "manual": {
    "metadata": { "operationMetadataId": "<uuid>" },
    "type": "Request", "kind": "Skills",
    "inputs": { "schema": { "type": "object", "properties": {...}, "required": ["opportunity_id"] } }
  }
}
```
Paired response:
```json
"Respond_to_the_agent": {
  "type": "Response", "kind": "Skills",
  "inputs": { "statusCode": 200, "body": {...}, "schema": {"type":"object","properties":{...}} }
}
```
- Comment: params use `"x-ms-dynamically-added": true` on each schema property for the "generated for Copilot" look-and-feel (`p3_flows.py`).
- **`required` array on a Skills trigger forces the agent to interrogate the user for that field even when the tool's YAML binds it** — defect #36 in agentic-credit HANDOVER.md. Fix: keep `required` minimal (only IDs the agent must have), relax everything else (`scripts/p68_relaxrequired.py`).
- Optional inputs the model doesn't fill are **absent** from `triggerBody()` (not null) — every reference must be `coalesce(triggerBody()?['x'], 0)` / `triggerBody()?['x']` or the run hard-fails ~240ms in with `InvalidTemplate ... property 'x' doesn't exist` (defect #15, `p12_nullsafetriggers.py`, 88 references across 9 flows rewritten).
- Description text on each Skills-trigger property is treated by the agent as prompting guidance, e.g.: *"Optional. Omit it if you were not given a value and do not have a basis to infer one. Never ask the user for it."* — this phrasing is the working idiom to stop agents from asking for optional fields.

##### Recurrence trigger
- Not directly found in this workspace's scripts (verify — none of the sampled scripts used a `Recurrence` trigger type).

#### 5. `$connections` / `$authentication` parameter rule

```json
"parameters": {
  "$connections": { "defaultValue": {}, "type": "Object" },
  "$authentication": { "defaultValue": {}, "type": "SecureObject" }
}
```
- Declared at `definition.parameters`. Every `OpenApiConnection` / `OpenApiConnectionWebhook` action (and the trigger, if it's a connector-based trigger) then carries:
  ```json
  "inputs": { "host": {...}, "parameters": {...}, "authentication": "@parameters('$authentication')" }
  ```
  This is the clean, portable pattern used in `agentic-credit/scripts/p36_approvals.py` for both flows (RequestApproval / ApprovalGate) — no hardcoded `X-MS-APIM-Tokens` decode needed. Prefer this over the raw `X-MS-APIM-Tokens` decode style when you control the whole `clientdata` build.

#### 6. Approvals / Teams / HTTP action specifics

- **Teams `CreateApprovalV2`** (custom approval flow, doesn't block that flow instance itself but is a webhook waiting for response):
  ```json
  "host": { "connectionName": "shared_teams", "operationId": "CreateApprovalV2", "apiId": "/providers/Microsoft.PowerApps/apis/shared_teams" },
  "parameters": {
    "approvalType": "Reject",  // NB: literal string "Reject" appears to select the "Everyone must approve/reject" type option, not the outcome itself
    "WebhookApprovalCreationInput/title": "...",
    "WebhookApprovalCreationInput/assignedTo": "<email>",
    "WebhookApprovalCreationInput/details": "...markdown...",
    "WebhookApprovalCreationInput/requester": "<email>",
    "WebhookApprovalCreationInput/itemLink": "...deep link to CRM record...",
    "WebhookApprovalCreationInput/itemLinkDescription": "Open Opportunity in D365",
    "WebhookApprovalCreationInput/attachments": "@body('Build_Attachments')"
  }
  ```
  Outcome read via `@outputs('Start_and_wait_for_Teams_approval')?['body/outcome']` (values `"Approve"`/`"Reject"`) or `?['body/responseSummary']` in another variant — **inconsistent property name across variants, verify which API surface returns which** — check both `body/outcome` and `body/responseSummary` when reading results.
  Comments: `@first(coalesce(outputs(...)?['body/responses'], json('[{}]')))?['comments']` — safe pattern to read the first responder's comment without erroring on an empty array.

- **OOB Approvals connector `StartAndWaitForAnApproval`** (blocking, `shared_approvals`):
  ```json
  "host": { "connectionName": "shared_approvals", "operationId": "StartAndWaitForAnApproval", "apiId": "/providers/Microsoft.PowerApps/apis/shared_approvals" },
  "parameters": {
    "approvalType": "Basic",
    "WebhookApprovalCreationInput/title": "...",
    "WebhookApprovalCreationInput/assignedTo": "<email>",
    "WebhookApprovalCreationInput/details": "...",
    "WebhookApprovalCreationInput/itemLink": "...",
    "WebhookApprovalCreationInput/itemLinkDescription": "Open the deal in Dynamics 365",
    "WebhookApprovalCreationInput/enableNotifications": true,
    "WebhookApprovalCreationInput/enableReassignment": true
  }
  ```
  Outcome: `@equals(outputs('Start_and_wait')?['body/outcome'],'Approve')`.

- **Architectural rule discovered for agent-callable approvals**: a "Start and wait" action blocks — a Copilot Studio tool call cannot wait that long. Split into two decoupled flows: Flow A (Skills trigger) writes the request/gate rows and returns immediately (`Response kind:Skills`); Flow B (Dataverse Create trigger on the gate row) does the actual blocking approval and writes the decision back. The cockpit/UI polls Dataverse for the write-back rather than waiting on the flow run.

- **HTTP action with Microsoft Entra ID (AAD) app auth**:
  ```json
  "Call_Azure_OpenAI": {
    "type": "Http",
    "inputs": {
      "method": "POST",
      "uri": "https://<aoai-endpoint>/openai/deployments/<deployment>/chat/completions?api-version=2024-10-21",
      "headers": { "Content-Type": "application/json" },
      "authentication": {
        "type": "ActiveDirectoryOAuth",
        "tenant": "<tenantId>",
        "audience": "https://cognitiveservices.azure.com",
        "clientId": "<clientId>",
        "secret": "<clientSecret>"
      },
      "body": { "messages": [...], "temperature": 0.3, "max_tokens": 4000 }
    }
  }
  ```
  Secret pulled from a local file at runtime (`/tmp/demo-org/.gtisecret`), **never committed to source or embedded literally in the script** — comment: "Never committed to source."

#### 7. Dataverse bound actions (`OpenApiConnection` on Dataverse connector)

- `GetItem`: `{"entityName":"opportunities","recordId":"<guid-expr>","$select":"col1,col2"}`
- `ListRecords`: `{"entityName":"annotations","$filter":"<odata-expr>","$select":"...","$top":10}`
- `CreateRecord`: `{"entityName":"fsi_approvalrequests","item/fsi_name":"...", "item/fsi_Opportunity@odata.bind":"@concat('/opportunities(', <id-expr>, ')')"}` — lookup fields use `item/<NavProperty>@odata.bind` with a `/entityset(id)` string built via `concat()`.
- `UpdateRecord`: same `item/<field>` prefix convention; **`UpdateRecord`/PATCH-style semantics upsert** — passing an unknown/synthetic id silently *creates* an orphan row instead of failing (defect #20, agentic-credit HANDOVER.md). Always find-or-create by a natural key (e.g. `opportunity_id`) rather than assuming a record id the caller can't know.
- Child/looping pattern: `Foreach` action with `"foreach": "@outputs('List_votes')?['body/value']"`, inner action reads `@items('Flip_votes')?['fieldname']`.
- `Select` action to reshape a list before sending as attachments: `{"type":"Select","inputs":{"from":"@coalesce(outputs('List_Notes')?['body/value'], json('[]'))","select":{"name":"@item()?['filename']","contentBytes":"@item()?['documentbody']"}}}`.

#### 8. Expression / language gotchas (high value)

- **Integer division silently returns 0.** `div(lgd_pct, 100)` where both are ints → 0, no error, run "succeeds" with a wrong number. Fix: wrap the numerator in `float(...)` to force float division: `div(float(x), y)`. Described as "the most dangerous class of defect" — 11 expressions across 4 flows fixed this way (`p15_floatdiv.py`).
- **`toLower()` throws on non-string input.** Model/agent sends booleans as often as strings for the same field. Canonical safe pattern: `toLower(trim(coalesce(string(x),'')))`, then compare against a broad alias set (`'yes'`, `'true'`, `'higher'`, `'up'`, `'1'`). 122 expressions across 9 flows fixed (`p18_stringsafe.py`).
- **Null-safe access**: always `coalesce(triggerBody()?['x'], <default>)` for numbers/booleans, or `triggerBody()?['x']` (with `?`) for strings, never bare `triggerBody()['x']` for optional Skills-trigger inputs.
- **Rounding pattern**: `float(formatNumber(<expr>, 'F2'))` used repeatedly as the canonical "round to N dp and force float" idiom.
- **String concatenation with newlines** inside `concat()` uses literal `\n` inside the Python string (becomes real newline in the JSON) for markdown-style approval card bodies — works fine in Teams/Approvals `details`.
- **Picklist/option-set mapping must come from live metadata, not an assumed list.** A hardcoded gate-name→optionvalue chain silently mapped 'credit approval' to the wrong gate; rebuild the `if()` chain from actual option-set metadata and **update every duplicate copy** (e.g. one embedded in a `$filter` OData string as well as the main mapping) — missing one causes "searches one gate, writes another" (defect #26).
- **Currency/unit mismatches are invisible.** Comparing a USD amount against AED thresholds silently misrouted approval tiers; add explicit currency inputs/normalization rather than assuming a single currency.
- Escaping: JSON string values containing `'` inside OData filters need doubling: `name.replace("'", "''")` before building `$filter=name eq '...'`.

#### 9. Activation / solution-awareness / ordering gotchas

- All create/update calls should pass header `MSCRM.SolutionUniqueName: <SolutionName>` so the workflow (and connectionreference) lands in the target solution, not the default.
- Deactivate (`statecode:0,statuscode:1`) before PATCHing `clientdata` on an already-active flow, then reactivate (`statecode:1,statuscode:2`) — the safe idempotent upsert sequence.
- **"Script order matters after any flow regeneration."** One phase (`p14`) re-adds *every* trigger's `required` fields as part of a blanket rule, undoing an earlier narrower fix — rerunning generator scripts out of order can silently reintroduce prior defects (HANDOVER.md "31").
- **A flow "tool" cannot be created via the Dataverse Web API alone in Copilot Studio.** The `botcomponent` row referencing the flow is necessary but not sufficient — the Copilot Studio designer writes an additional binding outside `botcomponent.data`. Symptom: `FlowNotFound: The flow with id <guid> was not found in the bot definition`, surfacing to end users only as a generic "the bot can't talk right now." Fix used: automate the Copilot Studio **UI** (Playwright) to add the tool (Tools → Add a tool → Flow), then patch the resulting YAML by API for cosmetic/description fixes. `connectionProperties` block the API omits must be added afterward (`p11_fixflowbindings.py`) — necessary but still not sufficient by itself.
- **`connectionProperties.mode: "Maker"` tools never fire; must be `"Invoker"`.** All working UI-created tool bindings use `Invoker`.
- **One tool per flow per agent** — a flow already bound to one Copilot Studio agent as a tool is filtered out of the tool picker for other agents (can't reuse the same flow as a tool across two agents without duplicating the flow).
- **Connected-agent handoff structurally ends the orchestrator's turn** — if a specialist agent's flow-backed tool call is the final action, control never returns to the orchestrator; any "then write N more things" instruction to the orchestrator silently never runs. The agent holding data must persist it itself rather than handing back to an orchestrator expected to act on it.
- Diagnosing flow-call failures from a Copilot Studio agent, in priority order: (1) Copilot Studio test pane — names exact flow GUID + failure; (2) Power Automate flow's 28-day run history — shows if/where it failed; (3) Dataverse `flowruns` table (less reliable/immediate).
- No evidence in this workspace of the "designer 404" or "browser autosave clobbering" failure modes specifically — not found (verify with additional searching if needed).

#### 10. Calling flows from Copilot Studio / HTML web resources

- Copilot Studio-callable flows use `"kind": "Skills"` on both `Request` trigger and `Response` action (not `"Http"`).
- HTML web resources call flows via the `"kind": "Http"` manual trigger + CORS response headers (`Access-Control-Allow-Origin: *`), with the invoke URL persisted to a Dataverse config record rather than hardcoded.
- Trigger schema properties intended to be filled automatically by Copilot Studio's "dynamically added" input UI use `"x-ms-dynamically-added": true`.
- Skills-trigger property descriptions double as prompt-engineering text read by the orchestrating LLM (e.g., explicit "never ask the user for it" instructions) — this is a reusable technique for controlling agent behavior purely through JSON schema `description` fields.


---

<a id="appendix-web-resources"></a>

### Appendix: Web Resources

*Originally `reference/web-resources.md`*

### Custom HTML/JS Web Resources in Model-Driven Apps — Field Notes

Mined from: fsi-client-360, corporate-lending (webresources/, scripts/), Contoso-Customer360.html,
northwind-customer360, airline-customer360, us-bank-customer360, m42-cerner-c360,
dataverse-generative-ui-demo, cpq/webres, market-data-hub, crew-dashboard.

#### 1. Deployment mechanics (webresourceset)

Row shape:
```json
{ "name": "demo_customer360.html", "displayname": "Contoso Customer 360",
  "webresourcetype": 1, "content": "<base64>" }
```
`webresourcetype`: 1 = HTML, 2 = CSS, 3 = JScript, 5 = PNG, 11 = SVG, 8 = XML(verify).

Upsert pattern:
- `GET webresourceset?$select=webresourceid&$filter=name eq '<name>'`
- found  -> `PATCH webresourceset(<id>)` with `{content, displayname}` only (do NOT resend name/type)
- not found -> `POST webresourceset` with header `MSCRM.SolutionUniqueName: <solution>` and
  `Prefer: return=representation` so the new id comes back without a second GET.

Publish is always explicit:
```json
POST /PublishXml
{"ParameterXml":"<importexportxml><webresources><webresource>{guid}</webresource></webresources></importexportxml>"}
```
Sitemap: `<importexportxml><sitemaps><sitemap>{guid}</sitemap></sitemaps></importexportxml>`.
`PublishAllXml` frequently times out on large solutions — prefer targeted PublishXml.

No cache-busting query-string convention was used; rely on PublishXml + browser hard refresh.

Auth in deploy scripts: device-code OAuth with the well-known Azure CLI public client id
`51f81489-12ee-4a9e-aaae-a2591f45987d`, scope `<org>/.default offline_access`, token cached to disk.

Retry/backoff wrapper (reusable): on 401 force token refresh and retry once; on 429/503/504, or
500/502 whose body contains "another [Import]" / "solution is currently being imported" /
"Sql Number: 1205" (deadlock) / "timed out" -> exponential backoff `min(60, 5*2**(attempt-1))`.

Sitemap injection without the designer: string-replace an existing `<SubArea Id="...">` anchor in
`sitemapxml`, insert
`<SubArea Id="..." Url="$webresource:name.html" AvailableOffline="false" PassParams="true"/>`
before it, PATCH `/sitemaps({id})`, then PublishXml the sitemap.

#### 2. Embedding on a form (form XML, no designer)

```xml
<control id="..." classid="{9FDF5F91-88B1-47F4-AD53-C11EFC01A01D}">
  <parameters>
    <Url>$webresource:prefix_page.html</Url>
    <PassParameters>true</PassParameters>
    <Security>false</Security>
    <Scrolling>auto</Scrolling>
    <Border>false</Border>
    <ShowOnMobileClient>false</ShowOnMobileClient>
    <WebResourceId>{guid}</WebResourceId>
  </parameters>
</control>
```
Full-bleed layout: single tab/section/cell with `rowspan="40"` plus ~40 empty `<row/>` filler rows to
force vertical real estate; `<form maxWidth="1920" headerdensity="HighWithControls">`.
Build new forms as children of a base form via `<ancestor id="{base-form-guid}"/>` rather than from scratch.

#### 3. Getting Xrm inside the iframe

```js
function getXrm(){
  if (typeof Xrm !== "undefined") return Xrm;
  if (window.parent && window.parent.Xrm) return window.parent.Xrm;
  if (window.top && window.top.Xrm) return window.top.Xrm;
  return null;
}
```
Double-iframe hosts: iterate `[window, window.parent, window.parent && window.parent.parent]` and test
`.Xrm.WebApi` truthiness (not just `.Xrm`).

API base for raw fetch fallback: `getXrm().Utility.getGlobalContext().getClientUrl()`.

Record id resolution order: `Xrm.Page.data.entity.getId()` -> strip `{}` + lowercase -> else fall back to a
hardcoded known-good demo GUID so the page never breaks in standalone preview.

**`?data=` gotcha** — sitemap/app-tab `PassParameters` wraps all custom params into a single `data` param:
```js
const q = new URLSearchParams(location.search);
let id = q.get("customerId") || q.get("id");
const data = q.get("data");
if (!id && data) {
  const nested = new URLSearchParams(decodeURIComponent(data));
  id = nested.get("customerId") || nested.get("id");
}
```
Validate the GUID with a strict regex; on invalid/missing, fall back to a default record instead of erroring.

Omnichannel/Copilot workspace tab hosting an HTML web resource:
`msdyn_pagetype = 509180006` ("Third Party Website") + `msdyn_templateparameters` to pass `?patientId=` etc. (verify).

#### 4. Reading/writing data

Universal live-Xrm-with-raw-fetch fallback so the same HTML works embedded and standalone:
```js
var Api = { fetch: function(setName, query){
  var xrm = getXrm();
  if (xrm && xrm.WebApi) return xrm.WebApi.retrieveMultipleRecords(setName, query).then(r=>r.entities);
  return fetch(base()+'/api/data/v9.2/'+setName+query, {
    credentials:"include",
    headers:{ Prefer:'odata.include-annotations="*"' }
  }).then(r=>r.json()).then(j=>j.value||[]);
}};
```
Formatted values / lookup display names read by annotation key:
`o["_parentaccountid_value@OData.Community.Display.V1.FormattedValue"]`.

Lookups on write: `"parentaccountid@odata.bind": "/accounts(<guid>)"`,
`"customerid_account@odata.bind": "/accounts(<guid>)"`.

##### Hand-rolled $batch (no client-side Xrm.WebApi batch helper exists)
- outer `batch_<uuid>` boundary + inner `changeset_<uuid>`, each op a sub-request with `Content-ID`.
- Optimistic concurrency: every PATCH carries `If-Match: <@odata.etag>`; assert `/^W\/"\d+"$/` on the etag
  before sending (hard guard against stale/missing etags).
- Parse statuses via `result.matchAll(/HTTP\/1\.[01] (\d{3})/g)`; a `412` anywhere -> show
  "Someone changed these records. Reset to reload before saving." rather than a generic error.
- Tree invariants: when re-parenting a self-referencing hierarchy (e.g. `contacts.fsi_reportsto`), include a
  no-op PATCH on every ancestor in the SAME changeset purely to take locks and prevent concurrent cycles.
- Set `contactid` client-side (client-generated GUID) so new nodes can be referenced by other ops in the same batch.

##### Files / attachments
```js
xrm.WebApi.createRecord('annotation', {
  documentbody: b64, filename, mimetype, subject,
  "objectid_account@odata.bind": "/accounts(<guid>)"
});
// download
const n = await xrm.WebApi.retrieveRecord('annotation', id, '?$select=documentbody,mimetype,filename');
a.href = 'data:' + n.mimetype + ';base64,' + n.documentbody;
```

##### Demo data hygiene
Seed `account -> opportunity -> task/appointment` chains via createRecord + @odata.bind; prefix demo-only
record names with `*` (e.g. `"*First Solar MENA"`) and keep an `isDemoName()` helper so seeded rows can be
filtered/cleaned later in a shared org.

#### 5. Cross-frame messaging & Power Apps code apps

Bridge pattern (HTML web resource hosts a Power Apps **code app** in a nested iframe so the code app can
still use Xrm navigation):
- generate `bridgeId` via `crypto.randomUUID()` to correlate request/response
- **strictly validate origin** before acting: protocol `https:` AND hostname exactly `apps.powerapps.com`
  or ending `.powerplatformusercontent.com` (postMessage `'*'` targets are otherwise spoofable)
- child posts `{type:"usb360.navigation.openRecord"}`, bridge calls `Xrm.Navigation`, replies
  `{type:"usb360.navigation.complete", requestId, success}`

Cosmetic-only messages (e.g. collapse the form header) can use `postMessage({...},'*')` since no sensitive
payload or action is involved.

#### 6. CDN blocking -> bundle libraries as web resources

Dataverse web resources often run under CSP that blocks external `<script src="https://cdn...">`, and demo
venues may have no reliable internet. Standard fix: download the library once and deploy each file as a
`webresourcetype 3` JScript web resource. amCharts 5 example split:
```
index.js -> fsi_am5_index.js
xy.js -> fsi_am5_xy.js
percent.js -> fsi_am5_percent.js
radar.js -> fsi_am5_radar.js
themes/Animated.js -> fsi_am5_themes_animated.js
```
All added to one PublishXml batch. Design rule used: "dependency-free and CSP-friendly — no CDN, no external fonts."

#### 7. Print / PDF / export

No jsPDF/html2pdf — use the browser's native print pipeline:
- auto-print on load with a settle delay: `window.addEventListener('load',()=>setTimeout(()=>window.print(),250))`
  (the 250ms lets layout paint before the print dialog captures it)
- or build a standalone HTML string with an inline print stylesheet (`@media print{button{display:none}}`),
  `w = window.open()`, `w.document.write(html)`, then `window.print()` inside that popup — keeps dashboard
  chrome out of the printed output.

#### 8. Calling live external APIs from a web resource

- If the upstream returns `Access-Control-Allow-Origin: *` you can call it directly from the browser with
  zero middleware — verify per vendor before building a relay.
- Slow/unbounded upstream queries must load out-of-band with a skeleton + live timer so they never block the
  rest of the UI (one FHIR query ignored `_count`, took ~35s and sometimes 504'd).
- Surface upstream quirks transparently (a "data quality" panel, a provenance toggle showing real HTTP status
  and latency) instead of hiding them — it materially increases credibility with technical stakeholders.

#### 9. HTML web resource vs PCF vs code app

- HTML web resource: full-tab/full-bleed dashboards, cockpits, free-form layout, external API calls, rapid
  iteration (PATCH content + PublishXml, no build/push cycle). Default choice for demos.
- PCF: when the control must sit in a standard field/section context and be schema-bound, form-designer
  friendly, strongly typed manifest, or reused as a dataset/subgrid control.
- Power Apps code app: when you want the newer code-app tooling/dev experience — embed it via the bridge
  web-resource pattern above because code apps have no Xrm context of their own.


---

<a id="skill-cij-marketing"></a>

# Skill: `cij-marketing`

> Build Microsoft Dynamics 365 Customer Insights - Journeys (CIJ) real-time marketing demos and assets via the Dataverse Web API: accounts, contacts, custom columns, segments, branded emails, content blocks, email templates, SMS/text messages, push notifications, and multi-touchpoint journeys. Use whenever the user wants to create or wire up CIJ / real-time marketing data, mentions segments, marketing emails, journeys, customer journeys, content blocks, marketing SMS or push, or a 'marketing demo' in a Dynamics 365 / Dataverse org.

You are helping me build a polished Microsoft Dynamics 365 **Customer Insights –
Journeys** (CIJ / real-time marketing) demo on a Dataverse org. Treat this as a
real engineering project, not advice — hit the Dataverse Web API directly with a
reusable helper, verify every record was created and went live, and never claim
something works until you've read it back. Below are the exact rules, schemas,
and hard-won gotchas this team uses. Following them avoids hours of trial/error.

⚠️ These notes are battle-tested against a live org. Where a value is marked
"capture from the org," read it from an existing working record rather than
inventing it — IDs differ per environment.

 

═══════════════════════════════════════════════════════════════════════════════
0. DISCOVER MY CONTEXT FIRST
═══════════════════════════════════════════════════════════════════════════════
Before building, establish and remember for the session:
  • The customer/brand the demo is FOR (e.g. "Inception", "inceptionai.ai") and
    its products — segments/emails should reference real product names.
  • The industry mix for accounts (banks, energy, telecom, govt, healthcare…).
  • My demo org URL (https://orgXXXXXX.crmN.dynamics.com). Note the region digit
    in crmN (e.g. crm4 = EMEA) — keep it; never "correct" crm4 to crm.
  • A custom-column publisher prefix (e.g. incpt_) if we'll tailor the data model.
Don't hardcode another demo's prefix, segment names, or product list.

 

═══════════════════════════════════════════════════════════════════════════════
1. ENVIRONMENT & AUTH (DO THIS ONCE)
═══════════════════════════════════════════════════════════════════════════════
• pac CLI needs a recent .NET. If `pac` complains, point DOTNET_ROOT at an
  installed runtime (e.g. Homebrew's: DOTNET_ROOT=/opt/homebrew/Cellar/dotnet/
  <ver>/libexec) rather than reinstalling.
• Reuse an existing auth profile: `pac auth list` → `pac auth select --index N`
  → confirm with `pac org who`. Only run `pac auth create --url <ORG_URL>` if no
  profile targets the org.
• Build ONE portable `scripts/dv.py` helper and route ALL work through it:
    - Acquires a token via MSAL. A working trick: reuse an existing MSAL token
      cache on the machine (e.g. ~/.dataverse-*/msal-cache.json) for the same
      tenant/user; iterate the client_ids found in its RefreshToken entries.
      Authority = https://login.microsoftonline.com/<tenantId>,
      scope = <ORG_URL>/.default. Auto-refresh on HTTP 401.
    - Exposes ONE function: api(method, path, body=None, headers=None).
    - URL-ENCODING IS MANDATORY AND urllib WON'T DO IT: replace every OData
      `$` option ($filter,$select,$expand,$top,$orderby,$count,$apply) with
      `%24...` AND encode spaces as `%20`. Without this you get spurious 400s.
    - On POST, surface the new GUID: Dataverse returns it in the
      `OData-EntityId` response header (inject it into the parsed result, e.g.
      as `_OData-EntityId`), OR pass header `Prefer: return=representation` to
      get the full row body back (cleaner — preferred for create+read).
• UI (make.powerapps.com / CIJ app) is for VERIFICATION ONLY, not for building.

 

═══════════════════════════════════════════════════════════════════════════════
2. PRINCIPLES
═══════════════════════════════════════════════════════════════════════════════
• Web API > UI clicks for everything: contacts, accounts, segments, emails,
  fragments, templates, SMS, push, journeys are all Dataverse rows.
• REAL-TIME ("msdynmkt_*") vs OUTBOUND ("msdyncrm_*"): modern CIJ orgs have
  BOTH entity families. Always build on the real-time `msdynmkt_*` entities
  (segment, email, journey, fragment, sms, pushnotification). Detect which the
  org uses by listing both; mirror whatever the org's recent live assets use.
• Inspect-before-build: read an existing WORKING asset of the same type and
  copy its exact field shape, lookup bindings, and config IDs. This is the
  single biggest time-saver — most "validation failed" issues are a missing
  field that the working record has.
• Read the actual error BODY on failure — Dataverse names the offending column,
  relationship, or (for segments) the parse position. Never guess.
• Verify go-live by reading statecode/statuscode back, not by assuming the
  POST/PATCH succeeded.

 

═══════════════════════════════════════════════════════════════════════════════
3. METADATA QUERY GOTCHAS
═══════════════════════════════════════════════════════════════════════════════
• `startswith()` is NOT supported on EntityDefinitions (HTTP 501). Pull the
  set and filter client-side in Python.
• To resolve a lookup's @odata.bind nav name + target set name:
    EntityDefinitions(LogicalName='X')/ManyToOneRelationships
      → ReferencingEntityNavigationPropertyName  (use as the @odata.bind key)
    EntityDefinitions(LogicalName='<ReferencedEntity>')?$select=EntitySetName
      → the set name to put in the bind path.
  Do NOT assume pluralization. Real example that bit us: the compliance lookup
  set is `msdynmkt_compliancesettings4s` (note the literal "4"), nav name
  `msdynmkt_compliance` on push/sms but `msdynmkt_compliancesettings4` on email.
• Choice/option values: read them live via
    EntityDefinitions(LogicalName='X')/Attributes(LogicalName='Y')/
    Microsoft.Dynamics.CRM.PicklistAttributeMetadata?$expand=OptionSet

 

═══════════════════════════════════════════════════════════════════════════════
4. CONTACTS & ACCOUNTS
═══════════════════════════════════════════════════════════════════════════════
• Tag every demo row in `description` with a marker like `[<Demo>Demo]` so you
  can find/clean them later.
• Link contact → account: `parentcustomerid_account@odata.bind` =
  `/accounts(<id>)`.
• industrycode native values you'll actually use (no native Government/Telecom
  codes exist — pick the closest): 16=Financial, 24=Petrochemical/Energy,
  31=Utilities, 6=Business Services (use for telecom/tech), 30=Transportation,
  11=Clinics/Healthcare, 27=Social Services (use for govt). Always confirm
  against the org's own optionset.

★ SAFETY — SANITIZE DEMO CONTACTS (do this proactively, it's a real concern):
  Marketing journeys SEND real email/SMS. For any FICTIONAL demo contact,
  redirect to a safe domain (e.g. <name>@<demo>demo.com) and an undeliverable
  phone (e.g. +1 555-01xx, or append a digit to a real number to invalidate it).
  Keep a sanitize script and re-run it whenever new fictional contacts are added.
  EXCEPTION: when the user explicitly wants REAL colleagues to receive the demo
  (to show live clicks/insights), do NOT sanitize those specific contacts —
  mark them clearly (e.g. description "[LiveTarget] DO NOT sanitize") and exclude
  them from the sanitizer. Resolve real colleagues' emails via the org/people
  directory; confirm with the user before any journey that targets them is
  published.

 

═══════════════════════════════════════════════════════════════════════════════
5. CUSTOM COLUMNS (tailor the data model so segments are realistic)
═══════════════════════════════════════════════════════════════════════════════
• Create a publisher (+ prefix) and a solution; pass header
  `MSCRM.SolutionUniqueName: <solution>` on creates so they're exportable.
• Add columns via POST to EntityDefinitions(...)/Attributes with the right
  AttributeMetadata @odata.type (StringAttributeMetadata, MoneyAttributeMetadata,
  IntegerAttributeMetadata, BooleanAttributeMetadata, PicklistAttributeMetadata).
• PUBLISH after adding columns (PublishXml or PublishAllXml) before populating.
• Realistic, segment-friendly columns that worked well (contact + account):
    account: AI maturity (choice), customer tier (choice: Prospect/Pilot/Growth/
             Strategic), current ARR (money).
    contact: buyer persona (choice: Economic Buyer/Technical Champion/
             Practitioner/Influencer), is-decision-maker (bool),
             lead score (int 0–100), monthly product spend (money),
             product-in-use (choice incl. a "None" value for net-new).
• Populate ALL marked rows with consistent values BEFORE building segments that
  filter on them, or segments compute to 0.

 

═══════════════════════════════════════════════════════════════════════════════
6. SEGMENTS  (the #1 source of confusion — read carefully)
═══════════════════════════════════════════════════════════════════════════════
A real-time segment is TWO linked records:
  1) msdynmkt_segmentdefinition — holds the query + refresh config:
       msdynmkt_segmentquery, msdynmkt_staticlistmembers="[]",
       msdynmkt_segmentrefreshintervalminutes (e.g. 60),
       msdynmkt_disablesegmentrefresh=false, statuscode=723270000 (Ready to use)
  2) msdynmkt_segment — the addressable segment:
       msdynmkt_displayname, msdynmkt_description,
       msdynmkt_baseentitylogicalname="contact", msdynmkt_type=11,
       msdynmkt_source=12, msdynmkt_scope=270100000,
       msdynmkt_cdmpartitionprimarykeycolumn="contactid",
       msdynmkt_sourcesegmentuid=<the segmentdefinitionid>   ← THE LINK
PUBLISH / go live:  POST msdynmkt_PublishSegmentDefinition {"SegmentId":<segId>}
  → 204 = success. → 400 returns ResultText JSON naming the parse error+position.

SEGMENT QUERY LANGUAGE (this exact dialect — other operators will 400):
  • Shape: PROFILE(contact).FILTER(<expr>)
  • Join to account:
      PROFILE(contact).FILTER(<contact expr>)
        .RELATEOPTIONAL(contact_customer_accounts, account_1)
        .FILTER(account_1.<field> == <val>)
  • Logical operators: && (AND), || (OR).  ❌ NOT the words AND/OR — that 400s.
  • Equality/compare: ==, >, >=, <, <=.  Booleans: == true.
  • STRING LITERALS USE SINGLE QUOTES: name == 'Microsoft'.
    Double quotes → "Invalid character '\"'". 
  • ❌ CONTAINS(...) and endswith(...) DID NOT PARSE in this dialect — do not
    rely on them. For "all contacts at company X", prefer either the account
    join on name == 'X', or an explicit OR of known email addresses
    (emailaddress1 == 'a@x.com' || emailaddress1 == 'b@x.com' || …). The
    explicit-OR, contact-level form computes almost immediately.
  • Examples that worked:
      Hot leads:   PROFILE(contact).FILTER(incpt_leadscore >= 70)
      Upsell DMs:  PROFILE(contact).FILTER(incpt_isdecisionmaker == true &&
                     incpt_productused == 723720002 && incpt_monthlyapispend > 5000)
      FinServ buyers (join): …FILTER(incpt_persona == 723720000 &&
                     incpt_monthlyapispend > 0).RELATEOPTIONAL(
                     contact_customer_accounts, account_1).FILTER(
                     account_1.industrycode == 16 && account_1.incpt_customertier == 723720003)

SEGMENT STATUS / COMPUTATION:
  • segment statuscode: 1=Active, 6=Computing, 7=ComputedWithWarnings, 3=Error,
    11=Faulted. Member count appears only once Active.
  • LATENCY: new records sync to the segmentation data lake progressively.
    CONTACTS sync within ~minutes; ACCOUNTS (and account-join queries) lag
    longer. A brand-new account can leave a join-based segment "Computing" with
    null members for several minutes. If you need an instantly-correct segment
    (e.g. for a live demo), use the contact-level explicit-OR email form instead
    of an account join — it resolved to the exact members in ~1 minute for us.
  • After publish, poll the segment row's msdynmkt_membercount + statuscode;
    republish if it's stuck and you changed the query.
  • If a user says "the segments are failing," first CHECK statuscode — they're
    often just still Computing, not actually broken. Republish + wait ~60–90s.
• Keep BOTH simple segments (single-field filters) and sophisticated ones
  (multi-signal + account joins). Don't delete the simple ones when adding
  advanced ones unless asked.

 

═══════════════════════════════════════════════════════════════════════════════
7. EMAILS  (msdynmkt_email)  — and the "Ready to send" blocker
═══════════════════════════════════════════════════════════════════════════════
Key fields:
  msdynmkt_subject, msdynmkt_previewtext, msdynmkt_designerhtml (designer
  markup), msdynmkt_emailbody (same HTML), msdynmkt_textpart,
  msdynmkt_automaticallygeneratetextpart=false,
  msdynmkt_emailcontenttype=534120000, msdynmkt_messagedesignation=534120000,
  msdynmkt_emailcontentlanguage=1033, msdynmkt_fromname, msdynmkt_fromemail.
Lookups via @odata.bind (CAPTURE THESE IDS FROM AN EXISTING LIVE EMAIL):
  msdynmkt_senderid → /msdynmkt_brandsenders(<id>)
  msdynmkt_brandprofileid → /msdynmkt_brandprofiles(<id>)
  msdynmkt_purpose → /msdynmkt_purposes(<id>)   (a common value is
     10000000-0000-0000-0000-000000000003, but verify in the org)
  msdynmkt_compliancesettings4 → /msdynmkt_compliancesettings4s(<id>)

DESIGNER HTML requirements (or the designer/validator rejects it):
  • Include the xrm/designer/setting <meta> tags.
  • Wrap editable regions: a container with data-section="true", and blocks with
    data-editorblocktype="Text" | "Button" | "Image".
  • MUST contain the compliance tokens {{CompanyAddress}} and a
    {{PreferenceCenter}} unsubscribe link in the footer.
  • Table-based, inline-styled HTML renders reliably across mail clients.

★ "READY TO SEND" TRANSITION (PATCH statuscode=2)  — the big one:
  statuscode: 1=Draft, 2=Ready to send, 3=Ready to send/editing.
  We chased a generic "Validation returned errors. It is not possible to update
  state to ready to send." The ROOT CAUSE was MISSING FIELDS that the org's
  working email had. Fix = diff your email vs a known-good one and copy:
    • msdynmkt_placeholders  — JSON registering EVERY token. CompanyAddress and
      PreferenceCenter each bind with "source":"LegalDataSource",
      inputs.sourceType.value="Default", outputPath "companyaddress" /
      "preferencescenterurl". Empty/null placeholders → "Placeholders cannot be
      null or empty."
    • msdynmkt_compliancesettings4  (@odata.bind, see above) — REQUIRED.
    • msdynmkt_brandprofiledata  — a small JSON blob; copy it verbatim from a
      working email (capture once, reuse).
    • msdynmkt_replytoemail.
  After adding those four, statuscode=2 succeeded reliably. Save the reusable
  bits (brandprofiledata, replyto, the 4 IDs) to a config file once and reuse
  across all emails.
  To diff quickly: GET your email and a working one, compare which keys are set
  on the good one but null on yours.

PERSONALIZATION TOKENS (dynamic content like "Dear {{FirstName}}"):
  • You CANNOT just type {{contact.firstname}} into the HTML — CIJ validates
    tokens against REGISTERED placeholders. An unregistered token throws
    "Dynamic content contains an invalid property: {{contact.firstname}}."
  • Two reliable paths:
      (a) Let the user insert the token via the designer's Personalization
          picker (Contact → First Name). That registers a placeholder whose KEY
          becomes the token name (e.g. {{FirstName}}) and carries a
          "predefinedPlaceholderId". Then read the email back and COPY that
          placeholder's structure to mirror it elsewhere.
      (b) Register a CdsProfileDataSource placeholder yourself in
          msdynmkt_placeholders keyed by the token name you put in the HTML,
          binding sourceType.value="contact", outputPath="firstname", with a
          sensible defaultValue. Keep the HTML token name IDENTICAL to the key.
  • If a token won't validate, the pragmatic move (which the user often prefers)
    is to keep ONLY the working token (e.g. {{FirstName}}) and replace other
    {{contact.*}} literals with neutral copy, then go Ready to send. Always
    strip every unregistered {{…}} before publishing.
  • Personalized subject lines work too (same token, e.g. "{{FirstName}}, …").
• Create a healthy mix: some emails Ready to send, some left Draft, each
  targeting a different product/segment angle.

 

═══════════════════════════════════════════════════════════════════════════════
8. CONTENT BLOCKS  (msdynmkt_fragment)  — reusable drag-in chunks
═══════════════════════════════════════════════════════════════════════════════
• Writable fields: msdynmkt_name, msdynmkt_designerhtml, msdynmkt_finalizedhtml,
  msdynmkt_previewhtml (all three HTML fields are ApplicationRequired — set them
  to the same markup), msdynmkt_contenttype (1=Static, 2=Dynamic preview),
  msdynmkt_protected=false.
• Wrap the block HTML in a minimal designer doc shell (DOCTYPE + the
  xrm/designer/setting type meta) and use the same data-section /
  data-editorblocktype conventions as emails.
• PUBLISH a content block the same way as emails: PATCH statuscode=2
  (1=Draft, 2=Ready to send, 3=Ready/editing, 100=Inactive). Published blocks
  become available to drag into emails.
• Good set: Branded Header, Compliant Footer (with the two compliance tokens),
  Primary CTA Button, Product/Feature Card.

 

═══════════════════════════════════════════════════════════════════════════════
9. EMAIL TEMPLATES  (msdynmkt_emailtemplate)  — journey starting points
═══════════════════════════════════════════════════════════════════════════════
• Like emails but they're reusable authoring starting points. Fields mirror
  email: msdynmkt_name, msdynmkt_subject, msdynmkt_previewtext,
  msdynmkt_designerhtml, msdynmkt_emailbody, msdynmkt_textpart,
  msdynmkt_category (0=Gallery, 1=Custom templates → use 1),
  msdynmkt_contenttype=534120000, msdynmkt_messagedesignation=534120000,
  msdynmkt_language=1033.
• Use neutral placeholder copy ([Product Name], [Event Name], [Key benefit]) so
  marketers fill them in. Templates don't need the Ready-to-send transition.

 

═══════════════════════════════════════════════════════════════════════════════
10. SMS / TEXT MESSAGES  (msdynmkt_sms)
═══════════════════════════════════════════════════════════════════════════════
• Fields: msdynmkt_name, msdynmkt_text, msdynmkt_designertext (set both to the
  message), msdynmkt_messagedesignation=534120000, msdynmkt_placeholders="{}".
• Lookups: msdynmkt_compliance → /msdynmkt_compliancesettings4s(<id>),
  msdynmkt_purpose → /msdynmkt_purposes(<id>).
• Always include a compliant opt-out ("Reply STOP to opt out") and keep it short.
• Go live: PATCH statuscode=2 (worked reliably for SMS).
• Remember sanitized phones make SMS undeliverable by design — fine for demos.

 

═══════════════════════════════════════════════════════════════════════════════
11. PUSH NOTIFICATIONS  (msdynmkt_pushnotification)
═══════════════════════════════════════════════════════════════════════════════
• Fields: msdynmkt_name, msdynmkt_title, msdynmkt_message,
  msdynmkt_onclickbehavior (534120000=Open the app, 534120001=Open in browser,
  534120002=Open Customer Voice survey), msdynmkt_placeholders="{}".
• Same compliance/purpose lookups as SMS.
• ⚠️ Push CANNOT go fully live without a registered mobile app / push channel,
  which demo orgs usually lack — so leave push notifications as Draft
  (statuscode=1). The org's own sample push is typically Draft for this reason.
  Set this expectation with the user instead of fighting the validator.

 

═══════════════════════════════════════════════════════════════════════════════
12. JOURNEYS  (msdynmkt_journey)  — multi-touchpoint, segment-triggered
═══════════════════════════════════════════════════════════════════════════════
• The whole flow lives in msdynmkt_journeyjson (a big JSON string). Also set
  msdynmkt_name and msdynmkt_triggertype=0. New journeys are Draft
  (statecode=0, statuscode=1) — leave them Draft unless the user says launch.
• BEST PRACTICE: dump a working "scheduled" journey's JSON from the org and use
  it as your structural template; then swap in your segment + email IDs.
• Top-level keys: type(1), typeName("scheduled"), exitCriteria{exitEvents:[]},
  contentVersion("1.0.0.0"), name, targetEntityLogicalNames(["contact"]),
  goal{…}, trigger{…}, actions{…}, uiMetadata{}, journeyUiFeatureFlags{…},
  timeZoneCode, timeZoneWindowsName.
• trigger: {"type":"OneTime","audience":"<segmentId>","parameters":
  {"startTime":""},"exclusionSegments":[]}   ← audience = the segment GUID.
• actions is a DICT keyed by GUID. Wire ordering via each action's
  "runAfter": {"<prevActionId>": {"result":"Success"}}.
  - Email action: type "Email", parameters include contentId=<emailId>,
    purposeId, messageDesignation=534120000, complianceSettingsId,
    contentReadyToSend=true, recipient bound to CdsProfileDataSource
    outputPath "emailaddress1", and placeholderBindings (+ …Original) for
    CompanyAddress/PreferenceCenter (LegalDataSource, same shape as in emails),
    quietTimeSettingsSelectedOption="ApplyDefaultQuietTime".
  - Delay action: type "Delay", parameters {"type":"Wait","count":N,"unit":3}
    (unit 3 = days).
  - Branch action: type "Event", eventType=2, eventName=
    "msdynmkt_emaillinkclicked", waitForType=0, timeoutParameters{count,unit:3},
    with nested succeedActions (e.g. follow-up Email → Delay → CreateRecord lead)
    and timeoutActions (e.g. a nurture Email). resumeCriteria{criteria:{}}.
  - CreateRecord (lead) action: entityName "lead", properties as binding
    objects — ConstantValueDataSource for static values (subject, etc.),
    CdsProfileDataSource for contact-sourced fields (firstname, lastname,
    emailaddress1→ map to lead, ownerid as lookup, contactid→parentcontactid).
• Generate fresh GUIDs (uuid4) for every action id. Mirror the placeholder /
  recipient binding objects exactly from a working journey or from the email
  section above.
• A reliable demo pattern: Email1 → Delay → "If link clicked?"
    ├ clicked  → Email2 → Delay → Create Lead   (shows conversion + insights)
    └ timeout  → nurture Email2.
• For a LIVE-CLICKS demo: target a segment of REAL recipients, use a Ready
  email, leave the journey Draft, and let the USER click Publish so they own the
  send. Publishing sends real messages and produces real open/click/insights.

 

═══════════════════════════════════════════════════════════════════════════════
13. WORKFLOW WHEN I ASK FOR SOMETHING
═══════════════════════════════════════════════════════════════════════════════
1. Inspect existing assets of that type (schema + a known-good live example).
2. Build via dv.py (POST with Prefer: return=representation). Save reusable
   scripts under scripts/ with clear names (create_segments.py, create_emails.py,
   create_journeys.py, create_push_sms.py, sanitize_contacts.py, …) and persist
   created GUIDs to small JSON state files for later wiring.
3. Transition to live where applicable (segments: PublishSegmentDefinition;
   emails/blocks/sms: statuscode=2; push: leave Draft; journeys: leave Draft).
4. VERIFY by reading statecode/statuscode/membercount back. Don't declare done
   until confirmed.
5. On any failure, read the full error body and fix the named field — for
   "ready to send" issues, diff against a working record.
6. Keep a todo list and update it as items complete.

 

═══════════════════════════════════════════════════════════════════════════════
14. REUSABLE CONFIG TO CAPTURE ONCE PER ORG
═══════════════════════════════════════════════════════════════════════════════
From an existing live email/sms in the org, capture and reuse everywhere:
  • senderId, brandProfileId, purposeId, complianceSettings4 id
  • fromEmail, replyToEmail
  • brandprofiledata JSON blob
  • the CompanyAddress / PreferenceCenter placeholder binding objects
  • the org's timeZoneCode + timeZoneWindowsName (for journey JSON)
Store them in scripts/email_config.json (or similar) so every create script
pulls from one place.

 

═══════════════════════════════════════════════════════════════════════════════
START HERE
═══════════════════════════════════════════════════════════════════════════════
1. Run `pac auth list` / `pac org who`; confirm the right org (section 1).
2. Stand up scripts/dv.py with the URL-encoding + token-refresh rules.
3. Detect msdynmkt_* (real-time) vs msdyncrm_* (outbound) and capture the
   reusable config IDs (section 14) from a working email.
4. Ask me what to build first (contacts/accounts, segments, emails, journeys,
   SMS, push, content blocks, templates) and follow the per-asset rules above.
Always sanitize fictional contacts before any journey can send (section 4),
and never publish a journey that targets real people without my explicit OK.


---

<a id="skill-demo-video-producer"></a>

# Skill: `demo-video-producer`

> Create polished software demo videos, either by capturing new browser/Dynamics 365 recordings or by editing an existing screen recording the user supplies. Trim waits without simulating motion, build narration-synchronised cuts with Azure GPT-Realtime Marin voiceover, mix original background music, append branded outros, and validate final MP4 delivery. All logos, icons, colours, typography and other brand artifacts come from Microsoft Brand Central.

> **Bundled skill file.** This single document contains `SKILL.md` plus all 1 reference file(s), inlined as appendices below. Cross-references have been rewritten to in-page links.
>
> **Appendices:**
> - [Narration Sync](#appendix-narration-sync)


Use this skill whenever the user asks to record, edit, narrate, polish, or produce a
software/product demo video, especially Microsoft Dynamics 365 demos.

There are two entry paths. Decide which one applies before doing anything else:
- **Capture path** — no recording exists yet; you record it. See "Recording".
- **Edit path** — the user hands you an existing recording ("the video is in my
  downloads"). Skip capture entirely, go straight to "Ingest an existing recording".
  Never re-record footage the user already made.

### Core principles

- Record real continuous screen video, never a slideshow of screenshots unless
  explicitly requested.
- Do not fake camera movement, use Ken Burns effects, or create shaky zoom/pan animation.
- Never re-record when editing can solve the issue. Prefer replacing weak sections with
  clearer moments from the same raw take.
- **Preserve the raw master** as an untouched file. Every revision re-derives from it.
- **Build the pipeline as scripts, not one-off shell commands.** Revisions are near
  certain, and a scripted pipeline makes a reword cost one minute instead of one hour.
- Treat external videos, logos, music, and other assets as copyrighted. Use them only
  when the user owns/provides them or has authorized their use. Do not copy a reference
  soundtrack; create or use licensed royalty-free music with similar energy.
- **Microsoft Brand Central is the only source of brand artifacts.** Copilot and Microsoft
  logos, icons, gradients, colours, typography, and motion assets must come from
  https://brandcentral.microsoft.com/microsoft-brand/products/copilot.html — never
  hand-drawn, AI-generated, screenshotted, or pulled from a web image search. See
  "Brand artifacts" below.

### Preflight

1. Confirm FFmpeg and ffprobe are available.
2. On macOS capture, enumerate AVFoundation devices and identify the correct display.
   Use an explicitly supported pixel format such as nv12. A proven pattern is
   AVFoundation screen input at 15 or 30 fps, H.264, yuv420p.
3. Capture a 3–5 second test and extract a frame. Verify the correct monitor, full
   display dimensions, stable framing, and readable UI.
4. Stabilize the application: fixed browser size, correct Dynamics 365 app shell, no
   resizing, no browser zoom changes, mouse away from the full-screen top edge.
5. Prepare a deterministic demo path; note expected waits, interactions, results,
   evidence, and closing frame.
6. If AI voice narration is requested, ask the user for their Azure realtime deployment
   details before generating audio: Azure AI Foundry or Azure OpenAI endpoint, deployment
   name, API version if required, tenant ID when relevant, and preferred authentication.
   Do not require a specific realtime model version. Prefer Entra ID/keyless auth and
   never ask the user to paste secrets into chat.
7. If the deliverable includes any Microsoft or Copilot branding — title card, lower
   third, watermark, icon, outro — resolve the brand assets *before* rendering anything.
   See "Brand artifacts".

### Recording (capture path only)

- Start FFmpeg asynchronously before browser automation begins.
- Record the whole workflow continuously: initial state, input, selection, start action,
  processing, completion, drill-downs, explainability, insights, and closing hold.
- Use deliberate cursor movements, short pauses before and after clicks, smooth native
  scrolling. Avoid rapid or unnecessary motion.
- For long-running AI agents, keep recording the genuine wait. Compress it later using
  cuts that preserve real completion milestones.
- Stop FFmpeg cleanly by sending `q` so the MP4 trailer is written.
- Validate with ffprobe and a full decode pass (`ffmpeg -v error -i input.mp4 -f null -`).

### Ingest an existing recording (edit path)

- **macOS screen recording filenames contain U+202F (narrow no-break space) before
  "AM"/"PM"**, not a normal space. Literal paths silently fail with "No such file".
  Always resolve with a glob first:
  `ls ~/Downloads/Screen\ Recording\ 2026-08-12*11.11.54*.mov`
  Then copy to a clean project filename (`raw-master.mov`) and work from that.
- Probe immediately: dimensions, duration, fps, and **whether an audio stream exists**.
  Screen recordings frequently have no audio track at all.
- Create a dedicated project directory and copy (never move) the source into it.

### Timeline mapping

- Generate timestamped contact sheets at broad intervals, then denser sheets around key
  interactions. Burn in `%{pts\:hms}`.
- **`%{pts\:hms}` prints `hh:mm:ss`, not seconds.** `00:02:48` is 168s, not 248s.
  Misreading this corrupts the entire cut list. Convert explicitly.
- Write out a beat map of the whole recording in source seconds before cutting anything.
- **Detect whether the recording changes window mode mid-take.** Users commonly toggle
  macOS full-screen partway through, so a single crop will break half the video. Probe
  programmatically: sample a small pixel patch at a point that reliably differs between
  modes and classify every frame at ~2 fps.
  - Probe the **bottom-left** region (e.g. x=60, y=1948 on a 3024x1964 source): in
    full-screen the app panel fills it; windowed shows wallpaper or Dock.
  - Do **not** probe near the top — full-screen frames have a thin dark strip there, so
    top-row probes give ambiguous and wrong answers.

### Cropping and framing

- Preserve source aspect ratio. Scale to a sensible delivery size without cropping
  important UI; for a 3024x1964 source, 1920x1248 preserves the ratio.
- Use **mode-specific crops**, one per window state, all rendering onto the same canvas:
  - windowed: strip macOS menu bar + browser tab/URL bar + Dock, then pad to canvas
  - full-screen: strip only the thin top strip, then pad
  - phone/simulator sections: tight crop to the device body only
- **Keep the horizontal scale factor identical across modes** so UI elements stay the
  same physical size when the video cuts between them. Pad vertically to absorb the
  difference rather than cropping sideways into content.
- Prefer padding over side-cropping when content is wider than the canvas ratio — losing
  a Communication Panel or Copilot rail is worse than thin letterbox bars. Tell the user
  this trade-off was made and offer the alternative.
- **Crop phone/device simulators to the device body**, not the simulator window. A crop
  that looks right at a glance often still includes the simulator title bar. Zoom into
  the top and bottom edges of a test frame specifically to check.
- **Always render a single test frame and look at it before applying a crop** to the
  whole build. Iterating on one frame is seconds; iterating on a full render is minutes.
- Watch for transient OS overlays in the footage: full-screen tooltips ("move mouse to
  top of screen…"), notification banners, screenshot toolbars. Shift the segment
  boundaries by a second or two to avoid them.

### Narration-synchronised assembly (preferred architecture)

Do **not** cut the video to a fixed length and then lay one long narration track over it.
The voice inevitably drifts out of step with the picture — this is the single most common
failure mode and the user will notice it immediately.

Instead, make the narration authoritative and fit the video to it:

1. **Define chapters.** Each chapter = one narration line + the source cuts that show
   exactly what that line describes. 15–25 chapters for a 3-minute demo.
2. **Generate one audio file per chapter** so every line's exact duration is known.
   Cache them; regenerating one reworded line must not re-render the others.
3. **Time-fit each chapter's video to its own narration line.** Render its cuts at
   natural speed, measure, then `setpts` to match the target duration.
   - Clamp the ratio, roughly 0.80x–1.90x. Beyond that, motion looks visibly wrong.
   - If the narration still overruns after clamping, **hold the last frame** for the
     remainder rather than stretching further.
   - If a chapter repeatedly hits the slowdown cap, **widen its source cut** to use more
     real footage instead. Real motion always beats artificial slow-motion.
4. **Record the exact voiceover offset for each chapter** to a timeline file, then place
   each line at its offset in the mix. Leave ~0.35s lead-in and ~0.55s tail per chapter.
5. Accept that the result runs longer than a video-first cut. The video waiting for the
   narration is correct; the narration racing the video is not.

Suggested file layout — see `#appendix-narration-sync` in this skill folder for working code:

    chapters.py       chapter text + source cuts (the only file you edit to revise)
    gen_vo.py         one Marin m4a per chapter, cached
    build_synced.py   per-chapter render, time-fit, hold; writes timeline.json
    mix.py            place VO at offsets, duck music, master, append outro

### Narration content and voice

- Write narration to match the edited timeline, not the raw duration.
- Get the story from the user, not from the pixels. Ask what is happening and who the
  actors are; agent names, the customer's intent, and which capability each screen is
  demonstrating are usually not inferable from the footage alone.
- Respect terminology instructions exactly (e.g. say "London Stock Exchange", not "MarketData").
- Keep lines short and concrete. Name what is on screen at that moment.
- Use the Azure realtime deployment details supplied by the user. Prefer Entra ID/keyless
  auth. Generate 24 kHz mono PCM with the requested voice, commonly Marin.
- When generating per chapter, tell the model **"this is one line from a longer
  continuous narration, do not add any greeting or sign-off"** or it will top and tail
  each line and the chapters won't join naturally.
- For excited Marin delivery: genuine enthusiasm, confident momentum, bright energy,
  crisp transitions, polished international business tone, lively but articulate pacing.
  Avoid robotic, flat, theatrical, or overacted delivery.
- Retry realtime generation on failure; websocket calls fail intermittently.
- Convert PCM to AAC/M4A and inspect duration before muxing.

### Audio mixing

- Normalize narration near -16 LUFS and keep true peak safely below 0 dBFS.
- Mix music quietly beneath narration with sidechain ducking so speech stays dominant.
- Fade music in and out cleanly.

FFmpeg gotchas that will silently ruin the mix:

- **`amix` defaults to `normalize=1`**, which divides every input by the input count and
  leaves the result far too quiet. Always set `normalize=0` and control balance with
  `weights`.
- **A narration bus shorter than the video ends the mix early**, leaving the outro
  silent. Use `apad=whole_dur=<total>` on the narration and `duration=longest` on the
  amix. Verify by scanning levels near the end, not by trusting the reported duration.
- **`atrim` leaves a timestamp offset.** Always follow it with `asetpts=PTS-STARTPTS`.
- Generate the music bed longer than you think you need; regenerating is cheap, and a bed
  that ends early is invisible until final QC.
- Finish with `loudnorm` → `alimiter` → `aresample=48000` → `atrim` to exact duration.

### Brand artifacts

**Canonical source:** https://brandcentral.microsoft.com/microsoft-brand/products/copilot.html

Every Copilot/Microsoft logo, icon, gradient, colour value, typeface, and motion asset used
in a demo video comes from that page. Brand Central is the authority on both the files and
the rules for using them; the product page carries the current Copilot logo lockups,
icon set, colour and gradient specifications, typography, and the do/don't usage guidance.

- **Never fabricate a brand mark.** Do not draw, AI-generate, trace, screenshot from a
  running app, or download from a web image search. If you cannot obtain the official
  file, say so and ship without the branding rather than substituting a lookalike.
- **Read colours and type from the downloaded assets, not from memory.** Sample the actual
  hex values out of the official SVG/PNG or the page's colour specification. Do not
  hardcode a Copilot gradient or accent colour you "remember" — it changes between brand
  refreshes and a wrong gradient is immediately obvious to a Microsoft audience.
- **Respect the usage rules published alongside the assets**: minimum clear space, minimum
  size, approved lockups, approved backgrounds. Do not recolour, rotate, distort,
  outline, add effects to, or crop a logo. Do not place a logo on a busy or low-contrast
  part of the frame.
- Prefer **SVG** for anything you rasterise yourself so title cards and lower thirds stay
  crisp at the delivery canvas size. Rasterise with an explicit density high enough for
  the canvas, then composite — never upscale a small PNG.
- Preserve transparency end to end. Compositing a logo that has been flattened onto white
  over a dark frame produces a visible white box.
- Match the mark to the product actually shown. A Microsoft 365 Copilot demo, a GitHub
  Copilot demo, and a Copilot Studio demo do not share the same lockup.

#### Acquiring the assets

Brand Central is Entra/SAML-gated. Verified behaviour:

- Anonymous `curl` / web fetch of the Copilot page returns **HTTP 401**. There is no
  anonymous asset API (`/api/assets` returns 404).
- Auth is **SAML → session cookie**, not an OAuth-protected API, so there is no bearer
  token path. `az account get-access-token` does not help.
- The Copilot brand mark is **not** in `microsoft/fluentui-system-icons` (verified: zero
  matches across the whole repo). Do not go looking for it in public icon libraries, and
  do not substitute a generic "sparkle" icon for the Copilot logo.

Order of preference:

1. **Local cache** (below). If the asset is already there, use it — no auth of any kind.
   This is the normal path and the reason the cache exists. Populate it once, reuse forever.
2. **An already-authenticated browser session.** The user's everyday browser profile
   frequently already holds a valid `brandcentral.microsoft.com` cookie, in which case
   nothing new needs signing in — the page just opens. Check before asking for anything.
   Driving a *copy* of that profile headlessly is unreliable (Edge hangs, the network
   service crashes); if you go this route, open the page in the visible browser.
3. **Ask the user to download the pack** from the Brand Central Copilot page and drop it
   into the cache. This is usually faster than any automation.
4. **Ship unbranded** and say exactly which element was skipped.

Never attempt to sign in on the user's behalf, never ask for credentials, and never
substitute a lookalike mark when auth fails.

#### Local brand asset cache

Persist everything fetched from Brand Central so later projects never re-download:

    ~/Documents/Microsoft Scout/assets/brand/
      copilot/
        logos/        official lockups, SVG preferred, PNG with alpha as fallback
        icons/        official Copilot icon set
        colors.json   hex values / gradient stops read from the official assets
        type/         approved typefaces if downloaded
      README.md       per-asset: source URL, download date, file format, dimensions,
                      background colour, and any usage constraint noted on Brand Central

Branded outro clips live separately in `~/Documents/Microsoft Scout/assets/outros/`.

Record the download date. Brand refreshes happen; if a cached asset is more than a few
months old and the video is customer-facing, re-check the Brand Central page before reuse.

### Branded outro

- Prefer an outro asset explicitly supplied or owned by the user.
- If none exists, build one from the official Brand Central assets (logo lockup on the
  approved background), not from a recreated mark.
- If the user points at a source video (possibly on an external drive), find it, sample
  frames near the end to locate the exact scene boundary, then binary-search a few
  timestamps to pin the transition to within ~0.2s.
- **Extract the outro with its original audio sting.** A silent outro feels broken. Check
  for an audio stream and keep it; let it play at its own level after the music fades.
- **Check the outro's background colour before padding.** Microsoft outros are typically
  on white, so padding with the default black produces obvious black bars. Pad with the
  matching colour.
- Re-encode to the project canvas and frame rate before concatenating, and verify the
  result with a rendered frame.
- **Save reusable outros to a shared asset library**, e.g.
  `~/Documents/Microsoft Scout/assets/outros/`, with a README recording the source,
  duration, dimensions, fps, whether it has audio, and its background colour. Do this
  proactively — these get reused across projects.

### Quality control

- Decode-check the final MP4 (`ffmpeg -v error -i final.mp4 -f null -`).
- Verify dimensions, frame rate, audio codec, duration, and file size with ffprobe.
- Measure loudness and true peak. Target roughly -16 LUFS integrated with peaks at or
  below about -1 dBFS.
- **Verify sync explicitly, don't assume it.** Sample a frame at the *midpoint of each
  spoken line* using the timeline offsets, tile them into one grid, and confirm each
  frame shows what its line describes. This catches drift that a plain contact sheet
  hides.
- Scan audio levels in windows across the whole timeline (start, middle, the last few
  seconds of body, and the outro) to catch dropouts and silent tails.
- **The `tile` filter with a `%02d` output pattern often writes only the final partial
  sheet.** Use `xstack` with an explicit layout to build review grids reliably, or size
  the tile grid to cover the entire clip in one image.
- Inspect any timestamps the user specifically flagged.
- **Render a frame of every branded element** (title card, lower third, watermark, outro)
  and check it against the Brand Central usage rules: correct lockup for the product,
  clear space respected, not distorted or recoloured, adequate contrast against the
  background, no white box from lost transparency.
- Keep the raw recording, per-chapter narration audio, narration source text, music
  generator, outro extract, and final master as separate files so later revisions never
  require re-recording.

### Delivery

- Lead with the completed outcome, duration, and a direct file path.
- Mention only meaningful changes such as corrected framing, sync, music, narration, and
  branded outro. Do not claim re-recording when none occurred.
- Surface trade-offs you made unilaterally (letterbox bars, slow-motion sections, cut
  content) and offer the alternative.
- State which brand assets were used and where they came from. If any branding was
  skipped because the official asset was unavailable, say so explicitly — never let the
  user assume a mark is official when it is not.
- State how cheap a revision is, so the user knows rewording a line is a minute's work.


---

<a id="appendix-narration-sync"></a>

### Appendix: Narration Sync

*Originally `narration-sync.md`*

### Narration-synchronised pipeline (working reference)

Proven on a 6.5-minute macOS screen recording of a mobile banking + Dynamics 365
contact centre demo (3024x1964 source, 390s raw, mixed windowed/full-screen, no audio),
delivered as a 3:05 narration-synced MP4.

Copy these four files into the project directory and edit only `chapters.py` to revise.

Revision loop:

    python3 gen_vo.py 05-dispute     # regenerate just the reworded line
    python3 build_synced.py
    python3 mix.py

---

#### chapters.py

The only file you edit to revise. Each chapter is one narration line plus the source
cuts that show what the line describes.

```python
"""Chapter definitions: narration line + the raw-master source cuts it describes.

Each chapter's video is time-fitted to its own narration so the picture always
shows what the voice is describing.

cuts: list of (start, end, mode) in raw-master.mov seconds.
mode: P = phone-only crop, W = windowed browser, F = macOS full-screen
"""

CHAPTERS = [
    dict(
        id="01-open",
        text="Meet John. He's a retail banking customer, and he's just opened his US Bank mobile app.",
        cuts=[(0.6, 4.0, "P")],
    ),
    dict(
        id="02-maya",
        text="Instead of a menu tree, he's greeted by Maya, an AI banking agent who already knows exactly who he is. She greets him by name, in Arabic or English, his choice.",
        cuts=[(9.6, 13.4, "P"), (14.4, 18.4, "P")],
    ),
    dict(
        id="03-faq",
        text="John starts with a simple question. Which credit cards earn frequent flyer miles?",
        cuts=[(27.0, 31.5, "P")],
    ),
    dict(
        id="04-cards",
        text="Maya answers instantly from the bank's own product knowledge, recommending the Fabrikam Guest AltitudeX cards and walking through the travel perks that come with each one.",
        cuts=[(34.5, 40.0, "P"), (44.0, 48.0, "P")],
    ),
    dict(
        id="05-dispute",
        text="Then the conversation turns serious. John has spotted suspicious transactions, and he wants his card blocked.",
        cuts=[(55.4, 60.6, "P")],
    ),
    dict(
        id="06-whichcard",
        text="Because Maya has his full customer context, she doesn't ask him for a card number. She simply shows him the cards he actually holds and asks which one.",
        cuts=[(69.5, 76.2, "P"), (77.2, 80.2, "P")],
    ),
...(remaining chapters follow the same shape)...
```

---

#### gen_vo.py

One Marin audio file per chapter, cached on disk. Pass chapter ids as arguments to
force-regenerate only those. Retries on transient websocket failures.

```python
#!/usr/bin/env python3
"""Generate one narration audio file per chapter via Azure OpenAI Realtime (Marin)."""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path

import websockets

from chapters import CHAPTERS

ENDPOINT = "<your-foundry>.services.ai.azure.com"
DEPLOYMENT = "gpt-realtime-2.1"
API_VERSION = "2025-04-01-preview"
VOICE = "marin"
ROOT = Path(__file__).resolve().parent
OUTDIR = ROOT / "vo"

STYLE = (
    "You are narrating an exciting, premium enterprise banking technology demo. "
    "Use the Marin voice with genuine enthusiasm, confident momentum, bright energy, "
    "and a polished international business tone. Sound genuinely impressed by the "
    "innovation. Keep the pace lively but articulate and clearly enunciated. "
    "This is one line from a longer continuous narration, so do not add any greeting, "
    "sign-off, or extra words. Never sound robotic, flat, theatrical or overacted."
)


def access_token() -> str:
    return subprocess.check_output(
        ["az", "account", "get-access-token", "--resource",
         "https://cognitiveservices.azure.com", "--query", "accessToken", "-o", "tsv"],
        text=True,
    ).strip()


async def speak(token: str, text: str) -> bytes:
    uri = (f"wss://{ENDPOINT}/openai/realtime"
           f"?api-version={API_VERSION}&deployment={DEPLOYMENT}")
    audio = bytearray()
    async with websockets.connect(
        uri, additional_headers={"Authorization": f"Bearer {token}"},
        max_size=None, open_timeout=30, close_timeout=10,
    ) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": VOICE,
                "output_audio_format": "pcm16",
                "instructions": STYLE,
            },
        }))
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message", "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": ("Read the following line verbatim. Do not add, remove, "
                             "summarize, or introduce any words.\n\n" + text),
                }],
            },
        }))
        await ws.send(json.dumps({
            "type": "response.create",
            "response": {
                "modalities": ["audio", "text"],
                "instructions": "Read the supplied line exactly as written.",
            },
        }))
        while True:
            event = json.loads(await ws.recv())
            et = event.get("type", "")
            if et in {"response.audio.delta", "response.output_audio.delta"}:
                audio.extend(base64.b64decode(event["delta"]))
            elif et == "error":
                raise RuntimeError(json.dumps(event, indent=2))
            elif et in {"response.done", "response.completed"}:
                break
    if not audio:
        raise RuntimeError("no audio returned")
    return bytes(audio)


async def main() -> None:
    OUTDIR.mkdir(exist_ok=True)
    token = access_token()
    only = set(sys.argv[1:])
    for ch in CHAPTERS:
        if only and ch["id"] not in only:
            continue
        dest = OUTDIR / f"{ch['id']}.m4a"
        if dest.exists() and not only:
            print(f"  skip {ch['id']} (exists)")
            continue
        for attempt in range(3):
            try:
                pcm = await speak(token, ch["text"])
                break
            except Exception as exc:                      # noqa: BLE001
                print(f"  retry {ch['id']}: {exc}")
                await asyncio.sleep(3)
        else:
            raise SystemExit(f"failed: {ch['id']}")
        raw = OUTDIR / f"{ch['id']}.pcm"
        raw.write_bytes(pcm)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", "24000", "-ac", "1",
             "-i", str(raw), "-c:a", "aac", "-b:a", "192k", str(dest)], check=True)
        raw.unlink()
        dur = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(dest)], text=True).strip())
        print(f"  {ch['id']}: {dur:6.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
```

---

#### build_synced.py

Renders each chapter at natural speed, time-fits it to its narration line with
clamped `setpts`, holds the last frame for any residual gap, and records exact
voiceover offsets to `timeline.json`.

```python
#!/usr/bin/env python3
"""Build a narration-synchronised cut.

For each chapter the video is time-fitted to its own narration line, so the
picture always shows what the voice is describing. Video that is shorter than
its narration is slowed (up to SLOW_MAX) and then holds on its last frame.
Video that is longer is gently sped up (down to FAST_MAX).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from chapters import CHAPTERS

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "raw-master.mov"
WORK = ROOT / "build"
VO = ROOT / "vo"

W, H = 1920, 1248
FPS = 30

VF = {
    "P": "crop=2530:1645:247:175,scale=1920:1248:flags=lanczos,setsar=1",
    "W": "crop=3024:1596:0:224,scale=1920:1013:flags=lanczos,"
         "pad=1920:1248:0:118:black,setsar=1",
    "F": "crop=3024:1930:0:34,scale=1920:1225:flags=lanczos,"
         "pad=1920:1248:0:12:black,setsar=1",
}

LEAD = 0.35      # silence before the narration line starts inside a chapter
TAIL = 0.55      # breathing room after the line ends
SLOW_MAX = 1.9   # never stretch motion more than this
FAST_MAX = 0.80  # never compress motion below this (i.e. max 1.25x speed)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def dur(path: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], text=True).strip())


def main() -> None:
    WORK.mkdir(exist_ok=True)
    for f in WORK.glob("*"):
        f.unlink()

    timeline = []
    parts = []
    clock = 0.0

    for ci, ch in enumerate(CHAPTERS):
        cid = ch["id"]
        vo_file = VO / f"{cid}.m4a"
        vo_dur = dur(vo_file)
        target = LEAD + vo_dur + TAIL

        # --- render this chapter's raw video at natural speed ---
        seg_files = []
        for si, (s, e, mode) in enumerate(ch["cuts"]):
            f = WORK / f"{cid}-s{si}.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-ss", str(s), "-i", str(SRC),
                 "-t", str(round(e - s, 3)), "-vf", VF[mode], "-r", str(FPS),
                 "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-an", str(f)])
            seg_files.append(f)

        joined = WORK / f"{cid}-nat.mp4"
        if len(seg_files) == 1:
            seg_files[0].rename(joined)
        else:
            lst = WORK / f"{cid}-list.txt"
            lst.write_text("".join(f"file '{p.name}'\n" for p in seg_files))
            run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", str(lst), "-c", "copy", str(joined)])
        nat = dur(joined)

        # --- time-fit to the narration ---
        ratio = target / nat
        ratio = max(FAST_MAX, min(SLOW_MAX, ratio))
        fitted = WORK / f"{cid}-fit.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(joined),
             "-vf", f"setpts={ratio:.5f}*PTS,fps={FPS}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p", "-an", str(fitted)])
        fit_dur = dur(fitted)

        # --- hold the last frame if the narration still overruns ---
        final = fitted
        gap = target - fit_dur
        if gap > 0.12:
            still = WORK / f"{cid}-last.png"
            run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.1", "-i", str(fitted),
                 "-frames:v", "1", str(still)])
            hold = WORK / f"{cid}-hold.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(still),
                 "-t", f"{gap:.3f}", "-r", str(FPS), "-c:v", "libx264",
                 "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-vf", "setsar=1", str(hold)])
            merged = WORK / f"{cid}-full.mp4"
            lst = WORK / f"{cid}-hlist.txt"
            lst.write_text(f"file '{fitted.name}'\nfile '{hold.name}'\n")
            run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", str(lst), "-c", "copy", str(merged)])
            final = merged

        actual = dur(final)
        parts.append(final)
        timeline.append(dict(id=cid, start=round(clock, 3),
                             vo_at=round(clock + LEAD, 3),
                             vo_dur=round(vo_dur, 3),
                             nat=round(nat, 3), ratio=round(ratio, 3),
                             dur=round(actual, 3)))
        print(f"{cid:14s} nat {nat:6.2f}  vo {vo_dur:6.2f}  "
              f"x{ratio:4.2f}  -> {actual:6.2f}  @ {clock:7.2f}")
        clock += actual

    lst = WORK / "all.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(ROOT / "body-silent.mp4")])
    (ROOT / "timeline.json").write_text(json.dumps(timeline, indent=2))
    print(f"\nbody-silent.mp4 = {dur(ROOT / 'body-silent.mp4'):.2f}s")


if __name__ == "__main__":
    main()
```

---

#### mix.py

Delays each chapter voiceover to its offset, ducks the music bed under the narration
bus, masters the body, then concatenates the outro so the outro keeps its own sting.

```python
#!/usr/bin/env python3
"""Assemble the narration track at exact chapter offsets, mix with music,
append the Microsoft outro (keeping its own audio sting), and master."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VO = ROOT / "vo"
FINAL = ROOT / "US-Bank-Maya-to-Marco-CCaaS-Demo.mp4"


def dur(p) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], text=True).strip())


def main() -> None:
    tl = json.loads((ROOT / "timeline.json").read_text())
    body = ROOT / "body-silent.mp4"
    body_dur = dur(body)
    outro = ROOT / "outro-project.mp4"
    outro_dur = dur(outro)
    total = body_dur + outro_dur
    print(f"body {body_dur:.2f}s + outro {outro_dur:.2f}s = {total:.2f}s")

    # ---- narration bus: each line delayed to its chapter offset ----
    inputs, chains, labels = [], [], []
    for i, ch in enumerate(tl):
        inputs += ["-i", str(VO / f"{ch['id']}.m4a")]
        ms = int(round(ch["vo_at"] * 1000))
        chains.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms},"
                      f"apad=whole_dur={total:.3f}[v{i}]")
        labels.append(f"[v{i}]")
    n = len(tl)
    chains.append(f"{''.join(labels)}amix=inputs={n}:duration=longest:"
                  f"dropout_transition=0:normalize=0,"
                  f"loudnorm=I=-16:TP=-1.5:LRA=11,"
                  f"apad=whole_dur={total:.3f},asplit=2[nar][key]")

    # ---- music bed ----
    inputs += ["-i", str(ROOT / "music-bed.wav")]
    mi = n
    fade_out_at = max(0.0, body_dur - 2.5)
    chains.append(f"[{mi}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                  f"volume=0.30,afade=t=in:st=0:d=2,"
                  f"afade=t=out:st={fade_out_at:.2f}:d=2.5[mus]")
    chains.append("[mus][key]sidechaincompress=threshold=0.028:ratio=9:"
                  "attack=8:release=420:makeup=1[duck]")
    chains.append("[nar][duck]amix=inputs=2:duration=longest:"
                  "dropout_transition=0:normalize=0:weights='1 0.85',"
                  "loudnorm=I=-16:TP=-1.0:LRA=11,alimiter=limit=0.93,"
                  f"aresample=48000,atrim=0:{body_dur:.3f}[bodyaud]")

    body_audio = ROOT / "body-audio.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs,
                    "-filter_complex", ";".join(chains),
                    "-map", "[bodyaud]", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2", str(body_audio)], check=True)
    print(f"body audio {dur(body_audio):.2f}s")

    # ---- mux body, then concat with the outro (outro keeps its own sting) ----
    body_av = ROOT / "body-av.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(body),
                    "-i", str(body_audio), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "copy", "-shortest",
                    str(body_av)], check=True)

    lst = ROOT / "final.txt"
    lst.write_text(f"file '{body_av.name}'\nfile '{outro.name}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
                    str(FINAL)], check=True)
    print(f"FINAL {dur(FINAL):.2f}s -> {FINAL.name}")


if __name__ == "__main__":
    main()
```

---

#### Supporting snippets

##### Resolve a macOS screen recording filename (U+202F trap)

```bash
# The space before "AM" is U+202F, not ASCII space — literal paths fail.
SRC=$(ls ~/Downloads/Screen\ Recording\ 2026-08-12*11.11.54*.mov | head -1)
cp "$SRC" raw-master.mov
```

##### Detect windowed vs full-screen ranges

```python
import subprocess, numpy as np
# Sample a 10x10 patch bottom-left; light = full-screen app panel, dark = wallpaper/Dock.
# Probe the BOTTOM, never the top: full-screen frames have a dark top strip.
X, Y, FPS = 60, 1948, 2
raw = subprocess.run(
    ["ffmpeg","-v","error","-i","raw-master.mov",
     "-vf",f"fps={FPS},crop=10:10:{X}:{Y}","-f","rawvideo","-pix_fmt","rgb24","-"],
    capture_output=True).stdout
a = np.frombuffer(raw, np.uint8).reshape(-1,10,10,3).mean(axis=(1,2))
for i,(r,g,b) in enumerate(a):
    print(i/FPS, "F" if min(r,g,b) > 150 else "W")
```

##### Crop modes onto one canvas (3024x1964 -> 1920x1248)

```python
VF = {
    "P": "crop=2530:1645:247:175,scale=1920:1248:flags=lanczos,setsar=1",
    "W": "crop=3024:1596:0:224,scale=1920:1013:flags=lanczos,"
         "pad=1920:1248:0:118:black,setsar=1",
    "F": "crop=3024:1930:0:34,scale=1920:1225:flags=lanczos,"
         "pad=1920:1248:0:12:black,setsar=1",
}
# W and F share the same horizontal scale (0.635) so the UI is the same physical
# size across cuts. Vertical padding absorbs the difference.
```

##### Extract a branded outro with its audio sting

```bash
# 1. sample frames near the end to find the scene boundary
for t in 62 65 68 70 72 74 76; do
  ffmpeg -v error -y -ss $t -i source.mp4 -frames:v 1 -vf "scale=480:-1" o$t.png; done
# 2. binary-search a few timestamps to pin the transition, then extract
ffmpeg -y -ss 72.4 -i source.mp4 -c:v libx264 -crf 17 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart microsoft-standard-outro.mp4
# 3. re-encode to the project canvas — PAD WITH WHITE for Microsoft outros
ffmpeg -y -i microsoft-standard-outro.mp4 \
  -vf "scale=1920:1080:flags=lanczos,pad=1920:1248:0:84:white,setsar=1,fps=30" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k outro-project.mp4
```

##### Sync verification grid

```python
import json, subprocess, pathlib
tl = json.loads(pathlib.Path("timeline.json").read_text())
for ch in tl:
    t = ch["vo_at"] + ch["vo_dur"] / 2      # midpoint of the spoken line
    subprocess.run(["ffmpeg","-v","error","-y","-ss",f"{t:.2f}","-i","final.mp4",
        "-frames:v","1","-vf",
        f"scale=480:-1,drawtext=text='{ch['id']}':x=8:y=8:fontsize=22:"
        "fontcolor=yellow:box=1:boxcolor=black@0.7", f"qc/s-{ch['id']}.png"], check=True)
# Then tile with xstack (NOT the tile filter with %02d, which drops sheets).
```

##### Audio level scan across the timeline

```python
import subprocess
for a, b in [(0,5),(60,65),(120,125),(170,175),(180,183),(183,185)]:
    err = subprocess.run(["ffmpeg","-hide_banner","-ss",str(a),"-t",str(b-a),
        "-i","final.mp4","-vn","-af","volumedetect","-f","null","-"],
        capture_output=True, text=True).stderr
    print(a, b, [l.split(":")[-1].strip() for l in err.splitlines()
                 if "mean_volume" in l or "max_volume" in l])
```


#### Overlay rails and animated cards (learned the hard way)

##### `fade=in:alpha=1` silently does nothing on a single-frame PNG input
An `-i card.png` input is **one frame at PTS 0**. `overlay` holds that frame for the whole
clip, but `fade` only ever sees PTS 0, so alpha stays at the start of the ramp — i.e. **zero**,
forever. The card is invisible in the exact chapter it was supposed to animate into, and
appears (correctly) only in later chapters where no fade is applied.

Always loop the input you intend to fade:

```
# fading card
-loop 1 -framerate 30 -t <chapter_duration> -i card5.png
# static (already-revealed) cards need no loop
-i card1.png
```

##### Composite the rail AFTER the setpts time-fit
If you overlay before time-fitting, `setpts` stretches the fade too and the animation speed
varies per chapter. Render backdrop+content -> time-fit -> then a second pass that overlays
the rail with fade times relative to the *final* chapter length.

##### Killing black bars without cropping away UI
Side-cropping a 3024x1964 recording to 16:9 clips real UI (side panels, Copilot rails).
Instead composite onto the target canvas over a blurred copy of the same frame:

```
[0:v]split=2[bg][fg];
[bg]crop=<mode>,scale=1920:1080,boxblur=30:2,eq=brightness=-0.10:saturation=0.6[b];
[fg]crop=<mode>,scale=1860:-2:flags=lanczos[f];
[b][f]overlay=(W-w)/2:(H-h)/2[out]
```

Scale **every** mode's foreground to the *same* width (1860) so the UI does not visibly
resize when the recording toggles between windowed and full-screen.

For phone-only chapters, crop just the phone body, place it on one side, and use the
remaining space for the card rail — no need to shrink the phone.

#### Screen-recording artifacts hide in the *desktop*, not just the app

macOS notification / Teams meeting-reminder popups look like stray window chrome
(they carry their own red-yellow-green traffic lights) and reviewers report them as
"I can still see minimize/maximize". They can be sub-2-second and invisible in a
1-fps contact sheet.

Detect them by diffing a small greyscale patch of the popup region against a known
"popup present" reference, stepping 0.25 s:

```python
BOX = "700:120:2180:1380"     # raw coords of the popup title strip
def g(t):
    out = subprocess.check_output(["ffmpeg","-v","error","-ss",f"{t}","-i",SRC,
        "-frames:v","1","-vf",f"crop={BOX},scale=70:12",
        "-f","rawvideo","-pix_fmt","gray","-"])
    return np.frombuffer(out, dtype=np.uint8).astype(float).reshape(12,70)
```

A near-zero mean absolute difference means the popup is on screen. Use a **tight**
box: a large box also matches unrelated layout changes and produces false ranges.
Then move every overlapping cut clear of the range with ~1 s of margin.

#### Don't crop the bottom to dodge the Dock without checking what else is down there

Agent-desk UIs put the compose box, quick replies and channel actions at the very
bottom of a panel. In this recording the action bar sat at raw y≈1900 while the
Dock top was y≈1837 — so a single "safe" bottom crop either ate the Dock **or** the
controls being demoed, depending on window mode. Measure both per mode:

- full-screen: no Dock, so crop right down to the action bar
- windowed: crop must stop above the Dock, but the window's own bottom is higher anyway

Then pick **one common foreground width** for both modes so the UI never changes
size. The width is bounded by the *tallest* crop still fitting 1080 px:
`common_w = 1080 * src_w / tallest_crop_h`. Anything wider makes the tall mode
overflow and forces per-mode scaling — which is exactly the "constant resizing"
artifact reviewers notice.

#### Keep the subject where the user framed it

When adding an overlay rail, resist moving the subject. If the source already has
dead space (here, wallpaper to the left of an iPhone simulator), crop a 16:9 window
that leaves the subject in its original position and size the overlay to fit the
space that already exists. Moving the subject reads as a heavier edit than it is and
is the first thing a reviewer objects to.

#### Iconography follows the story, not the plumbing

A reviewer may want every step badged with the *orchestrator's* logo (Copilot Studio)
even when the underlying service differs (Azure SQL, Azure OpenAI), keeping the
service name in the card subtitle. Keep icon choice and copy as separate fields in
the card definition so this is a one-line change.

#### A long freeze-hold before the outro reads as "the outro is missing"

If a closing chapter has far less source than narration, the freeze-hold can run for
several seconds and viewers perceive the frozen app screen as the start of the outro.
Give the final chapter enough source that the hold stays under ~2 s, splitting the cut
around any artifact rather than accepting a single short range.

#### "The outro is missing" is almost always a concat/timestamp fault

If the body is assembled with the **concat demuxer + `-c copy`** (which it is, in this
pipeline - 20 identically encoded chapters), then the outro must be encoded with the
**exact same parameters** and appended the same way. Three things all fail:

1. **copy-concat of a differently encoded outro** - two independent H.264 segments in
   one container. ffprobe reports the full duration and ffmpeg decodes it fine, so it
   looks correct in every automated check, but QuickTime/Preview/Quick Look stop at
   the first segment's end. The reviewer sees no outro.
2. **Re-encoding across the join with the `concat` filter** - inherits the timestamp
   discontinuities from the copy-concatenated body. Observed: a 4.57 s outro stretched
   to 7.97 s of timeline (123 frames spread over 8 s of PTS).
3. **Adding `setpts=PTS-STARTPTS` after `fps=30` to fix (2)** - overcorrects and drops
   frames; output came out *shorter* than the body alone.

The fix that works: keep one homogeneous video chain.

```bash
# outro video, encoded EXACTLY like every chapter
ffmpeg -i outro.mp4 -an -vf "scale=1920:1080,setsar=1,fps=30,format=yuv420p" \
  -r 30 -fps_mode cfr -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p outro-silent.mp4
# outro sting extracted separately
ffmpeg -i outro.mp4 -vn -c:a aac -b:a 192k -ar 48000 -ac 2 outro-sting.m4a
```

Append `outro-silent.mp4` to the chapter list in the same copy-concat, and mix the
sting into the master audio bus with `adelay=<body_dur_ms>`. One video stream, one
audio stream, one mux.

**Verify with frame count, not duration**: `expected == round(total_seconds * fps)`.
Duration alone hides both the stretch and the drop.

```bash
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=nb_read_frames,duration,avg_frame_rate -of csv=p=0 out.mp4
```

#### Trim a lifted outro on a luma threshold, not a guess

Binary-searching the "content -> white card" boundary to 0.1 s still left two frames of
the source app UI at the head of the clip - invisible in a contact sheet, obvious when
a reviewer steps the first frames. Sample mean luma at 0.02 s steps across the
boundary and cut on the step change (here 228.0 -> 253.2 at t=72.44), then confirm by
exporting frames 0-3 with `-vsync 0`.
