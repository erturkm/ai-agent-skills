---
name: "copilot-mcp-app"
description: "Build a Microsoft 365 Copilot declarative agent backed by a remote MCP server (an 'MCP App') that reads and writes live Dataverse / Dynamics 365 data and renders rich interactive D365-styled React widgets inside Copilot chat. Covers the MCP server with openai/outputTemplate widget binding, the Dataverse S2S client, the React widget and window.openai host bridge, the agent app package (manifest + declarativeAgent + ai-plugin), Azure Container Apps deployment, Graph app-catalog publishing, a revertible write journal for demo safety, and a local screenshot preview harness. Use whenever someone wants to build, extend, debug or demo a Copilot agent with custom UI, mentions declarative agent, MCP app, MCP server, Copilot widget, Copilot extensibility, agent app package, or wants D365 data surfaced natively in M365 Copilot chat."
---

You are building a **Copilot MCP App**: a declarative agent for Microsoft 365 Copilot whose
actions are served by a remote MCP server, and whose tool results render as an interactive
React widget *inside the Copilot conversation* — not as text, not as an Adaptive Card.

Treat this as an engineering project. Write the code, deploy it, call the live endpoints and
verify what actually renders before declaring anything done. Most failures in this stack are
silent: the agent publishes fine and simply answers in prose while your widget never appears.

Deep reference files live next to this skill. Read them on demand — do not guess when one
covers the topic:

- `~/.copilot/m-skills/copilot-mcp-app/reference/mcp-server.md` — MCP server, tool + resource
  registration, the widget binding contract, Dataverse S2S client, streamable HTTP transport, CORS
- `~/.copilot/m-skills/copilot-mcp-app/reference/widget.md` — React widget, the `window.openai`
  host bridge, single-file bundling, D365 visual shell, local preview + screenshots
- `~/.copilot/m-skills/copilot-mcp-app/reference/agent-package.md` — manifest.json,
  declarativeAgent.json, ai-plugin.json, writing instructions that actually drive tools,
  templating, publishing via Graph, and every publish error you will hit
- `~/.copilot/m-skills/copilot-mcp-app/reference/deploy.md` — bicep, Azure Container Apps,
  ACR build, the deploy script, and the Azure failure modes that are lies
- `~/.copilot/m-skills/copilot-mcp-app/reference/demo-safety.md` — revertible write journal,
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
See the reference files — this specific trap appears in both `deploy.md` and `agent-package.md`.

**Look at the rendered screenshot, not the DOM snapshot.** Accessibility snapshots miss
cosmetic defects — an empty chip rendering as a stray "—" is invisible in the DOM and obvious
on a projector. The preview harness in `reference/widget.md` exists for this.

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
`reference/demo-safety.md` **before writing the first write tool**. It covers:

- a JSONL write journal that makes every change revertible in one tool call
- a guard that makes pre-existing records read-only while still allowing the journey to run
- `list_demo_changes` / `revert_demo_changes` tools so the presenter can clean up on stage
- display-name masking, if the demo goes on a public stage and the real customer cannot be named

The ordering matters: **the journal must exist before any write tool does.** Retrofitting it
means you cannot revert the writes you already made.
