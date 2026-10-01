---
name: "build-d365"
description: "Build end-to-end Microsoft Dynamics 365 / Power Platform demos programmatically on a demo tenant via the Dataverse Web API: solutions, tables, columns, relationships, forms and form XML surgery, collapsible form headers, views, model-driven apps and sitemaps, BPFs, custom HTML web resources that read and write live Dataverse data, PCF controls, Power Automate cloud flows, Copilot Studio AI agents (Standard and GitHub Copilot harness), Dataverse MCP tools, Azure AI Foundry agents, and demo data s"
---

You are building a polished Microsoft Dynamics 365 / Power Platform demo on a demo tenant.
Treat it as a real engineering project, not advice — install tooling, write scripts, hit the
Dataverse Web API directly, and verify before declaring anything done.

Deep reference files live next to this skill. Read them on demand — do not guess when one covers the topic:
- `~/.copilot/m-skills/build-d365/reference/forms-schema-apps.md` — tables, columns, relationships, form XML,
  views, BPFs, appmodules/sitemaps, solution lifecycle, demo reset
- `~/.copilot/m-skills/build-d365/reference/power-automate.md` — cloud flows via `workflow.clientdata`,
  connection references, triggers, approvals, expression gotchas
- `~/.copilot/m-skills/build-d365/reference/ai-agents.md` — Copilot Studio `bot`/`botcomponent`, YAML dialect,
  tools, MCP, publishing, harness fork, Azure AI Foundry
- `~/.copilot/m-skills/build-d365/reference/web-resources.md` — HTML/JS web resources, Xrm in iframes, $batch,
  CDN/CSP, bridges, print
- `~/.copilot/m-skills/build-d365/reference/pcf.md` — PCF authoring, manifests, binding via form XML, importing
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
3. SCHEMA, FORMS, VIEWS, APPS  (details: reference/forms-schema-apps.md)
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
4. POWER AUTOMATE FLOWS  (details: reference/power-automate.md)
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
5. AI AGENTS  (details: reference/ai-agents.md)
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
