# Deployment

Azure Container Apps, image built by ACR Tasks (no local Docker needed), everything described
in bicep so re-deploys are idempotent.

## Dockerfile

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

## bicep (`infra/main.bicep`)

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

## deploy.sh

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

### The two-pass deploy

You cannot build into a registry that doesn't exist. Pass 1 provisions with a placeholder (or
the currently running image, on re-deploys); pass 2 rolls to the freshly built tag.

### Unique tags are mandatory

Container Apps compares the template and **creates no revision if it is byte-identical**.
`:latest` therefore deploys nothing, silently, and you debug "my fix didn't work" for an hour.
Timestamp every tag.

### Set env vars through bicep only

Never `az containerapp update --set-env-vars`. It works, and the next bicep deploy wipes it.
Every variable belongs in `main.bicep` with a parameter fed from `.env`.

---

## `.env` discipline

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

## Azure failure modes that are lies

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

## Verify after every deploy

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

## Cost

Roughly **$35–60/month**: Container Apps 0.5 vCPU / 1 GiB pinned at one replica (~$30–45), ACR
Basic (~$5), Log Analytics (~$3 at low volume). Scaling to zero saves ~$30 but adds a cold
start — keep `minReplicas: 1` for anything you demo.

Tear down: `az group delete -n "$RG" --yes --no-wait`.
