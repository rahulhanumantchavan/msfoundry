# POC: Operator minting ServiceAccount tokens across namespaces

**Verdict: Yes, this is possible — and it is the standard Kubernetes way.**
Verified end-to-end on cluster `aks-app-dev01`.

## The mechanism

Use the **TokenRequest API**, not Secrets.

`serviceaccounts/token` is a *subresource* of `ServiceAccount`. Granting `create`
on it via a **ClusterRole + ClusterRoleBinding** authorizes the operator to call:

```
POST /api/v1/namespaces/{namespace}/serviceaccounts/{name}/token
```

RBAC rules are evaluated against the **request path**, not against stored objects.
The authorizer never asks "does this namespace exist?" — so a ClusterRoleBinding
granted today automatically covers namespaces created next month.
**No RBAC changes are needed when a new agent namespace appears.**

## Files

| File | Purpose |
|---|---|
| `01-operator.yaml` | Operator namespace, SA, ClusterRole, ClusterRoleBinding, test pod |
| `02-agent-namespace.yaml` | `entra-agent-poc` + `sa-entra-agent-poc` (no operator RBAC inside) |
| `03-late-agent-namespace.yaml` | A namespace created *after* the operator, to prove ordering doesn't matter |
| `mint-token.sh` | Minimal mint call, run inside the operator pod |
| `use-token.sh` | Mint → decode JWT → authenticate to the API server as the target SA |
| `verify-token.sh` | Variant using TokenReview |

## Reproduce

```powershell
kubectl apply -f 01-operator.yaml
kubectl -n agent-operator wait --for=condition=Ready pod/operator-shell --timeout=180s

# Operator is already authorized for a namespace that does NOT exist yet:
kubectl auth can-i create serviceaccounts/token --subresource=token `
  -n future-agent-ns --as=system:serviceaccount:agent-operator:agent-operator
# -> yes

kubectl apply -f 02-agent-namespace.yaml

kubectl -n agent-operator cp .\use-token.sh operator-shell:/tmp/use-token.sh
kubectl -n agent-operator exec operator-shell -- sh /tmp/use-token.sh entra-agent-poc sa-entra-agent-poc
```

## Verified results

1. **Pre-authorization works.** `can-i` returned `yes` for `future-agent-ns`,
   a namespace that did not exist.

2. **Token minted successfully** for `entra-agent-poc/sa-entra-agent-poc` from
   inside the operator pod, using only the operator's own mounted SA token.

3. **The token is genuinely the target SA.** Decoded JWT payload:
   ```json
   {
     "sub": "system:serviceaccount:entra-agent-poc:sa-entra-agent-poc",
     "kubernetes.io": {
       "namespace": "entra-agent-poc",
       "serviceaccount": { "name": "sa-entra-agent-poc", "uid": "f1e1730e-..." }
     }
   }
   ```

4. **The token actually authenticates.** `SelfSubjectReview` using the minted
   token returned:
   ```json
   "username": "system:serviceaccount:entra-agent-poc:sa-entra-agent-poc",
   "groups": ["system:serviceaccounts", "system:serviceaccounts:entra-agent-poc", "system:authenticated"]
   ```

5. **Late-created namespace works with zero RBAC changes.** Applied
   `03-late-agent-namespace.yaml` and immediately minted a token for
   `late-agent-poc/sa-late-agent-poc`.

6. **Negative test passes.** `system:serviceaccount:default:default` → `no`.
   Operator cannot `get secrets` → `no`. The ClusterRole is doing the work and
   stays narrow.

## Gotcha found during testing (important for AKS)

Hardcoding `"audiences": ["https://kubernetes.default.svc"]` produced a token
that the API server **rejected with 401**.

This cluster has the AKS OIDC issuer enabled, so its accepted audience is
`https://aks-app-dev01-dns-iclslpku.hcp.westeurope.azmk8s.io` (plus the OIDC
issuer URL), not `kubernetes.default.svc`.

**Rule:**
- **Omit `audiences`** when the token is used against the Kubernetes API server →
  the API server fills in its own correct default.
- **Set `audiences` explicitly** only when an *external* party validates the
  token (Entra workload identity federation, Vault, an admission webhook).
  The audience must then match what that party expects.

## Notes for the real operator

- In client-go this is
  `clientset.CoreV1().ServiceAccounts(ns).CreateToken(ctx, saName, &authnv1.TokenRequest{...}, metav1.CreateOptions{})`.
- Tokens are **short-lived and not stored**. Cache in memory and re-mint at
  ~80% of `expirationTimestamp`. Do not persist them into Secrets.
- `expirationSeconds` minimum is 600 (10 min); values below are silently raised.
  Keep it short — 3600 or less.
- Optionally set `spec.boundObjectRef` to a Pod/Secret so the token is
  invalidated when that object is deleted.
- Minting a token does **not** grant the target SA any permissions. The token
  carries whatever RBAC `sa-entra-agent-poc` already has.
- If you want to constrain which namespaces the operator can mint for, a
  ClusterRole cannot express that. Options: an admission/validating webhook, or
  per-namespace RoleBindings created by whatever provisions the namespace
  (which reintroduces the "additional changes" you wanted to avoid).

## Cleanup

```powershell
kubectl delete -f 03-late-agent-namespace.yaml --ignore-not-found
kubectl delete -f 01-operator.yaml --ignore-not-found
```
