"""Deliberately malformed/slow plugins for subprocess boundary tests."""

import os
import time


def delayed(case, options):
    time.sleep(options.get("seconds", 4))
    return {"score": 1, "reason": "late"}


def malformed(case, options):
    return options["result"]


def nonfinite(case, options):
    return {"score": float("nan"), "reason": "bad"}


def throwing(case, options):
    raise RuntimeError("SECRET exception with credentials")


def noisy(case, options):
    print("SENSITIVE LOG " * 100000)
    return {"score": 1, "reason": "clean"}


def secret_reason(case, options):
    return {"score": 1, "reason": os.environ["BYOE_TEST_TOKEN"]}


def huge(case, options):
    return {"score": 1, "reason": "large", "metadata": {"data": "a" * 1100000}}