from __future__ import annotations

import socket
import urllib.error
from dataclasses import dataclass

from .db import daily_run_usage, record_run_usage, run_usage_totals

MANAGED_PROVIDERS = ("Serper", "Apollo.io", "Hunter.io")


@dataclass(frozen=True)
class ProviderBudget:
    run_limit: float = 0.0
    daily_limit: float = 0.0

    def enabled(self) -> bool:
        return self.run_limit > 0 or self.daily_limit > 0


class BudgetManager:
    def __init__(self, db, run_log_id: int, budgets: dict[str, ProviderBudget] | None = None) -> None:
        self.db = db
        self.run_log_id = int(run_log_id)
        self.budgets = {
            provider: _coerce_budget(budget)
            for provider, budget in dict(budgets or {}).items()
        }

    def check(self, provider: str, cost_units: float) -> dict | None:
        budget = self.budgets.get(provider)
        if budget is None or not budget.enabled() or float(cost_units) <= 0:
            return None

        run_used = float(run_usage_totals(self.db, self.run_log_id).get(provider, 0.0))
        daily_used = float(daily_run_usage(self.db, providers=[provider]).get(provider, 0.0))
        requested = float(cost_units)

        if budget.run_limit > 0 and run_used + requested > budget.run_limit:
            return _budget_stop(provider, "run", budget.run_limit, run_used, daily_used, requested)
        if budget.daily_limit > 0 and daily_used + requested > budget.daily_limit:
            return _budget_stop(provider, "daily", budget.daily_limit, run_used, daily_used, requested)
        return None

    def record(self, provider: str, event_type: str, status: str, cost_units: float, message: str) -> dict:
        return record_run_usage(
            self.db,
            self.run_log_id,
            provider=provider,
            event_type=event_type,
            status=status,
            cost_units=cost_units,
            message=message,
        )


def budget_limits_from_settings(cfg) -> dict[str, ProviderBudget]:
    return {
        "Serper": ProviderBudget(
            run_limit=float(getattr(cfg, "serper_run_limit", 0.0) or 0.0),
            daily_limit=float(getattr(cfg, "serper_daily_limit", 0.0) or 0.0),
        ),
        "Apollo.io": ProviderBudget(
            run_limit=float(getattr(cfg, "apollo_run_limit", 0.0) or 0.0),
            daily_limit=float(getattr(cfg, "apollo_daily_limit", 0.0) or 0.0),
        ),
        "Hunter.io": ProviderBudget(
            run_limit=float(getattr(cfg, "hunter_run_limit", 0.0) or 0.0),
            daily_limit=float(getattr(cfg, "hunter_daily_limit", 0.0) or 0.0),
        ),
    }


def budget_snapshot(db, cfg, run_log_id: int | None = None) -> dict[str, dict]:
    limits = budget_limits_from_settings(cfg)
    daily_usage = daily_run_usage(db, providers=list(limits))
    run_usage = run_usage_totals(db, run_log_id) if run_log_id else {provider: 0.0 for provider in limits}
    snapshot: dict[str, dict] = {}
    for provider, budget in limits.items():
        snapshot[provider] = {
            "run_limit": budget.run_limit,
            "daily_limit": budget.daily_limit,
            "run_used": float(run_usage.get(provider, 0.0)),
            "daily_used": float(daily_usage.get(provider, 0.0)),
            "run_remaining": _remaining(budget.run_limit, float(run_usage.get(provider, 0.0))),
            "daily_remaining": _remaining(budget.daily_limit, float(daily_usage.get(provider, 0.0))),
        }
    return snapshot


def is_retryable_error(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return 500 <= int(error.code) < 600
    return isinstance(error, (urllib.error.URLError, TimeoutError, socket.timeout))


def call_with_limited_retry(operation, *, retries: int = 1):
    last_error: Exception | None = None
    attempts = max(0, int(retries)) + 1
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as error:
            last_error = error
            if attempt >= attempts - 1 or not is_retryable_error(error):
                raise
    if last_error is not None:
        raise last_error


def _remaining(limit: float, used: float) -> float | None:
    if limit <= 0:
        return None
    return max(0.0, float(limit) - float(used))


def _coerce_budget(value) -> ProviderBudget:
    if isinstance(value, ProviderBudget):
        return value
    if isinstance(value, dict):
        return ProviderBudget(
            run_limit=float(value.get("run_limit", 0.0) or 0.0),
            daily_limit=float(value.get("daily_limit", 0.0) or 0.0),
        )
    return ProviderBudget()


def _budget_stop(provider: str, scope: str, limit: float, run_used: float, daily_used: float, requested: float) -> dict:
    if scope == "run":
        message = f"{provider} 已达到单次额度上限 {limit:g}，本次不再继续调用。"
    else:
        message = f"{provider} 已达到当日额度上限 {limit:g}，本次不再继续调用。"
    return {
        "provider": provider,
        "scope": scope,
        "limit": float(limit),
        "run_used": float(run_used),
        "daily_used": float(daily_used),
        "requested": float(requested),
        "message": message,
    }
