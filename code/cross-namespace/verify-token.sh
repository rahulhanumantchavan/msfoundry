#!/bin/sh
# Runs INSIDE the operator pod.
# Mints a token for <ns>/<sa>, then submits it to the TokenReview API to prove
# the API server resolves it to system:serviceaccount:<ns>:<sa>.
#
# Usage: verify-token.sh <namespace> <serviceaccount>

set -eu

NS="$1"
SA="$2"

SADIR=/var/run/secrets/kubernetes.io/serviceaccount
OPERATOR_TOKEN="$(cat $SADIR/token)"
APISERVER="https://kubernetes.default.svc"
CA="$SADIR/ca.crt"

echo "=== Operator identity (whoami) ==="
curl -sS --cacert "$CA" -H "Authorization: Bearer ${OPERATOR_TOKEN}" \
  -X POST "${APISERVER}/apis/authentication.k8s.io/v1/selfsubjectreviews" \
  -H 'Content-Type: application/json' \
  -d '{"apiVersion":"authentication.k8s.io/v1","kind":"SelfSubjectReview"}' \
  | tr ',' '\n' | grep -E '"username"|"uid"' || true

echo ""
echo "=== Minting token for ${NS}/${SA} ==="
MINTED=$(curl -sS --fail-with-body --cacert "$CA" \
  -H "Authorization: Bearer ${OPERATOR_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST "${APISERVER}/api/v1/namespaces/${NS}/serviceaccounts/${SA}/token" \
  -d '{"apiVersion":"authentication.k8s.io/v1","kind":"TokenRequest","spec":{"audiences":["https://kubernetes.default.svc"],"expirationSeconds":3600}}' \
  | tr ',' '\n' | grep '"token"' | sed 's/.*"token": *"//; s/"$//')

echo "minted token length: ${#MINTED}"

echo ""
echo "=== TokenReview: who does the API server say this token is? ==="
curl -sS --cacert "$CA" \
  -H "Authorization: Bearer ${OPERATOR_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST "${APISERVER}/apis/authentication.k8s.io/v1/tokenreviews" \
  -d "{\"apiVersion\":\"authentication.k8s.io/v1\",\"kind\":\"TokenReview\",\"spec\":{\"token\":\"${MINTED}\",\"audiences\":[\"https://kubernetes.default.svc\"]}}" \
  | tr ',' '\n' | grep -E '"authenticated"|"username"|"groups"|system:serviceaccount' || true
