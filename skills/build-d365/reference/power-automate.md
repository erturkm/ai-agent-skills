# Power Automate Cloud Flows via Dataverse Web API — Technical Learnings

## 1. Minimal `workflow` row shape for a modern cloud flow

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

## 2. `clientdata` payload schema (exact shape used everywhere)

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

### Two binding modes for `connectionReferences` — this is the single most important gotcha found:
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

## 3. `connectionreference` Dataverse row — creating/binding

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

## 4. Trigger patterns

### Dataverse trigger (row created/modified/deleted)
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

### HTTP "manual" Request trigger (called from a web resource / external caller)
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

### "Skills" trigger — the pattern for flows callable from Copilot Studio agents
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

### Recurrence trigger
- Not directly found in this workspace's scripts (verify — none of the sampled scripts used a `Recurrence` trigger type).

## 5. `$connections` / `$authentication` parameter rule

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

## 6. Approvals / Teams / HTTP action specifics

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

## 7. Dataverse bound actions (`OpenApiConnection` on Dataverse connector)

- `GetItem`: `{"entityName":"opportunities","recordId":"<guid-expr>","$select":"col1,col2"}`
- `ListRecords`: `{"entityName":"annotations","$filter":"<odata-expr>","$select":"...","$top":10}`
- `CreateRecord`: `{"entityName":"fsi_approvalrequests","item/fsi_name":"...", "item/fsi_Opportunity@odata.bind":"@concat('/opportunities(', <id-expr>, ')')"}` — lookup fields use `item/<NavProperty>@odata.bind` with a `/entityset(id)` string built via `concat()`.
- `UpdateRecord`: same `item/<field>` prefix convention; **`UpdateRecord`/PATCH-style semantics upsert** — passing an unknown/synthetic id silently *creates* an orphan row instead of failing (defect #20, agentic-credit HANDOVER.md). Always find-or-create by a natural key (e.g. `opportunity_id`) rather than assuming a record id the caller can't know.
- Child/looping pattern: `Foreach` action with `"foreach": "@outputs('List_votes')?['body/value']"`, inner action reads `@items('Flip_votes')?['fieldname']`.
- `Select` action to reshape a list before sending as attachments: `{"type":"Select","inputs":{"from":"@coalesce(outputs('List_Notes')?['body/value'], json('[]'))","select":{"name":"@item()?['filename']","contentBytes":"@item()?['documentbody']"}}}`.

## 8. Expression / language gotchas (high value)

- **Integer division silently returns 0.** `div(lgd_pct, 100)` where both are ints → 0, no error, run "succeeds" with a wrong number. Fix: wrap the numerator in `float(...)` to force float division: `div(float(x), y)`. Described as "the most dangerous class of defect" — 11 expressions across 4 flows fixed this way (`p15_floatdiv.py`).
- **`toLower()` throws on non-string input.** Model/agent sends booleans as often as strings for the same field. Canonical safe pattern: `toLower(trim(coalesce(string(x),'')))`, then compare against a broad alias set (`'yes'`, `'true'`, `'higher'`, `'up'`, `'1'`). 122 expressions across 9 flows fixed (`p18_stringsafe.py`).
- **Null-safe access**: always `coalesce(triggerBody()?['x'], <default>)` for numbers/booleans, or `triggerBody()?['x']` (with `?`) for strings, never bare `triggerBody()['x']` for optional Skills-trigger inputs.
- **Rounding pattern**: `float(formatNumber(<expr>, 'F2'))` used repeatedly as the canonical "round to N dp and force float" idiom.
- **String concatenation with newlines** inside `concat()` uses literal `\n` inside the Python string (becomes real newline in the JSON) for markdown-style approval card bodies — works fine in Teams/Approvals `details`.
- **Picklist/option-set mapping must come from live metadata, not an assumed list.** A hardcoded gate-name→optionvalue chain silently mapped 'credit approval' to the wrong gate; rebuild the `if()` chain from actual option-set metadata and **update every duplicate copy** (e.g. one embedded in a `$filter` OData string as well as the main mapping) — missing one causes "searches one gate, writes another" (defect #26).
- **Currency/unit mismatches are invisible.** Comparing a USD amount against AED thresholds silently misrouted approval tiers; add explicit currency inputs/normalization rather than assuming a single currency.
- Escaping: JSON string values containing `'` inside OData filters need doubling: `name.replace("'", "''")` before building `$filter=name eq '...'`.

## 9. Activation / solution-awareness / ordering gotchas

- All create/update calls should pass header `MSCRM.SolutionUniqueName: <SolutionName>` so the workflow (and connectionreference) lands in the target solution, not the default.
- Deactivate (`statecode:0,statuscode:1`) before PATCHing `clientdata` on an already-active flow, then reactivate (`statecode:1,statuscode:2`) — the safe idempotent upsert sequence.
- **"Script order matters after any flow regeneration."** One phase (`p14`) re-adds *every* trigger's `required` fields as part of a blanket rule, undoing an earlier narrower fix — rerunning generator scripts out of order can silently reintroduce prior defects (HANDOVER.md "31").
- **A flow "tool" cannot be created via the Dataverse Web API alone in Copilot Studio.** The `botcomponent` row referencing the flow is necessary but not sufficient — the Copilot Studio designer writes an additional binding outside `botcomponent.data`. Symptom: `FlowNotFound: The flow with id <guid> was not found in the bot definition`, surfacing to end users only as a generic "the bot can't talk right now." Fix used: automate the Copilot Studio **UI** (Playwright) to add the tool (Tools → Add a tool → Flow), then patch the resulting YAML by API for cosmetic/description fixes. `connectionProperties` block the API omits must be added afterward (`p11_fixflowbindings.py`) — necessary but still not sufficient by itself.
- **`connectionProperties.mode: "Maker"` tools never fire; must be `"Invoker"`.** All working UI-created tool bindings use `Invoker`.
- **One tool per flow per agent** — a flow already bound to one Copilot Studio agent as a tool is filtered out of the tool picker for other agents (can't reuse the same flow as a tool across two agents without duplicating the flow).
- **Connected-agent handoff structurally ends the orchestrator's turn** — if a specialist agent's flow-backed tool call is the final action, control never returns to the orchestrator; any "then write N more things" instruction to the orchestrator silently never runs. The agent holding data must persist it itself rather than handing back to an orchestrator expected to act on it.
- Diagnosing flow-call failures from a Copilot Studio agent, in priority order: (1) Copilot Studio test pane — names exact flow GUID + failure; (2) Power Automate flow's 28-day run history — shows if/where it failed; (3) Dataverse `flowruns` table (less reliable/immediate).
- No evidence in this workspace of the "designer 404" or "browser autosave clobbering" failure modes specifically — not found (verify with additional searching if needed).

## 10. Calling flows from Copilot Studio / HTML web resources

- Copilot Studio-callable flows use `"kind": "Skills"` on both `Request` trigger and `Response` action (not `"Http"`).
- HTML web resources call flows via the `"kind": "Http"` manual trigger + CORS response headers (`Access-Control-Allow-Origin: *`), with the invoke URL persisted to a Dataverse config record rather than hardcoded.
- Trigger schema properties intended to be filled automatically by Copilot Studio's "dynamically added" input UI use `"x-ms-dynamically-added": true`.
- Skills-trigger property descriptions double as prompt-engineering text read by the orchestrating LLM (e.g., explicit "never ask the user for it" instructions) — this is a reusable technique for controlling agent behavior purely through JSON schema `description` fields.