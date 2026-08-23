# Deployment Runbook — Agent Identity Operator

Operational runbook for deploying the Agent Identity Blueprint operator to an AKS cluster.

| | |
| --- | --- |
| **Component** | `agent-identity-operator` |
| **Namespace** | `agent-operator-system` |
| **Type** | Mutating admission webhook (`failurePolicy: Fail`) |
| **Blast radius** | Pod creation in every namespace labelled `agent-enabled=true` |
| **Est. duration** | 15–20 min (first install) |
| **Rollback** | ~2 min (see [Rollback](#7-rollback)) |

---

## ⚠️ Read this first

This operator runs with **`failurePolicy: Fail`**. That is deliberate — it is the mechanism that
guarantees an agent pod cannot start unless the Blueprint API call succeeded. The operational
consequence is:

> **If the operator is unavailable, pod creation in every `agent-enabled=true` namespace is blocked.**

Existing running pods are unaffected — this only gates *new* pod creation. But scale-ups,
rollouts, and node-failure rescheduling will all stall. Two rules follow from this:

1. **Never label a namespace `agent-enabled=true` before the operator is Ready.**
2. **Never scale the operator to zero.** To disable it, delete the webhook configuration
   (step 7.1), not the Deployment.

---

## 1. Prerequisites

| Requirement | Verify with |
| --- | --- |
| `kubectl` v1.28+ | `kubectl version --client` |
| Docker (with buildx) | `docker --version` |
| Cluster admin on target AKS | `kubectl auth can-i create mutatingwebhookconfigurations` |
| Push rights to your registry | `az acr login --name <registry>` |
| Agent Identity Blueprints already created | Out of scope — assumed present |

Confirm you are pointed at the right cluster **before anything else**:

```powershell
kubectl config current-context
kubectl cluster-info
```

Egress check — the operator must reach the Blueprint API. If your cluster restricts egress
(Azure Firewall, NSG, or a proxy), allow `jsonplaceholder.typicode.com:443` first. Verify from
inside the cluster:

```powershell
kubectl run egress-check --rm -it --restart=Never --image=curlimages/curl:8.10.1 -- `
  curl -s -o /dev/null -w "%{http_code}`n" -X POST `
  https://jsonplaceholder.typicode.com/posts `
  -H "Content-Type: application/json" `
  -d '{"userId":1,"id":1,"title":"title","body":"title"}'
```

Expect `201`. Anything else — resolve it now; every agent pod will be denied otherwise.

---

## 2. Build and push the image

```powershell
cd "d:\office work\minimal-kube-operator"

$REGISTRY = "<your-registry>.azurecr.io"
$TAG      = "v0.1.0"
$IMAGE    = "$REGISTRY/agent-identity-operator:$TAG"
```

Run the tests before building. No local Go toolchain is required — everything runs in Docker:

```powershell
docker run --rm -v "${PWD}:/src" -w /src golang:1.23 sh -c "go build ./... && go vet ./... && go test ./..."
```

All packages must report `ok` or `no test files`. Then build and push:

```powershell
az acr login --name $REGISTRY.Split('.')[0]
docker build --platform linux/amd64 -t $IMAGE .
docker push $IMAGE
```

> **Use `--platform linux/amd64`** unless your node pool is ARM. Building on an ARM Mac without
> this flag produces an image that crash-loops with `exec format error` on standard AKS nodes.

Verify the push landed:

```powershell
az acr repository show-tags --name $REGISTRY.Split('.')[0] --repository agent-identity-operator -o table
```

---

## 3. Deploy the operator

### 3.1 Point the manifest at your image

```powershell
(Get-Content deploy/03-deployment.yaml) `
  -replace 'REPLACE_ME/agent-identity-operator:v0\.1\.0', $IMAGE `
  | Set-Content deploy/03-deployment.yaml

Select-String -Path deploy/03-deployment.yaml -Pattern "image:"
```

### 3.2 Dry-run, then apply

```powershell
kubectl apply --dry-run=server -f deploy/
kubectl apply -f deploy/
```

Apply order is handled by the filename prefixes (`01`–`04`): namespace → RBAC → workload →
webhook configuration. Applying the webhook config last means the API server does not start
routing admission traffic until the Deployment exists.

### 3.3 Wait for readiness

```powershell
kubectl -n agent-operator-system rollout status deploy/agent-identity-operator --timeout=180s
kubectl -n agent-operator-system get pods -o wide
```

**Do not continue until both replicas are `Running` and `2/2` ready.**

### 3.4 Confirm the certificate bootstrap

The operator generates its own CA, stores it in a Secret, and patches the `caBundle` into its
own `MutatingWebhookConfiguration`. Verify all three:

```powershell
kubectl -n agent-operator-system get secret agent-identity-operator-webhook-cert

kubectl get mutatingwebhookconfiguration agent-identity-operator-mutating-webhook `
  -o jsonpath='{.webhooks[0].clientConfig.caBundle}' | Measure-Object -Character

kubectl -n agent-operator-system logs deploy/agent-identity-operator | Select-String "caBundle|certificate"
```

The `caBundle` character count must be **greater than zero**. If it is empty, the webhook will
fail TLS verification and — because of `failurePolicy: Fail` — block every agent pod. See
[Troubleshooting](#8-troubleshooting).

---

## 4. Smoke test in an isolated namespace

Validate against a throwaway namespace **before** touching any real agent workload.

```powershell
kubectl apply -f examples/agent-namespace.yaml
kubectl -n agents-payments rollout status deploy/payments-agent --timeout=120s
```

### 4.1 Confirm the identity was injected

```powershell
kubectl -n agents-payments get pod -l app=payments-agent `
  -o jsonpath='{.items[0].spec.containers[0].env}'
```

Expect `AGENT_IDENTITY_ID` set to `3f2504e0-4f89-11d3-9a0c-0305e82c3301`.

### 4.2 Confirm the API call was logged

```powershell
kubectl -n agent-operator-system logs deploy/agent-identity-operator --tail=50 `
  | Select-String "Blueprint API call"
```

Expect a `SUCCESS` line carrying the blueprint ID, HTTP status, and attempt number.

### 4.3 Confirm the negative path

The most important test — a pod carrying a malformed blueprint ID **must be rejected**:

```powershell
kubectl -n agents-payments run bad-agent --image=busybox --restart=Never `
  --annotations="agent.blueprint/id=not-a-guid" -- sleep 300
```

This must fail with an admission error mentioning `agent identity blueprint resolution failed`.
**If this pod is created successfully, stop and investigate** — the webhook is not intercepting
traffic, and agents could start without a validated identity.

### 4.4 Tear down

```powershell
kubectl delete -f examples/agent-namespace.yaml
```

---

## 5. Onboard real agent namespaces

Onboard **one namespace at a time**, verifying each before moving on.

```powershell
$NS = "agents-payments"
```

### 5.1 Pre-flight checks

Confirm exactly one non-`default` service account exists. The operator denies pods in
namespaces with more than one, rather than guessing which identity to use:

```powershell
kubectl -n $NS get serviceaccounts
```

Confirm every agent Deployment carries a valid annotation:

```powershell
kubectl -n $NS get deploy -o custom-columns=`
'NAME:.metadata.name,BLUEPRINT:.metadata.annotations.agent\.blueprint/id'
```

Any agent Deployment showing `<none>` will have its pods pass through untouched (it is treated
as a non-agent workload). Add the annotation before labelling the namespace.

### 5.2 Enable the namespace

```powershell
kubectl label namespace $NS agent-enabled=true --overwrite
```

Injection applies to **newly created pods only**. Existing pods keep running without the
variable until they are recreated:

```powershell
kubectl -n $NS rollout restart deploy/payments-agent
kubectl -n $NS rollout status  deploy/payments-agent --timeout=120s
```

### 5.3 Verify

```powershell
kubectl -n $NS get pod -l app=payments-agent `
  -o jsonpath='{range .items[*]}{.metadata.name}{"`t"}{.spec.containers[0].env}{"`n"}{end}'
```

---

## 6. Upgrade

Rolling updates are safe: the PodDisruptionBudget (`minAvailable: 1`) plus two replicas keep a
webhook backend serving throughout.

```powershell
$NEW = "$REGISTRY/agent-identity-operator:v0.2.0"

docker build --platform linux/amd64 -t $NEW .
docker push $NEW

kubectl -n agent-operator-system set image deploy/agent-identity-operator operator=$NEW
kubectl -n agent-operator-system rollout status deploy/agent-identity-operator --timeout=180s
```

Then re-run the smoke test (step 4). If the rollout stalls, roll back immediately:

```powershell
kubectl -n agent-operator-system rollout undo deploy/agent-identity-operator
```

---

## 7. Rollback

### 7.1 Emergency: unblock pod creation now

If the operator is breaking agent deployments and you need the cluster working immediately,
**delete the webhook configuration**. This is the fastest safe action — the API server stops
calling the operator, and pod creation resumes instantly.

```powershell
kubectl delete mutatingwebhookconfiguration agent-identity-operator-mutating-webhook
```

> Agent pods created after this point will start **without** `AGENT_IDENTITY_ID` and without the
> Blueprint API call. This trades the identity guarantee for availability — an explicit,
> deliberate decision. Note it in the incident record.

Restore when the fix is ready:

```powershell
kubectl apply -f deploy/04-webhook.yaml
kubectl -n agent-operator-system rollout restart deploy/agent-identity-operator
```

The operator re-publishes the `caBundle` on startup, so no manual cert step is needed.

### 7.2 Narrower: disable one namespace

```powershell
kubectl label namespace $NS agent-enabled-
```

### 7.3 Full uninstall

```powershell
kubectl delete -f deploy/04-webhook.yaml   # webhook FIRST — stops admission traffic
kubectl delete -f deploy/03-deployment.yaml
kubectl delete -f deploy/02-rbac.yaml
kubectl delete -f deploy/01-namespace.yaml
```

**Order matters.** Deleting the Deployment before the webhook configuration leaves a
`failurePolicy: Fail` webhook pointing at a service with no backends — which blocks pod creation
in every agent-enabled namespace until the config is removed.

---

## 8. Troubleshooting

### All agent pods rejected: `failed calling webhook ... connection refused`

The operator is unreachable. Check pods and endpoints:

```powershell
kubectl -n agent-operator-system get pods
kubectl -n agent-operator-system get endpoints agent-identity-operator-webhook
```

Empty endpoints means no Ready pod is backing the Service. Inspect events and logs:

```powershell
kubectl -n agent-operator-system describe pod -l app.kubernetes.io/name=agent-identity-operator
kubectl -n agent-operator-system logs deploy/agent-identity-operator --previous
```

If you cannot restore it quickly, apply the emergency rollback (7.1).

### `x509: certificate signed by unknown authority`

The `caBundle` is stale or empty. Force regeneration:

```powershell
kubectl -n agent-operator-system delete secret agent-identity-operator-webhook-cert
kubectl -n agent-operator-system rollout restart deploy/agent-identity-operator
kubectl -n agent-operator-system rollout status  deploy/agent-identity-operator
```

The operator generates a fresh CA and re-patches the webhook on startup.

### Pods denied: `agent identity blueprint api call failed`

The operator is reaching the API but not getting a 2xx. Confirm egress (step 1) and check
whether the timeout budget is being exhausted:

```powershell
kubectl -n agent-operator-system logs deploy/agent-identity-operator | Select-String "FAILED"
```

Keep `BLUEPRINT_API_ATTEMPTS × BLUEPRINT_API_TIMEOUT` **below** the webhook's
`timeoutSeconds: 20`. The default 3 × 5s = 15s leaves headroom. Raising attempts to 5 pushes
the worst case to 25s, so the API server times out before retries finish — and the pod is
denied regardless.

### `AGENT_IDENTITY_ID` is missing but the pod started

The pod was not treated as an agent. Work through, in order:

```powershell
# 1. Is the namespace in scope?
kubectl get namespace $NS --show-labels

# 2. Is the annotation present and a valid GUID?
$DEPLOY = "payments-agent"
kubectl -n $NS get deploy $DEPLOY -o jsonpath='{.metadata.annotations}'

# 3. Was the pod created BEFORE the namespace was labelled?
kubectl -n $NS get pods -o wide
```

Cause 3 is the most common: labelling a namespace does not retroactively affect running pods.
Restart the Deployment.

### Pods denied: `expected exactly one agent service account`

The namespace has multiple non-`default` service accounts and the operator will not guess.
Either remove the extras, or set the service account explicitly on the pod spec — an explicit
`serviceAccountName` is always respected.

```powershell
kubectl -n $NS get serviceaccounts
```

---

## 9. Post-deployment verification

Run through this list before declaring the deployment complete.

- [ ] Both operator replicas `Running` and Ready, spread across nodes
- [ ] `caBundle` on the webhook configuration is non-empty
- [ ] Smoke test pod received `AGENT_IDENTITY_ID` (4.1)
- [ ] `SUCCESS` line present in operator logs (4.2)
- [ ] Malformed-GUID pod was **rejected** (4.3)
- [ ] Every onboarded namespace has exactly one non-`default` service account
- [ ] Every agent Deployment in scope carries a valid `agent.blueprint/id`
- [ ] Smoke-test resources cleaned up
- [ ] Alerting configured on operator availability (see below)

### Recommended monitoring

Because `failurePolicy: Fail` makes this operator a hard dependency for agent pod creation,
alert on:

| Signal | Condition |
| --- | --- |
| Operator availability | Ready replicas `< 1` for 1 min — **page** |
| Admission rejections | Sustained rise in denied pod creations |
| Blueprint API failures | `FAILED` log lines trending up |
| Certificate expiry | Serving cert within 30 days of `NotAfter` |
| Webhook latency | p99 approaching `timeoutSeconds: 20` |

```powershell
# Ad-hoc health snapshot
kubectl -n agent-operator-system get deploy agent-identity-operator `
  -o jsonpath='{.status.readyReplicas}/{.status.replicas} ready'
```

---

## Reference

| Item | Value |
| --- | --- |
| Annotation read | `agent.blueprint/id` (GUID) |
| Env var injected | `AGENT_IDENTITY_ID` |
| Namespace gate | `agent-enabled=true` |
| Break-glass pod label | `agent.blueprint/skip=true` |
| Webhook path | `/mutate-v1-pod` on port 9443 |
| Cert secret | `agent-identity-operator-webhook-cert` |
| Excluded namespaces | `agent-operator-system`, `kube-system` |

Tunable via environment variables in `deploy/03-deployment.yaml`: `BLUEPRINT_API_URL`,
`BLUEPRINT_API_TIMEOUT`, `BLUEPRINT_API_ATTEMPTS`, `ENFORCE_NAMESPACE_SERVICE_ACCOUNT`,
`ENABLE_CERT_BOOTSTRAP`, `DEV_LOGGING`. See `README.md` for architecture and defaults.
