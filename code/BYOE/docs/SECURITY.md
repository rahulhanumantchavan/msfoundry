# Security, trust and operating limits

## Evaluators are executable integrations

Only load suites from trusted authors. `allow_code=true` authorizes Python imports
and CLI processes. The process boundary provides a deadline and separates accidental
crashes; **it is not a sandbox**. Python plugins/model providers inherit process
credentials and can access files/network. CLI children receive a minimal environment
plus their explicit `env_allowlist`, but still have the OS user's filesystem/network
rights. Do not execute untrusted uploaded evaluators on this runner.

Immediate child processes are killed on timeout. CLI has a shorter inner deadline,
but arbitrary detached descendants are not contained. For untrusted/multi-tenant
evaluation use separate containers/jobs, nonprivileged identities, network policies,
read-only filesystem, CPU/memory/process limits and platform-specific process-tree
termination. These controls are not implemented by this local POC.

## Network and credentials

- HTTPS is required except literal loopback HTTP. TLS verification stays enabled.
- Redirects are disabled so Authorization headers are not forwarded.
- URLs and secrets are operator-controlled environment references. No URL query
  strings or embedded credentials are accepted by HTTP transport.
- HTTPS alone is not SSRF prevention: trusted configuration may target private
  networks. Add destination allowlists and egress policies in production.
- Bearer and Azure identity authentication are supported. IAM/RBAC/network access
  must be configured separately for agent invocation, model inference and judges.
- Calls can send datasets to different providers. Review data residency, retention,
  access controls and billing independently for each configured endpoint.
- Bounded worker stdout and JSON HTTP response sizes reduce accidental output
  expansion; there is no global dataset-size, memory or CPU budget.

## Data and reporting

Reports and `.env` are git-ignored, not encrypted. Responses, fixture cases and
reasons may contain sensitive text. Reason redaction is best-effort for recognized
credential patterns, not a full DLP guarantee. Metadata and dataset context should
not contain secrets. Set local filesystem permissions and retention before real use.

The server does not auto-register remote agents, create conversations, enable cloud
telemetry exporters or persist sessions remotely. It cannot remove exporters already
installed by an embedding application. `store=false` is requested; provider-side
service retention policies still apply.

## LLM judge risk

Agent responses and evaluator rubrics are serialized separately from system
instructions, but prompt-injection resistance is not guaranteed. The offline mock
judge verifies request/response wiring only. Run real judge contract fixtures,
adversarial cases and human calibration before using its decisions for release gates.

## Hosting

Local default is loopback. The standalone server has no application authentication;
never expose it publicly without a trusted authentication gateway. Foundry/AKS/own
infrastructure require separately verified ingress security. In-memory sessions do
not support cross-replica state consistency. This is a POC, not a production platform.