# AI Agents on Copilot Studio / Dataverse — Field Notes from the Workspace

Sources: `agentic-credit/` (HANDOVER.md, BUILD-PLAN.md, BINDING-CHECKLIST.md, `scripts/p5*`–`p76*`), `airline-workshop/reference/copilot-studio-tool-schemas.md`, `meeting-intelligence/scripts/create_agent.py`, `CaseProcessConfigurator/`+`SalesProcessConfigurator/` (`step49`/`step52`/`step53`, `agent_invoke.py`), `market-data-hub`/`market-data-hub-v2` (`deploy_v2_agents.py`, `deploy_foundry_orchestrator.py`), `CRMCopilot/README.md`, `dataverse-generative-ui-demo/README.md`, `scripts/ivr_08_bot_topics.py`.

## 1. Creating an agent as raw Dataverse rows

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

## 2. The Copilot Studio YAML dialect (in `botcomponent.data`)

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

## 3. MCP: exact working shape, and why scripted MCP tools come out empty

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

## 4. WorkflowTool backing flow — cannot fully register via API

`workflow` Dataverse row: `category: 5` (Modern Flow), `type: 1` (Definition), `statecode: 1`/`statuscode: 2` (Activated), `primaryentity: none`. `clientdata.properties.definition.triggers.manual = {type: Request, kind: Skills}` ("When an agent calls the flow"); response action same `kind: Skills`. Cloud flows as Dataverse rows **bypass** the `service.flow.microsoft.com` consent failure (`AADSTS65002`) that blocks the plain Power Automate REST API.

**Critical defect (14 in HANDOVER.md):** a flow tool cannot be *fully* created through the Dataverse Web API. The `botcomponent` row is only half the registration — Copilot Studio's designer writes an additional binding **outside `botcomponent.data`**. Proof: an API row patched byte-identical to a working UI row still threw `FlowNotFound: The flow with id <guid> was not found in the bot definition` at runtime (visible in the M365 Copilot channel only as the generic "the bot can't talk for a while"). Fix used in this workspace: **re-add all flow tools through the Copilot Studio UI** (automated with Playwright), then patch in the missing `connectionProperties` block via API — necessary but not sufficient alone.

`BINDING-CHECKLIST.md` confirms the same rule generally: **"Tools added to agents through the Dataverse API in this org publish as empty shells that report 'no tools available'"** — the two remaining flow tools had to be added by hand in Copilot Studio UI, no API workaround found.

## 5. Publishing programmatically

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

## 6. Direct-invoke / runtime endpoints (verified live)

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

## 7. Standard harness vs GitHub Copilot harness — the routing fork

`CaseProcessConfigurator/step49_agent_flow.py` and `step52_hybrid_test.py` document a production Power Automate flow that forks based on harness because **each is reachable through a different connector**:
| Harness | `bot.template` | Reachable via |
|---|---|---|
| Standard | `default-*` | Copilot Studio connector, `ExecuteCopilotAsyncV2` (`shared_microsoftcopilotstudio`) |
| GitHub Copilot | `cliagent-*` | Agent-node connector, `InvokeAgent` (`shared_agentnode`) — same connector the Copilot Studio workflow "Agent node" uses internally |

**The dangerous failure mode:** calling a `cliagent-*` agent through the Standard `ExecuteCopilotAsyncV2` route does **not** fail loudly. The agent answers with the literal string *"This action doesn't support agents built with the GitHub Copilot harness"* **as its own reply**, the connector reports success, the run is green, and that refusal string gets written onto downstream records (task notes, etc.) as if it were a real agent finding. The Entra direct-invoke conversations API gives the same silent refusal. Only an end-to-end functional test (not a green flow run) catches this — `step52_hybrid_test.py` asserts on `REFUSAL = "doesn't support agents built with the github copilot harness"` substring as its canary.

Practical rule embedded in flows: check `bot.template` string prefix at runtime/design-time and branch; never assume "published" implies "reachable the way you expect."

Generative orchestration (parent → connected-child delegation) is a **toggle**, not a rebuild: **Settings → Generative AI → Generative orchestration** on the parent agent + republish. Connected agents normally *require* this for automatic delegation — on Standard orchestration the parent may just answer itself instead of handing off (observed and deliberately left this way in agentic-credit).

## 8. Azure AI Foundry agents (market-data-hub-v2 `deploy_foundry_orchestrator.py`)

- Two Foundry "Agents API" surfaces exist: legacy `/assistants`, and the new **Agents API** (`api-version=v1`, exposes agent versioning) — `PUT /agents/{name}`, `POST /agents/{name}/versions`.
- Model-vs-transport quirks (verified against a specific Foundry account, 2026-09-07): `gpt-6-astra` **500s on Agents Service** for even trivial prompts, but works fine on **direct chat completions**; `gpt-4.1`/`gpt-5-mini` work on Agents Service. `gpt-6-astra` also **rejects `reasoning.effort` and the `web_search_preview` tool**.
- Structured output support differs by model: `gpt-6-astra` supports `response_format: json_object` (valid JSON, not exact shape) but **not** `json_schema`/`strict`; `gpt-5.6-sol` and `gpt-4.1` support strict `json_schema` on the Agents API.
- **Strict `json_schema` requires `additionalProperties: false` on every object AND every property listed in `required`** (no true optionality — express optional fields as nullable types instead). A recursive `walk()` helper auto-derives the strict variant from a lenient schema.
- Invocation goes through the **project-scoped** `/openai/v1/responses` endpoint (`https://{account}.services.ai.azure.com/api/projects/{project}/openai/v1/responses`) — the same path directly under the account host (no project segment) does **not** resolve agent references.
- Explicitly pass `"tools": []` — project defaults can otherwise silently inject `web_search_preview`, which some models reject outright.
- Auth scope: `https://ai.azure.com/.default`.
- Design pattern: keep the LLM **stateless with no tools** for a pure JSON-fan-in synthesizer (no need for Agent Service threads/tool-calling machinery) — call it directly from chat completions and mirror that call from a Power Automate HTTP action so both paths stay in lockstep.
- Anti-hallucination pattern in the schema itself: every "modelled/estimated" numeric field carries a sibling `"basis": {"enum":["modelled"]}` flag so the UI can visibly badge inferred numbers, and a validation script asserts `coverage=="none"` and no invented wallet numbers when input data is empty (fail-closed, not fail-plausible).

## 9. MCP-as-a-data-source for orchestration (market-data hub)

- Each of 6 parallel Copilot Studio specialist agents queries the **market-data MCP connector** independently, each writing its own result row (`envelope`, tools actually called, evidence count).
- **Silent-degrade gotcha:** the market-data OAuth refresh token expires periodically → connection state `Unauthorized`/`invalid_grant`. When Copilot Studio can't enumerate MCP tools, **the planner quietly falls back to the built-in `UniversalSearchTool`**, returning `{"search_result": null}` in ~60ms, and the flow still writes `status = Completed` — **a green status with an empty report**. Diagnose by inspecting the run's `DynamicPlanReceived → value.steps`: healthy shows `MCP:<agent>.action.MARKETDATA-...:<tool>`; broken shows `P:UniversalSearchTool`.
- `PublishAllXml` frequently times out on large solutions — use targeted `PublishXml` with the specific web-resource GUID instead.

## 10. Instructions / prompt-engineering lessons for tool-calling agents (agentic-credit defects 29–35, 15–28)

- **The orchestrator's completion/auto-fill behaviour beats instruction text.** If an agent keeps asking the user for an optional input despite "never ask" instructions, the fix is **unbinding the input in the tool schema**, not more prompt wording (defect 29). Verify a literal terminal default exists before unbinding, so no real computed value is silently discarded.
- **Producer/consumer output↔input name mismatches look identical to the unbind bug** but are the wrong fix target — rename the consuming tool's input to match the producer's output name (defect 30).
- **`AutomaticTaskInput` handles JSON `number` but silently fails on `integer`** — retype every integer trigger input to `number`, wrap with `int()` server-side for Dataverse Whole Number columns (defect 16). Watch for double-wrapping `int(coalesce(int(X),0))` which throws on null.
- Power Automate expression-library gotchas that produce **silently wrong numbers, not errors**: `div()` does integer division when both operands are ints (wrap the numerator in `float()`); `abs()` **does not exist** in Power Automate (`if(less(X,0),mul(X,-1),X)` instead) — an unknown function is not rejected at save time, only throws at runtime as a generic `BadGateway`. `toLower()` throws on a non-string; canonicalize with `toLower(trim(coalesce(string(...),'')))`.
- Copilot Studio sends **only the trigger inputs the model actually filled** — `triggerBody()['x']` on an omitted optional input hard-fails; always `coalesce(triggerBody()?['x'], default)`.
- `UpdateRecord` (PATCH) **upserts** — an update flow keyed on an id the agent cannot know for a "cold" record will silently *create* an orphan row carrying that GUID. Use find-or-create keyed on a natural id instead.
- **"A green run is not evidence of a correct number."** Integer division, stale option-set/gate mapping, and currency-unit mismatches (USD amount tested against AED thresholds) all returned HTTP 200 with a confidently wrong narrated answer.
- Diagnostic order for a broken flow tool: (1) Copilot Studio **test pane** — names the exact flow GUID and failure (the M365 Copilot channel does not); (2) Power Automate **28-day run history** on the flow (the Dataverse `flowruns` table only logs *scheduled* runs, useless here); (3) build one reference tool **by hand in the UI** and diff.

## 11. Knowledge sources

Confirmed action available in the classic YAML dialect: `kind: SearchAndSummarizeContent` with `userInput:` + `additionalInstructions:` searching "connected knowledge sources (Dataverse knowledge articles)". UI path noted (`airline-workshop/portal/labs_new.py`): Add-knowledge dialog offers **public website / SharePoint site / file upload** — file-upload path was the one actually used in that lab ("you want the file upload area, not a website or SharePoint site"). No workspace evidence of scripting knowledge-source `botcomponent` rows via API — treated as a UI-only step everywhere it appears (verify).

## 12. Cross-cutting architectural lesson (agentic-credit's core thesis)

"A Copilot Studio agent cannot paint the Dynamics UI." The reliable pattern used throughout: agent → deterministic Power Automate flow (all math) → agent writes typed rows to app tables → a polling web resource (Xrm.WebApi or raw `fetch` to `/api/data/v9.2/<singular-logical-name>`, **not** the plural collection name) repaints the form every few seconds. **The LLM never does arithmetic** — every number is independently reproduced from a transpiled copy of the flow logic (`p3_verify.py`) and asserted against a reference calc engine, closing the credibility gap for a regulated-industry demo. Tools should be **typed and single-purpose** ("write one shape to one table") rather than a generic "write any row" action, and option-set string→integer mapping should happen **inside the flow**, never trusted to the model.