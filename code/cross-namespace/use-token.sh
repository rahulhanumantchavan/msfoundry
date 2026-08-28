#!/bin/sh
# Runs INSIDE the operator pod.
# 1. Operator mints a token for <ns>/<sa>.
# 2. The MINTED token is then used to call the API server.
#    SelfSubjectReview echoes back who the API server thinks the caller is.
#    If it prints system:serviceaccount:<ns>:<sa>, the token is genuinely
#    that ServiceAccount's identity - not the operator's.
#
# Usage: use-token.sh <namespace> <serviceaccount>

set -eu

NS="$1"
SA="$2"

SADIR=/var/run/secrets/kubernetes.io/serviceaccount
CA="$SADIR/ca.crt"
API="https://kubernetes.default.svc"
OP_TOKEN="$(cat $SADIR/token)"

# --- step 1: mint -----------------------------------------------------------
# NOTE: "audiences" is deliberately OMITTED.
# When omitted, the API server issues the token with its own default audience,
# so the token is accepted for API-server authentication.
# On AKS with the OIDC issuer enabled, hardcoding "https://kubernetes.default.svc"
# produces a token the API server will REJECT with 401.
# Set audiences explicitly ONLY when the token is for an external verifier
# (e.g. Entra workload identity federation, Vault, a webhook).
cat >/tmp/req.json <<'EOF'
{
  "apiVersion": "authentication.k8s.io/v1",
  "kind": "TokenRequest",
  "spec": {
    "expirationSeconds": 3600
  }
}
EOF

curl -sS --fail-with-body --cacert "$CA" \
  -H "Authorization: Bearer ${OP_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST "${API}/api/v1/namespaces/${NS}/serviceaccounts/${SA}/token" \
  --data @/tmp/req.json > /tmp/resp.json

# extract .status.token without needing jq
sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /tmp/resp.json \
  | tr -d '\n' > /tmp/minted.jwt

echo "operator identity : system:serviceaccount:agent-operator:agent-operator"
echo "requested SA      : ${NS}/${SA}"
echo "minted jwt bytes  : $(wc -c < /tmp/minted.jwt)"
echo ""

# --- step 2: decode the JWT payload (proof of 'sub' claim) -------------------
echo "=== decoded JWT payload ==="
PAYLOAD="$(cut -d. -f2 < /tmp/minted.jwt)"
# pad base64url to a multiple of 4
case $(( ${#PAYLOAD} % 4 )) in
  2) PAYLOAD="${PAYLOAD}==" ;;
  3) PAYLOAD="${PAYLOAD}=" ;;
esac
echo "$PAYLOAD" | tr '_-' '/+' | base64 -d 2>/dev/null || true
echo ""
echo ""

# --- step 3: actually USE the minted token against the API ------------------
echo "=== SelfSubjectReview using the MINTED token ==="
cat >/tmp/ssr.json <<'EOF'
{"apiVersion":"authentication.k8s.io/v1","kind":"SelfSubjectReview"}
EOF

curl -sS --cacert "$CA" \
  -H "Authorization: Bearer $(cat /tmp/minted.jwt)" \
  -H "Content-Type: application/json" \
  -X POST "${API}/apis/authentication.k8s.io/v1/selfsubjectreviews" \
  --data @/tmp/ssr.json
echo ""
