# PCF (Power Apps Component Framework) Controls — Field Notes

Mined from: pcf/ (herocard, CoverageNotesGallery), corporate-lending/pcf (fsiPremiumGrid,
PipelineDealTracker, customer360), fsi-client-360/Solution, CaseProcessConfigurator (Modern SLA Timer),
Bind-PCF-Surgical.ps1, Bind-CoverageTeamNotesPCF.ps1, northwind/fabrikam customer360 pcf.

## 1. Project layout & toolchain

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

### macOS toolchain chain (documented in setup.sh)
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

## 2. ControlManifest.Input.xml patterns

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

## 3. Runtime patterns (index.ts)

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

## 4. Binding a PCF to a form/view — the "surgical" pattern

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

## 5. Deploying when pac is unavailable

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

## 6. When PCF beats an HTML web resource (evidenced)

- No supported "compact" mode exists for stacked quick-view SLA cards — a dataset PCF bound to a single
  `slakpiinstance` subgrid rendered all KPI instances as compact cards in one control and reclaimed vertical
  form space two stacked quick-view forms couldn't.
- Reuse over rewrite: the same installed PCF was reused across two unrelated entities (Case's
  `slakpiinstance_incident` and Task's `slakpiinstance_task`) by *mirroring task deadlines into real
  `slakpiinstance` rows* rather than authoring a second look-alike widget — "make my data look like the shape
  the PCF already understands" avoids a manifest/version bump entirely.
- Generic dataset PCFs with `usage="input"` field-name parameters are the multi-demo reuse strategy behind the
  Customer360 / PremiumGrid control family shared across Contoso Bank, fsi-client-360, Northwind and Fabrikam variants.
