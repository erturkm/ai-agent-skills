# Custom HTML/JS Web Resources in Model-Driven Apps — Field Notes

Mined from: fsi-client-360, corporate-lending (webresources/, scripts/), Contoso-Customer360.html,
northwind-customer360, airline-customer360, us-bank-customer360, m42-cerner-c360,
dataverse-generative-ui-demo, cpq/webres, market-data-hub, crew-dashboard.

## 1. Deployment mechanics (webresourceset)

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

## 2. Embedding on a form (form XML, no designer)

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

## 3. Getting Xrm inside the iframe

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

## 4. Reading/writing data

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

### Hand-rolled $batch (no client-side Xrm.WebApi batch helper exists)
- outer `batch_<uuid>` boundary + inner `changeset_<uuid>`, each op a sub-request with `Content-ID`.
- Optimistic concurrency: every PATCH carries `If-Match: <@odata.etag>`; assert `/^W\/"\d+"$/` on the etag
  before sending (hard guard against stale/missing etags).
- Parse statuses via `result.matchAll(/HTTP\/1\.[01] (\d{3})/g)`; a `412` anywhere -> show
  "Someone changed these records. Reset to reload before saving." rather than a generic error.
- Tree invariants: when re-parenting a self-referencing hierarchy (e.g. `contacts.fsi_reportsto`), include a
  no-op PATCH on every ancestor in the SAME changeset purely to take locks and prevent concurrent cycles.
- Set `contactid` client-side (client-generated GUID) so new nodes can be referenced by other ops in the same batch.

### Files / attachments
```js
xrm.WebApi.createRecord('annotation', {
  documentbody: b64, filename, mimetype, subject,
  "objectid_account@odata.bind": "/accounts(<guid>)"
});
// download
const n = await xrm.WebApi.retrieveRecord('annotation', id, '?$select=documentbody,mimetype,filename');
a.href = 'data:' + n.mimetype + ';base64,' + n.documentbody;
```

### Demo data hygiene
Seed `account -> opportunity -> task/appointment` chains via createRecord + @odata.bind; prefix demo-only
record names with `*` (e.g. `"*First Solar MENA"`) and keep an `isDemoName()` helper so seeded rows can be
filtered/cleaned later in a shared org.

## 5. Cross-frame messaging & Power Apps code apps

Bridge pattern (HTML web resource hosts a Power Apps **code app** in a nested iframe so the code app can
still use Xrm navigation):
- generate `bridgeId` via `crypto.randomUUID()` to correlate request/response
- **strictly validate origin** before acting: protocol `https:` AND hostname exactly `apps.powerapps.com`
  or ending `.powerplatformusercontent.com` (postMessage `'*'` targets are otherwise spoofable)
- child posts `{type:"usb360.navigation.openRecord"}`, bridge calls `Xrm.Navigation`, replies
  `{type:"usb360.navigation.complete", requestId, success}`

Cosmetic-only messages (e.g. collapse the form header) can use `postMessage({...},'*')` since no sensitive
payload or action is involved.

## 6. CDN blocking -> bundle libraries as web resources

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

## 7. Print / PDF / export

No jsPDF/html2pdf — use the browser's native print pipeline:
- auto-print on load with a settle delay: `window.addEventListener('load',()=>setTimeout(()=>window.print(),250))`
  (the 250ms lets layout paint before the print dialog captures it)
- or build a standalone HTML string with an inline print stylesheet (`@media print{button{display:none}}`),
  `w = window.open()`, `w.document.write(html)`, then `window.print()` inside that popup — keeps dashboard
  chrome out of the printed output.

## 8. Calling live external APIs from a web resource

- If the upstream returns `Access-Control-Allow-Origin: *` you can call it directly from the browser with
  zero middleware — verify per vendor before building a relay.
- Slow/unbounded upstream queries must load out-of-band with a skeleton + live timer so they never block the
  rest of the UI (one FHIR query ignored `_count`, took ~35s and sometimes 504'd).
- Surface upstream quirks transparently (a "data quality" panel, a provenance toggle showing real HTTP status
  and latency) instead of hiding them — it materially increases credibility with technical stakeholders.

## 9. HTML web resource vs PCF vs code app

- HTML web resource: full-tab/full-bleed dashboards, cockpits, free-form layout, external API calls, rapid
  iteration (PATCH content + PublishXml, no build/push cycle). Default choice for demos.
- PCF: when the control must sit in a standard field/section context and be schema-bound, form-designer
  friendly, strongly typed manifest, or reused as a dataset/subgrid control.
- Power Apps code app: when you want the newer code-app tooling/dev experience — embed it via the bridge
  web-resource pattern above because code apps have no Xrm context of their own.
