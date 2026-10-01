---
name: "build-d365"
description: "Build end-to-end Microsoft Dynamics 365 / Power Platform demos programmatically on a demo tenant via the Dataverse Web API: solutions, tables, columns, relationships, forms and form XML surgery, collapsible form headers, views, model-driven apps and sitemaps, BPFs, custom HTML web resources that read and write live Dataverse data, PCF controls, Power Automate cloud flows, Copilot Studio AI agents (Standard and GitHub Copilot harness), Dataverse MCP tools, Azure AI Foundry agents, and demo data s"
---


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

## Appendix: Ai Agents

*Originally `reference/ai-agents.md`*

## AI Agents on Copilot Studio / Dataverse — Field Notes from the Workspace

Sources: `agentic-credit/` (HANDOVER.md, BUILD-PLAN.md, BINDING-CHECKLIST.md, `scripts/p5*`–`p76*`), `airline-workshop/reference/copilot-studio-tool-schemas.md`, `meeting-intelligence/scripts/create_agent.py`, `CaseProcessConfigurator/`+`SalesProcessConfigurator/` (`step49`/`step52`/`step53`, `agent_invoke.py`), `market-data-hub`/`market-data-hub-v2` (`deploy_v2_agents.py`, `deploy_foundry_orchestrator.py`), `CRMCopilot/README.md`, `dataverse-generative-ui-demo/README.md`, `scripts/ivr_08_bot_topics.py`.

### 1. Creating an agent as raw Dataverse rows

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

### 2. The Copilot Studio YAML dialect (in `botcomponent.data`)

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

### 3. MCP: exact working shape, and why scripted MCP tools come out empty

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

### 4. WorkflowTool backing flow — cannot fully register via API

`workflow` Dataverse row: `category: 5` (Modern Flow), `type: 1` (Definition), `statecode: 1`/`statuscode: 2` (Activated), `primaryentity: none`. `clientdata.properties.definition.triggers.manual = {type: Request, kind: Skills}` ("When an agent calls the flow"); response action same `kind: Skills`. Cloud flows as Dataverse rows **bypass** the `service.flow.microsoft.com` consent failure (`AADSTS65002`) that blocks the plain Power Automate REST API.

**Critical defect (14 in HANDOVER.md):** a flow tool cannot be *fully* created through the Dataverse Web API. The `botcomponent` row is only half the registration — Copilot Studio's designer writes an additional binding **outside `botcomponent.data`**. Proof: an API row patched byte-identical to a working UI row still threw `FlowNotFound: The flow with id <guid> was not found in the bot definition` at runtime (visible in the M365 Copilot channel only as the generic "the bot can't talk for a while"). Fix used in this workspace: **re-add all flow tools through the Copilot Studio UI** (automated with Playwright), then patch in the missing `connectionProperties` block via API — necessary but not sufficient alone.

`BINDING-CHECKLIST.md` confirms the same rule generally: **"Tools added to agents through the Dataverse API in this org publish as empty shells that report 'no tools available'"** — the two remaining flow tools had to be added by hand in Copilot Studio UI, no API workaround found.

### 5. Publishing programmatically

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

### 6. Direct-invoke / runtime endpoints (verified live)

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

### 7. Standard harness vs GitHub Copilot harness — the routing fork

`CaseProcessConfigurator/step49_agent_flow.py` and `step52_hybrid_test.py` document a production Power Automate flow that forks based on harness because **each is reachable through a different connector**:
| Harness | `bot.template` | Reachable via |
|---|---|---|
| Standard | `default-*` | Copilot Studio connector, `ExecuteCopilotAsyncV2` (`shared_microsoftcopilotstudio`) |
| GitHub Copilot | `cliagent-*` | Agent-node connector, `InvokeAgent` (`shared_agentnode`) — same connector the Copilot Studio workflow "Agent node" uses internally |

**The dangerous failure mode:** calling a `cliagent-*` agent through the Standard `ExecuteCopilotAsyncV2` route does **not** fail loudly. The agent answers with the literal string *"This action doesn't support agents built with the GitHub Copilot harness"* **as its own reply**, the connector reports success, the run is green, and that refusal string gets written onto downstream records (task notes, etc.) as if it were a real agent finding. The Entra direct-invoke conversations API gives the same silent refusal. Only an end-to-end functional test (not a green flow run) catches this — `step52_hybrid_test.py` asserts on `REFUSAL = "doesn't support agents built with the github copilot harness"` substring as its canary.

Practical rule embedded in flows: check `bot.template` string prefix at runtime/design-time and branch; never assume "published" implies "reachable the way you expect."

Generative orchestration (parent → connected-child delegation) is a **toggle**, not a rebuild: **Settings → Generative AI → Generative orchestration** on the parent agent + republish. Connected agents normally *require* this for automatic delegation — on Standard orchestration the parent may just answer itself instead of handing off (observed and deliberately left this way in agentic-credit).

### 8. Azure AI Foundry agents (market-data-hub-v2 `deploy_foundry_orchestrator.py`)

- Two Foundry "Agents API" surfaces exist: legacy `/assistants`, and the new **Agents API** (`api-version=v1`, exposes agent versioning) — `PUT /agents/{name}`, `POST /agents/{name}/versions`.
- Model-vs-transport quirks (verified against a specific Foundry account, 2026-09-07): `gpt-6-astra` **500s on Agents Service** for even trivial prompts, but works fine on **direct chat completions**; `gpt-4.1`/`gpt-5-mini` work on Agents Service. `gpt-6-astra` also **rejects `reasoning.effort` and the `web_search_preview` tool**.
- Structured output support differs by model: `gpt-6-astra` supports `response_format: json_object` (valid JSON, not exact shape) but **not** `json_schema`/`strict`; `gpt-5.6-sol` and `gpt-4.1` support strict `json_schema` on the Agents API.
- **Strict `json_schema` requires `additionalProperties: false` on every object AND every property listed in `required`** (no true optionality — express optional fields as nullable types instead). A recursive `walk()` helper auto-derives the strict variant from a lenient schema.
- Invocation goes through the **project-scoped** `/openai/v1/responses` endpoint (`https://{account}.services.ai.azure.com/api/projects/{project}/openai/v1/responses`) — the same path directly under the account host (no project segment) does **not** resolve agent references.
- Explicitly pass `"tools": []` — project defaults can otherwise silently inject `web_search_preview`, which some models reject outright.
- Auth scope: `https://ai.azure.com/.default`.
- Design pattern: keep the LLM **stateless with no tools** for a pure JSON-fan-in synthesizer (no need for Agent Service threads/tool-calling machinery) — call it directly from chat completions and mirror that call from a Power Automate HTTP action so both paths stay in lockstep.
- Anti-hallucination pattern in the schema itself: every "modelled/estimated" numeric field carries a sibling `"basis": {"enum":["modelled"]}` flag so the UI can visibly badge inferred numbers, and a validation script asserts `coverage=="none"` and no invented wallet numbers when input data is empty (fail-closed, not fail-plausible).

### 9. MCP-as-a-data-source for orchestration (market-data hub)

- Each of 6 parallel Copilot Studio specialist agents queries the **market-data MCP connector** independently, each writing its own result row (`envelope`, tools actually called, evidence count).
- **Silent-degrade gotcha:** the market-data OAuth refresh token expires periodically → connection state `Unauthorized`/`invalid_grant`. When Copilot Studio can't enumerate MCP tools, **the planner quietly falls back to the built-in `UniversalSearchTool`**, returning `{"search_result": null}` in ~60ms, and the flow still writes `status = Completed` — **a green status with an empty report**. Diagnose by inspecting the run's `DynamicPlanReceived → value.steps`: healthy shows `MCP:<agent>.action.MARKETDATA-...:<tool>`; broken shows `P:UniversalSearchTool`.
- `PublishAllXml` frequently times out on large solutions — use targeted `PublishXml` with the specific web-resource GUID instead.

### 10. Instructions / prompt-engineering lessons for tool-calling agents (agentic-credit defects 29–35, 15–28)

- **The orchestrator's completion/auto-fill behaviour beats instruction text.** If an agent keeps asking the user for an optional input despite "never ask" instructions, the fix is **unbinding the input in the tool schema**, not more prompt wording (defect 29). Verify a literal terminal default exists before unbinding, so no real computed value is silently discarded.
- **Producer/consumer output↔input name mismatches look identical to the unbind bug** but are the wrong fix target — rename the consuming tool's input to match the producer's output name (defect 30).
- **`AutomaticTaskInput` handles JSON `number` but silently fails on `integer`** — retype every integer trigger input to `number`, wrap with `int()` server-side for Dataverse Whole Number columns (defect 16). Watch for double-wrapping `int(coalesce(int(X),0))` which throws on null.
- Power Automate expression-library gotchas that produce **silently wrong numbers, not errors**: `div()` does integer division when both operands are ints (wrap the numerator in `float()`); `abs()` **does not exist** in Power Automate (`if(less(X,0),mul(X,-1),X)` instead) — an unknown function is not rejected at save time, only throws at runtime as a generic `BadGateway`. `toLower()` throws on a non-string; canonicalize with `toLower(trim(coalesce(string(...),'')))`.
- Copilot Studio sends **only the trigger inputs the model actually filled** — `triggerBody()['x']` on an omitted optional input hard-fails; always `coalesce(triggerBody()?['x'], default)`.
- `UpdateRecord` (PATCH) **upserts** — an update flow keyed on an id the agent cannot know for a "cold" record will silently *create* an orphan row carrying that GUID. Use find-or-create keyed on a natural id instead.
- **"A green run is not evidence of a correct number."** Integer division, stale option-set/gate mapping, and currency-unit mismatches (USD amount tested against AED thresholds) all returned HTTP 200 with a confidently wrong narrated answer.
- Diagnostic order for a broken flow tool: (1) Copilot Studio **test pane** — names the exact flow GUID and failure (the M365 Copilot channel does not); (2) Power Automate **28-day run history** on the flow (the Dataverse `flowruns` table only logs *scheduled* runs, useless here); (3) build one reference tool **by hand in the UI** and diff.

### 11. Knowledge sources

Confirmed action available in the classic YAML dialect: `kind: SearchAndSummarizeContent` with `userInput:` + `additionalInstructions:` searching "connected knowledge sources (Dataverse knowledge articles)". UI path noted (`airline-workshop/portal/labs_new.py`): Add-knowledge dialog offers **public website / SharePoint site / file upload** — file-upload path was the one actually used in that lab ("you want the file upload area, not a website or SharePoint site"). No workspace evidence of scripting knowledge-source `botcomponent` rows via API — treated as a UI-only step everywhere it appears (verify).

### 12. Cross-cutting architectural lesson (agentic-credit's core thesis)

"A Copilot Studio agent cannot paint the Dynamics UI." The reliable pattern used throughout: agent → deterministic Power Automate flow (all math) → agent writes typed rows to app tables → a polling web resource (Xrm.WebApi or raw `fetch` to `/api/data/v9.2/<singular-logical-name>`, **not** the plural collection name) repaints the form every few seconds. **The LLM never does arithmetic** — every number is independently reproduced from a transpiled copy of the flow logic (`p3_verify.py`) and asserted against a reference calc engine, closing the credibility gap for a regulated-industry demo. Tools should be **typed and single-purpose** ("write one shape to one table") rather than a generic "write any row" action, and option-set string→integer mapping should happen **inside the flow**, never trusted to the model.


---

<a id="appendix-forms-schema-apps"></a>

## Appendix: Forms Schema Apps

*Originally `reference/forms-schema-apps.md`*

## Dataverse / Model-Driven App Technical Learnings — Field-Mined Briefing

Sources: `CaseProcessConfigurator/{dv.py,step2..21}.py`, `SalesProcessConfigurator/*` (near-identical sibling), `agentic-credit/scripts/{dvx.py,p0_solution.py,p4_ui.py,p4_app.py,p4b_wireapp.py,p32_demoreset.py}`, `corporate-lending/webresources/fsi_corporatelending.js`, `fsi-client-360/scripts/fix-form*.js`, `Bind-PCF-Surgical.ps1`.

### 1. Auth & call plumbing (reusable helper pattern)
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

### 2. Table & column creation (EntityDefinitions)
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

### 3. Relationships / lookups
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

### 4. Form XML editing (surgical, not maker UI)
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

### 5. PCF binding via `<controlDescriptions>` (not the maker UI)
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

### 6. Views (savedquery)
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

### 7. Business Process Flows — no supported "create BPF" API
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

### 8. Model-driven app + sitemap
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

### 9. Command bar / ribbon — actually NOT used
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

### 10. Solution lifecycle
- Publisher+solution creation is minimal and idempotent-checked by `uniquename` first:
```python
body = {'uniquename': SOLUTION, 'friendlyname': 'FSI Agentic Credit', 'version': '1.0.0.0',
        'description': '...', 'publisherid@odata.bind': f'/publishers({PUBLISHER_ID})'}
```
- **Collision-guard pattern before creating a new additive solution** (`p0_solution.py`): hardcode the exact list of new table logical names the project is about to introduce, and abort if any already exists in `EntityDefinitions` (`IsCustomEntity eq true`) — protects against silently colliding with another demo's tables sharing the same publisher prefix (`fsi_`).
- Preflight backup before any change: snapshot existing `systemforms` for the target entity, existing `solutions` list, existing `fsi_` tables, and existing `appmodules` to a timestamped JSON file — a manual "get-ids"/rollback aid rather than an automated revert.
- **Two solutions sharing the same system forms is the real trap called out explicitly**: every downstream form-editing step filters target forms by exact `name` (`"Case for Interactive experience"`, `"Case"`, `"Case for Multisession experience"`) rather than by solution, because system forms (`type eq 2`, main form) are **shared singletons across all solutions on the same entity** — patching them from solution A's script silently mutates what solution B thinks is "its" form. All scripts here explicitly comment "Additive — does not modify any existing form" and instead create a **brand-new named form** (`FORM_NAME = 'Contoso Bank Agentic Credit'`) rather than touching the shared stock form, specifically to sidestep this.
- Solution scoping is done per-call via `MSCRM.SolutionUniqueName` header, not by switching a "current solution" context — every write must pass it explicitly or it lands in Default/Active solution.

### 11. Data seeding / demo lifecycle at scale
- Bulk create/patch uses raw sequential POST/PATCH via the same thin client (no evidence of `$batch`/`ExecuteMultiple` batching in these scripts; they rely on the `_resilient` retry-on-timeout pattern instead of true batching)(verify if larger seed scripts elsewhere use $batch).
- **Safe, reversible demo-data reset** (`p32_demoreset.py`) is the standout pattern:
  - Hard allowlist of exact table logical names ever touched (`AGENTIC`), explicitly **not** a `startswith('fsi_')` prefix match, with an `assert_safe()` that aborts if the allowlist ever collides with a separately maintained `PROTECTED` set of pre-existing customer tables.
  - Every delete/restore is scoped to one parent record via `_fsi_opportunity_value eq {id}` filter — never table-wide.
  - `reset` refuses to run unless a JSON snapshot exists on disk (or `--force`), so a demo can always be put back.
  - `snapshot` strips system columns before saving (`k.startswith('fsi_') and k != pk`), keeping only writable business columns plus a `__id` for traceability.
  - `restore` re-creates via `POST` with an explicit `@odata.bind` back to the parent (`'fsi_Opportunity@odata.bind': '/opportunities(%s)' % opp`) rather than trying to preserve original GUIDs.
  - Staged partial reset (`--stage N`) via a `STAGE` dict mapping table→phase number, so a demo can be rewound to "just before structuring" etc., not only to fully empty.

### 12. Misc / smaller facts
- `webresourcetype` codes confirmed in use: `1` = HTML, `3` = JScript, `11` = SVG.
- Label/localized-label boilerplate (`Label`/`LocalizedLabel` `@odata.type`s) is required on **every** DisplayName/Description field, not optional shorthand.
- `RequiredLevel` shorthand seen: `{"Value":"None"|"ApplicationRequired","CanBeChanged":true,"ManagedPropertyLogicalName":"canmodifyrequirementlevelsettings"}` — the managed-property fields are included even on unmanaged/new attributes in the `dvx.py` helper, defensively, though likely unnecessary at create time (verify necessity).
- Global option sets are avoided in all surveyed scripts — every choice column here is local (`IsGlobal: false`) with a per-entity/per-attribute `OptionSet.Name`.


---

<a id="appendix-pcf"></a>

## Appendix: Pcf

*Originally `reference/pcf.md`*

## PCF (Power Apps Component Framework) Controls — Field Notes

Mined from: pcf/ (herocard, CoverageNotesGallery), corporate-lending/pcf (fsiPremiumGrid,
PipelineDealTracker, customer360), fsi-client-360/Solution, CaseProcessConfigurator (Modern SLA Timer),
Bind-PCF-Surgical.ps1, Bind-CoverageTeamNotesPCF.ps1, northwind/fabrikam customer360 pcf.

### 1. Project layout & toolchain

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

#### macOS toolchain chain (documented in setup.sh)
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

### 2. ControlManifest.Input.xml patterns

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

### 3. Runtime patterns (index.ts)

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

### 4. Binding a PCF to a form/view — the "surgical" pattern

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

### 5. Deploying when pac is unavailable

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

### 6. When PCF beats an HTML web resource (evidenced)

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

## Appendix: Power Automate

*Originally `reference/power-automate.md`*

## Power Automate Cloud Flows via Dataverse Web API — Technical Learnings

### 1. Minimal `workflow` row shape for a modern cloud flow

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

### 2. `clientdata` payload schema (exact shape used everywhere)

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

#### Two binding modes for `connectionReferences` — this is the single most important gotcha found:
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

### 3. `connectionreference` Dataverse row — creating/binding

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

### 4. Trigger patterns

#### Dataverse trigger (row created/modified/deleted)
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

#### HTTP "manual" Request trigger (called from a web resource / external caller)
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

#### "Skills" trigger — the pattern for flows callable from Copilot Studio agents
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

#### Recurrence trigger
- Not directly found in this workspace's scripts (verify — none of the sampled scripts used a `Recurrence` trigger type).

### 5. `$connections` / `$authentication` parameter rule

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

### 6. Approvals / Teams / HTTP action specifics

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

### 7. Dataverse bound actions (`OpenApiConnection` on Dataverse connector)

- `GetItem`: `{"entityName":"opportunities","recordId":"<guid-expr>","$select":"col1,col2"}`
- `ListRecords`: `{"entityName":"annotations","$filter":"<odata-expr>","$select":"...","$top":10}`
- `CreateRecord`: `{"entityName":"fsi_approvalrequests","item/fsi_name":"...", "item/fsi_Opportunity@odata.bind":"@concat('/opportunities(', <id-expr>, ')')"}` — lookup fields use `item/<NavProperty>@odata.bind` with a `/entityset(id)` string built via `concat()`.
- `UpdateRecord`: same `item/<field>` prefix convention; **`UpdateRecord`/PATCH-style semantics upsert** — passing an unknown/synthetic id silently *creates* an orphan row instead of failing (defect #20, agentic-credit HANDOVER.md). Always find-or-create by a natural key (e.g. `opportunity_id`) rather than assuming a record id the caller can't know.
- Child/looping pattern: `Foreach` action with `"foreach": "@outputs('List_votes')?['body/value']"`, inner action reads `@items('Flip_votes')?['fieldname']`.
- `Select` action to reshape a list before sending as attachments: `{"type":"Select","inputs":{"from":"@coalesce(outputs('List_Notes')?['body/value'], json('[]'))","select":{"name":"@item()?['filename']","contentBytes":"@item()?['documentbody']"}}}`.

### 8. Expression / language gotchas (high value)

- **Integer division silently returns 0.** `div(lgd_pct, 100)` where both are ints → 0, no error, run "succeeds" with a wrong number. Fix: wrap the numerator in `float(...)` to force float division: `div(float(x), y)`. Described as "the most dangerous class of defect" — 11 expressions across 4 flows fixed this way (`p15_floatdiv.py`).
- **`toLower()` throws on non-string input.** Model/agent sends booleans as often as strings for the same field. Canonical safe pattern: `toLower(trim(coalesce(string(x),'')))`, then compare against a broad alias set (`'yes'`, `'true'`, `'higher'`, `'up'`, `'1'`). 122 expressions across 9 flows fixed (`p18_stringsafe.py`).
- **Null-safe access**: always `coalesce(triggerBody()?['x'], <default>)` for numbers/booleans, or `triggerBody()?['x']` (with `?`) for strings, never bare `triggerBody()['x']` for optional Skills-trigger inputs.
- **Rounding pattern**: `float(formatNumber(<expr>, 'F2'))` used repeatedly as the canonical "round to N dp and force float" idiom.
- **String concatenation with newlines** inside `concat()` uses literal `\n` inside the Python string (becomes real newline in the JSON) for markdown-style approval card bodies — works fine in Teams/Approvals `details`.
- **Picklist/option-set mapping must come from live metadata, not an assumed list.** A hardcoded gate-name→optionvalue chain silently mapped 'credit approval' to the wrong gate; rebuild the `if()` chain from actual option-set metadata and **update every duplicate copy** (e.g. one embedded in a `$filter` OData string as well as the main mapping) — missing one causes "searches one gate, writes another" (defect #26).
- **Currency/unit mismatches are invisible.** Comparing a USD amount against AED thresholds silently misrouted approval tiers; add explicit currency inputs/normalization rather than assuming a single currency.
- Escaping: JSON string values containing `'` inside OData filters need doubling: `name.replace("'", "''")` before building `$filter=name eq '...'`.

### 9. Activation / solution-awareness / ordering gotchas

- All create/update calls should pass header `MSCRM.SolutionUniqueName: <SolutionName>` so the workflow (and connectionreference) lands in the target solution, not the default.
- Deactivate (`statecode:0,statuscode:1`) before PATCHing `clientdata` on an already-active flow, then reactivate (`statecode:1,statuscode:2`) — the safe idempotent upsert sequence.
- **"Script order matters after any flow regeneration."** One phase (`p14`) re-adds *every* trigger's `required` fields as part of a blanket rule, undoing an earlier narrower fix — rerunning generator scripts out of order can silently reintroduce prior defects (HANDOVER.md "31").
- **A flow "tool" cannot be created via the Dataverse Web API alone in Copilot Studio.** The `botcomponent` row referencing the flow is necessary but not sufficient — the Copilot Studio designer writes an additional binding outside `botcomponent.data`. Symptom: `FlowNotFound: The flow with id <guid> was not found in the bot definition`, surfacing to end users only as a generic "the bot can't talk right now." Fix used: automate the Copilot Studio **UI** (Playwright) to add the tool (Tools → Add a tool → Flow), then patch the resulting YAML by API for cosmetic/description fixes. `connectionProperties` block the API omits must be added afterward (`p11_fixflowbindings.py`) — necessary but still not sufficient by itself.
- **`connectionProperties.mode: "Maker"` tools never fire; must be `"Invoker"`.** All working UI-created tool bindings use `Invoker`.
- **One tool per flow per agent** — a flow already bound to one Copilot Studio agent as a tool is filtered out of the tool picker for other agents (can't reuse the same flow as a tool across two agents without duplicating the flow).
- **Connected-agent handoff structurally ends the orchestrator's turn** — if a specialist agent's flow-backed tool call is the final action, control never returns to the orchestrator; any "then write N more things" instruction to the orchestrator silently never runs. The agent holding data must persist it itself rather than handing back to an orchestrator expected to act on it.
- Diagnosing flow-call failures from a Copilot Studio agent, in priority order: (1) Copilot Studio test pane — names exact flow GUID + failure; (2) Power Automate flow's 28-day run history — shows if/where it failed; (3) Dataverse `flowruns` table (less reliable/immediate).
- No evidence in this workspace of the "designer 404" or "browser autosave clobbering" failure modes specifically — not found (verify with additional searching if needed).

### 10. Calling flows from Copilot Studio / HTML web resources

- Copilot Studio-callable flows use `"kind": "Skills"` on both `Request` trigger and `Response` action (not `"Http"`).
- HTML web resources call flows via the `"kind": "Http"` manual trigger + CORS response headers (`Access-Control-Allow-Origin: *`), with the invoke URL persisted to a Dataverse config record rather than hardcoded.
- Trigger schema properties intended to be filled automatically by Copilot Studio's "dynamically added" input UI use `"x-ms-dynamically-added": true`.
- Skills-trigger property descriptions double as prompt-engineering text read by the orchestrating LLM (e.g., explicit "never ask the user for it" instructions) — this is a reusable technique for controlling agent behavior purely through JSON schema `description` fields.


---

<a id="appendix-web-resources"></a>

## Appendix: Web Resources

*Originally `reference/web-resources.md`*

## Custom HTML/JS Web Resources in Model-Driven Apps — Field Notes

Mined from: fsi-client-360, corporate-lending (webresources/, scripts/), Contoso-Customer360.html,
northwind-customer360, airline-customer360, us-bank-customer360, m42-cerner-c360,
dataverse-generative-ui-demo, cpq/webres, market-data-hub, crew-dashboard.

### 1. Deployment mechanics (webresourceset)

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

### 2. Embedding on a form (form XML, no designer)

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

### 3. Getting Xrm inside the iframe

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

### 4. Reading/writing data

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

#### Hand-rolled $batch (no client-side Xrm.WebApi batch helper exists)
- outer `batch_<uuid>` boundary + inner `changeset_<uuid>`, each op a sub-request with `Content-ID`.
- Optimistic concurrency: every PATCH carries `If-Match: <@odata.etag>`; assert `/^W\/"\d+"$/` on the etag
  before sending (hard guard against stale/missing etags).
- Parse statuses via `result.matchAll(/HTTP\/1\.[01] (\d{3})/g)`; a `412` anywhere -> show
  "Someone changed these records. Reset to reload before saving." rather than a generic error.
- Tree invariants: when re-parenting a self-referencing hierarchy (e.g. `contacts.fsi_reportsto`), include a
  no-op PATCH on every ancestor in the SAME changeset purely to take locks and prevent concurrent cycles.
- Set `contactid` client-side (client-generated GUID) so new nodes can be referenced by other ops in the same batch.

#### Files / attachments
```js
xrm.WebApi.createRecord('annotation', {
  documentbody: b64, filename, mimetype, subject,
  "objectid_account@odata.bind": "/accounts(<guid>)"
});
// download
const n = await xrm.WebApi.retrieveRecord('annotation', id, '?$select=documentbody,mimetype,filename');
a.href = 'data:' + n.mimetype + ';base64,' + n.documentbody;
```

#### Demo data hygiene
Seed `account -> opportunity -> task/appointment` chains via createRecord + @odata.bind; prefix demo-only
record names with `*` (e.g. `"*First Solar MENA"`) and keep an `isDemoName()` helper so seeded rows can be
filtered/cleaned later in a shared org.

### 5. Cross-frame messaging & Power Apps code apps

Bridge pattern (HTML web resource hosts a Power Apps **code app** in a nested iframe so the code app can
still use Xrm navigation):
- generate `bridgeId` via `crypto.randomUUID()` to correlate request/response
- **strictly validate origin** before acting: protocol `https:` AND hostname exactly `apps.powerapps.com`
  or ending `.powerplatformusercontent.com` (postMessage `'*'` targets are otherwise spoofable)
- child posts `{type:"usb360.navigation.openRecord"}`, bridge calls `Xrm.Navigation`, replies
  `{type:"usb360.navigation.complete", requestId, success}`

Cosmetic-only messages (e.g. collapse the form header) can use `postMessage({...},'*')` since no sensitive
payload or action is involved.

### 6. CDN blocking -> bundle libraries as web resources

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

### 7. Print / PDF / export

No jsPDF/html2pdf — use the browser's native print pipeline:
- auto-print on load with a settle delay: `window.addEventListener('load',()=>setTimeout(()=>window.print(),250))`
  (the 250ms lets layout paint before the print dialog captures it)
- or build a standalone HTML string with an inline print stylesheet (`@media print{button{display:none}}`),
  `w = window.open()`, `w.document.write(html)`, then `window.print()` inside that popup — keeps dashboard
  chrome out of the printed output.

### 8. Calling live external APIs from a web resource

- If the upstream returns `Access-Control-Allow-Origin: *` you can call it directly from the browser with
  zero middleware — verify per vendor before building a relay.
- Slow/unbounded upstream queries must load out-of-band with a skeleton + live timer so they never block the
  rest of the UI (one FHIR query ignored `_count`, took ~35s and sometimes 504'd).
- Surface upstream quirks transparently (a "data quality" panel, a provenance toggle showing real HTTP status
  and latency) instead of hiding them — it materially increases credibility with technical stakeholders.

### 9. HTML web resource vs PCF vs code app

- HTML web resource: full-tab/full-bleed dashboards, cockpits, free-form layout, external API calls, rapid
  iteration (PATCH content + PublishXml, no build/push cycle). Default choice for demos.
- PCF: when the control must sit in a standard field/section context and be schema-bound, form-designer
  friendly, strongly typed manifest, or reused as a dataset/subgrid control.
- Power Apps code app: when you want the newer code-app tooling/dev experience — embed it via the bridge
  web-resource pattern above because code apps have no Xrm context of their own.
