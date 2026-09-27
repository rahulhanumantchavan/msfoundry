"""Strict, versioned public contracts. Loading configuration never imports code."""

import json
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_REASON = 2048
ENV_NAME = r"^[A-Za-z_][A-Za-z0-9_]*$"
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)] | Annotated[
    int, Field(strict=True)
]
UnitNumber = Annotated[Number, Field(ge=0, le=1)]
EnvName = Annotated[str, Field(pattern=ENV_NAME)]


def strict_json_loads(text: str | bytes) -> Any:
    """Reject ambiguous keys and non-JSON numeric constants, including overflow."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Nonfinite JSON number")

    def finite_float(value):
        number = float(value)
        return number if math.isfinite(number) else invalid(value)

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid,
                      parse_float=finite_float)


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", validate_default=True)


class Case(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    query: str
    response: str | None = None
    context: dict = Field(default_factory=dict)
    expected: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    @field_validator("id", "query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank")
        return value


class EvalResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    score: UnitNumber
    reason: str = Field(max_length=MAX_REASON)
    metadata: dict = Field(default_factory=dict)


class EvaluatorSpec(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["python", "http", "cli", "llm"]
    threshold: UnitNumber = 1
    timeout_seconds: Annotated[Number, Field(gt=0, le=300)] = 30
    config: dict = Field(default_factory=dict)
    required: bool = True


class Suite(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluators: list[EvaluatorSpec] = Field(min_length=1)
    min_pass_rate: UnitNumber = 1
    target: dict = Field(default_factory=lambda: {"kind": "saved"})
    allow_code: bool = False

    @model_validator(mode="after")
    def unique_required(self):
        ids = [spec.id for spec in self.evaluators]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate evaluator ID")
        if not any(spec.required for spec in self.evaluators):
            raise ValueError("At least one required evaluator is needed")
        return self


class PythonConfig(StrictModel):
    entrypoint: str = Field(pattern=r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")
    options: dict = Field(default_factory=dict)


class CLIConfig(StrictModel):
    command: list[str] = Field(min_length=1)
    env_allowlist: list[EnvName] = Field(default_factory=list)
    options: dict = Field(default_factory=dict)

    @field_validator("command")
    @classmethod
    def command_valid(cls, value):
        if any(not part or "\0" in part for part in value):
            raise ValueError("Invalid command")
        return value


class HTTPConfig(StrictModel):
    endpoint_env: EnvName
    token_env: EnvName | None = None
    azure_scope: str | None = Field(default=None, min_length=1)
    options: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_auth_method(self):
        if self.token_env and self.azure_scope:
            raise ValueError("Select only one authentication method")
        return self


class ModelConfig(StrictModel):
    kind: Literal["openai_chat", "foundry_model", "python"]
    endpoint_env: EnvName | None = None
    model_env: EnvName | None = None
    token_env: EnvName | None = None
    azure_scope: str | None = Field(default=None, min_length=1)
    entrypoint: str | None = None

    @model_validator(mode="after")
    def required_fields(self):
        if self.kind == "python":
            PythonConfig(entrypoint=self.entrypoint)
        elif not self.endpoint_env or not self.model_env:
            raise ValueError("Remote models need endpoint_env and model_env")
        if self.token_env and self.azure_scope:
            raise ValueError("Select only one authentication method")
        return self


class LLMConfig(StrictModel):
    model: ModelConfig
    rubric: str = Field(min_length=1)


class SavedTarget(StrictModel):
    kind: Literal["saved"]


class ModelTarget(StrictModel):
    kind: Literal["model"]
    model: ModelConfig
    instructions: str = ""


class HTTPTarget(HTTPConfig):
    kind: Literal["http", "foundry_agent"]


def uses_code(spec: EvaluatorSpec) -> bool:
    return spec.kind in {"python", "cli"} or (
        spec.kind == "llm" and spec.config.get("model", {}).get("kind") == "python"
    )


def validate_evaluator(spec: EvaluatorSpec, allow_code: bool) -> None:
    configurations = {"python": PythonConfig, "cli": CLIConfig,
                      "http": HTTPConfig, "llm": LLMConfig}
    configurations[spec.kind].model_validate(spec.config)
    if uses_code(spec) and not allow_code:
        raise ValueError("Code execution requires suite allow_code=true")


def validate_target(config: dict, allow_code: bool) -> None:
    target_types = {"saved": SavedTarget, "model": ModelTarget,
                    "http": HTTPTarget, "foundry_agent": HTTPTarget}
    target_type = target_types.get(config.get("kind"))
    if target_type is None:
        raise ValueError("Unsupported target kind")
    target = target_type.model_validate(config)
    if isinstance(target, ModelTarget) and target.model.kind == "python" and not allow_code:
        raise ValueError("Python model requires suite allow_code=true")


def preflight(suite: Suite) -> None:
    for spec in suite.evaluators:
        validate_evaluator(spec, suite.allow_code)
    validate_target(suite.target, suite.allow_code)


class Fixture(StrictModel):
    evaluator_id: str
    case: Case
    expect_valid: bool
    expect_pass: bool

    @model_validator(mode="after")
    def invalid_cannot_pass(self):
        if self.expect_pass and not self.expect_valid:
            raise ValueError("Invalid results cannot pass")
        return self