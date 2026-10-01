# MCP server

Node 22 + TypeScript + `@modelcontextprotocol/sdk` over **streamable HTTP**. This is the only
transport Copilot supports for remote MCP servers — not stdio, not SSE-only.

## Dependencies

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

## Dataverse client (`src/dataverse.ts`)

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

## Dataverse setup (once per org)

1. **App registration** in Entra → client secret.
2. **Application user** in Power Platform admin centre → the org → Users → *Application users* →
   New, pick the app registration, assign **System Administrator** (or a scoped role for prod).
3. Verify end to end before writing any tool code:

```bash
node -e "import('./dist/dataverse.js').then(m=>m.dv('accounts?\$top=1').then(r=>console.log(r.value[0].name)))"
```

If this fails, nothing downstream can work. Fix it here.

---

## Server skeleton (`src/index.ts`)

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

### Tool shape

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

### Helper: resolve a partial payload into a full one

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

## HTTP host

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

## Fail loudly on startup

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

## Testing the server directly

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
