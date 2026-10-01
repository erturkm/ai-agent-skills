# Dataverse / Model-Driven App Technical Learnings — Field-Mined Briefing

Sources: `CaseProcessConfigurator/{dv.py,step2..21}.py`, `SalesProcessConfigurator/*` (near-identical sibling), `agentic-credit/scripts/{dvx.py,p0_solution.py,p4_ui.py,p4_app.py,p4b_wireapp.py,p32_demoreset.py}`, `corporate-lending/webresources/fsi_corporatelending.js`, `fsi-client-360/scripts/fix-form*.js`, `Bind-PCF-Surgical.ps1`.

## 1. Auth & call plumbing (reusable helper pattern)
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

## 2. Table & column creation (EntityDefinitions)
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

## 3. Relationships / lookups
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

## 4. Form XML editing (surgical, not maker UI)
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

## 5. PCF binding via `<controlDescriptions>` (not the maker UI)
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

## 6. Views (savedquery)
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

## 7. Business Process Flows — no supported "create BPF" API
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

## 8. Model-driven app + sitemap
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

## 9. Command bar / ribbon — actually NOT used
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

## 10. Solution lifecycle
- Publisher+solution creation is minimal and idempotent-checked by `uniquename` first:
```python
body = {'uniquename': SOLUTION, 'friendlyname': 'FSI Agentic Credit', 'version': '1.0.0.0',
        'description': '...', 'publisherid@odata.bind': f'/publishers({PUBLISHER_ID})'}
```
- **Collision-guard pattern before creating a new additive solution** (`p0_solution.py`): hardcode the exact list of new table logical names the project is about to introduce, and abort if any already exists in `EntityDefinitions` (`IsCustomEntity eq true`) — protects against silently colliding with another demo's tables sharing the same publisher prefix (`fsi_`).
- Preflight backup before any change: snapshot existing `systemforms` for the target entity, existing `solutions` list, existing `fsi_` tables, and existing `appmodules` to a timestamped JSON file — a manual "get-ids"/rollback aid rather than an automated revert.
- **Two solutions sharing the same system forms is the real trap called out explicitly**: every downstream form-editing step filters target forms by exact `name` (`"Case for Interactive experience"`, `"Case"`, `"Case for Multisession experience"`) rather than by solution, because system forms (`type eq 2`, main form) are **shared singletons across all solutions on the same entity** — patching them from solution A's script silently mutates what solution B thinks is "its" form. All scripts here explicitly comment "Additive — does not modify any existing form" and instead create a **brand-new named form** (`FORM_NAME = 'Contoso Bank Agentic Credit'`) rather than touching the shared stock form, specifically to sidestep this.
- Solution scoping is done per-call via `MSCRM.SolutionUniqueName` header, not by switching a "current solution" context — every write must pass it explicitly or it lands in Default/Active solution.

## 11. Data seeding / demo lifecycle at scale
- Bulk create/patch uses raw sequential POST/PATCH via the same thin client (no evidence of `$batch`/`ExecuteMultiple` batching in these scripts; they rely on the `_resilient` retry-on-timeout pattern instead of true batching)(verify if larger seed scripts elsewhere use $batch).
- **Safe, reversible demo-data reset** (`p32_demoreset.py`) is the standout pattern:
  - Hard allowlist of exact table logical names ever touched (`AGENTIC`), explicitly **not** a `startswith('fsi_')` prefix match, with an `assert_safe()` that aborts if the allowlist ever collides with a separately maintained `PROTECTED` set of pre-existing customer tables.
  - Every delete/restore is scoped to one parent record via `_fsi_opportunity_value eq {id}` filter — never table-wide.
  - `reset` refuses to run unless a JSON snapshot exists on disk (or `--force`), so a demo can always be put back.
  - `snapshot` strips system columns before saving (`k.startswith('fsi_') and k != pk`), keeping only writable business columns plus a `__id` for traceability.
  - `restore` re-creates via `POST` with an explicit `@odata.bind` back to the parent (`'fsi_Opportunity@odata.bind': '/opportunities(%s)' % opp`) rather than trying to preserve original GUIDs.
  - Staged partial reset (`--stage N`) via a `STAGE` dict mapping table→phase number, so a demo can be rewound to "just before structuring" etc., not only to fully empty.

## 12. Misc / smaller facts
- `webresourcetype` codes confirmed in use: `1` = HTML, `3` = JScript, `11` = SVG.
- Label/localized-label boilerplate (`Label`/`LocalizedLabel` `@odata.type`s) is required on **every** DisplayName/Description field, not optional shorthand.
- `RequiredLevel` shorthand seen: `{"Value":"None"|"ApplicationRequired","CanBeChanged":true,"ManagedPropertyLogicalName":"canmodifyrequirementlevelsettings"}` — the managed-property fields are included even on unmanaged/new attributes in the `dvx.py` helper, defensively, though likely unnecessary at create time (verify necessity).
- Global option sets are avoided in all surveyed scripts — every choice column here is local (`IsGlobal: false`) with a per-entity/per-attribute `OptionSet.Name`.