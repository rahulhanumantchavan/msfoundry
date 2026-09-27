# Foundry POC: deployment handoff, no cloud changes performed

The source is a model-backed agent with a Foundry-compatible Responses host in
`hosted_main.py`. It is **not currently a deployed Foundry agent**. The offline demo
and local protocol tests do not certify live Foundry hosting compatibility.

## Stage 1 — evaluator compatibility, free/offline

Run the four-adapter demo and tests. Review `verification.json`: each evaluator must
have known valid pass/fail coverage. Review SDK scores and the release gate separately.

## Stage 2 — local host with a real model, optional/billable

Configure `MODEL_CONFIG_FILE` using `configs/model.foundry.json` or
`configs/model.openai.json`. Model endpoint and deployment are entirely independent
of where the agent will be hosted. The example Foundry model values refer to the
existing project's model; verify access and availability before use.

The root VS Code debug entry **BYOE Generic: hosted agent** loads `BYOE/.env`, starts
the host at `127.0.0.1:8090`, and opens Agent Inspector. The original support host
uses different ports and tasks. CLI startup uses exported environment variables.
Use `configs/suite.local-agent.json` for evaluation against that local Responses
endpoint, with `--collect`. `data/queries.jsonl` contains generic exact-text cases,
not customer-support policy assertions.

## Stage 3 — prepare/approve Foundry deployment

Before deployment, select and verify:

- Existing Foundry project ARM ID/endpoint, subscription, region and agent name.
- Hosting runtime availability, quota, compatible current azd extension versions and
  an approved source sample/manifest for the selected Responses hosting path.
- Authentication/RBAC for deployment, agent invocation, and model inference.
- Model provider's endpoint reachability from hosted compute; private-network egress
  and secrets injection when using non-Foundry models.
- Estimated agent compute, model/LLM-judge charges, logging, and storage costs.

Onboard **this BYOE source directory** as existing code using the current Foundry
create/re-host workflow and inspect generated artifacts before deploying. Do not
initialize a second copy over the existing support-agent folder. Source entry point
is `hosted_main.py`, Python runtime **3.13**, requirements in `requirements.txt`.
For hosted compute the server must be explicitly bound to `0.0.0.0` and the port
expected by the chosen hosting protocol (typically 8088 for the adapter). The
entrypoint supports `--host` and `--port`; configure these in the host startup command.

This handoff deliberately does not contain guessed project IDs, image URIs, an
unvalidated deployment manifest, or automation that provisions resources. Generate
the platform-specific deployment artifacts only after choices and approval. It is
deployable application source, **not a completed one-click infrastructure setup**.

Keep `.env`, `results`, tests, `.venv` and local caches out of the deployment package.
`deploy/agentignore.example` supplies exclusions to copy into the selected agent's
`.agentignore` after onboarding. Inject configuration through the platform; do not
include API keys in manifest files. Use identity-based inference wherever supported.

## Stage 4 — evaluate the deployed agent

1. Verify the deployed version is active using the deployment tooling.
2. Obtain the **full deployed Responses protocol endpoint** from discovery; do not
   construct it from a project URL or confuse it with a model inference URL.
3. Set `BYOE_AGENT_RESPONSES_URL` and verify its required audience/authentication.
   The sample suite uses Azure identity scope `https://ai.azure.com/.default`;
   adjust to the discovered endpoint contract if different.
4. Run suite `configs/suite.foundry-agent.json` on `data/queries.jsonl` with collection
   enabled. Requests ask for nonstreaming output and no response storage.
5. Check row completeness, actual outputs, evaluator reasons, metrics and gate status.
   Preserve deployment version/model version alongside the report for reproducibility.

If the chosen host requires extra routing headers, session creation, or a different
protocol, add a dedicated target adapter. A full URL alone cannot accommodate every
Foundry host/session API version. No automatic protocol or mock fallback is provided.

## AKS / own infrastructure

The same application source can run behind a protected ingress with the Responses
adapter, or any existing agent can expose the canonical HTTP target contract.
Choose that adapter without changing evaluator plugins. Container images, Kubernetes
manifests, ingress, TLS, identity, rollout, autoscaling and durable session storage
are platform work intentionally outside this Foundry-first POC.