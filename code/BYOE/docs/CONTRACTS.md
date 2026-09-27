# BYOE contracts — version 1.0

The authoritative validators are Pydantic models in `byoe/contracts.py`. Unknown
top-level keys, duplicate JSON keys, unsupported versions, boolean-as-score values,
NaN/Infinity and out-of-range scores are rejected. A missing version defaults to
1.0 for this POC; new integrations should send it explicitly.

## Case

```json
{
  "schema_version": "1.0",
  "id": "case-001",
  "query": "Reply with hello",
  "response": "hello",
  "context": {},
  "expected": {"contains": ["hello"], "response": "hello"},
  "metadata": {}
}
```

ID and query must be nonblank strings; IDs must be unique in a dataset. Response
can be omitted/null for collection but must be a string for saved evaluation.
Empty responses are permitted as saved negative test data, not as successful
collection output. Context/expected/metadata are dictionaries with domain-defined
contents. This is the extension surface for evaluator-specific inputs.

## Evaluator request and result

HTTP/CLI input is a JSON object containing `case` and `options`. A Python plugin
receives these as positional dictionaries: `function(case, options)`.
All adapters return the same JSON-compatible result:

```json
{"schema_version":"1.0","score":1.0,"reason":"Matches expected behavior.","metadata":{}}
```

Score must be finite **0..1**, higher-is-better. Reason is a string of at most
2048 characters. The runner computes `passed` from the configured threshold;
evaluators cannot set it directly. Metadata is validated as an object but is not
propagated into SDK outputs in this POC. Wrap detailed evidence in a separately
secured artifact if needed.

Python registration example:

```json
{
  "id":"business_rule",
  "kind":"python",
  "threshold":1.0,
  "timeout_seconds":30,
  "required":true,
  "config":{"entrypoint":"examples.plugins:contains_expected","options":{}}
}
```

Supported kinds:

| Kind | Required config | Notes |
| --- | --- | --- |
| `python` | `entrypoint` | Trusted module:function, no import at config-load time |
| `cli` | `command` array | `{python}` expands to selected interpreter; JSON stdin/stdout; no shell |
| `http` | `endpoint_env` | Full evaluator URL; optional `token_env` or `azure_scope` |
| `llm` | `model`, `rubric` | Strict result JSON from independent model; rubric and case delimited as data |

No automatic score extraction from arbitrary dictionaries, output-scale guessing,
silent retries, or “best-effort” passing on errors. Use a wrapper for existing APIs.

## Suite and fixtures

Suites require at least one evaluator and one required evaluator, unique evaluator
IDs, a target configuration and optional `allow_code` (default false). Each
evaluator's threshold selects passing rows; `min_pass_rate` selects the fraction
of passing rows required for each required evaluator. Both default to 1.

```json
{
  "evaluator_id":"business_rule",
  "case":{"id":"positive","query":"Reply hello","response":"hello","expected":{"contains":["hello"]}},
  "expect_valid":true,
  "expect_pass":true
}
```

Add a valid negative fixture (`expect_valid=true`, `expect_pass=false`) for the same
evaluator. Invalid-response fixtures can supplement but cannot replace positive
and negative coverage. Unknown evaluator IDs, missing coverage, and mismatched
assertions fail verification.

## Target and model protocols

- Canonical HTTP target request: `schema_version`, `id`, `query`, `context`,
  `metadata`. Result: `{"schema_version":"1.0","response":"..."}`.
- Responses target: nonstreaming `input`, `stream=false`, `store=false`; parses
  completed assistant output-text blocks, rejects provider errors/incomplete output.
- OpenAI-compatible model: full `/chat/completions` URL, `model`, `messages`;
  parses textual `choices[0].message.content`.
- Foundry model: project SDK Responses client with explicit deployment name and
  `store=false`; identity-managed authentication.
- Python model: trusted `module:function(messages, timeout)` returning a nonempty
  string. Allowed for direct evaluation/judging, not the supplied streaming host.

The SDK and remote service must also support the selected protocol. Deployment and
native-provider compatibility need a real integration test after configuration.