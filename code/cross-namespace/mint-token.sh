#!/bin/sh
# Runs INSIDE the operator pod. Mints a token for an arbitrary SA in an
# arbitrary namespace using only the operator's own mounted SA token.
#
# Usage: mint-token.sh <namespace> <serviceaccount> [expirationSeconds]

set -eu

NS="$1"
SA="$2"
EXP="${3:-3600}"

SADIR=/var/run/secrets/kubernetes.io/serviceaccount
OPERATOR_TOKEN="$(cat $SADIR/token)"
APISERVER="https://kubernetes.default.svc"

curl -sS --fail-with-body \
  --cacert "$SADIR/ca.crt" \
  -H "Authorization: Bearer ${OPERATOR_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  "${APISERVER}/api/v1/namespaces/${NS}/serviceaccounts/${SA}/token" \
  -d "{
        \"apiVersion\": \"authentication.k8s.io/v1\",
        \"kind\": \"TokenRequest\",
        \"spec\": {
          \"audiences\": [\"https://kubernetes.default.svc\"],
          \"expirationSeconds\": ${EXP}
        }
      }"
