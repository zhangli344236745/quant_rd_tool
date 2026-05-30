"""Match schedule cycle symbols against user-defined alert conditions.

Condition format (stored in ``data/settings.json`` → ``schedule_alerts.custom_rules``):

Each **custom rule** object::

    {
      "id": "btc-turn-bull",           // required, unique slug (cooldown key)
      "name": "BTC 转多",              // optional label
      "enabled": true,
      "job_ids": [],                   // empty = all schedule jobs; else only these ids
      "symbol_scope": "any_symbol",    // any_symbol | all_symbols (multi-symbol jobs)
      "logic": "and",                  // and | or — combine conditions for one symbol row
      "conditions": [ ... ],           // see below
      "message": "{job_id} {symbol} → {stance} ({action})"  // optional template
    }

Each **condition** compares one field on a per-symbol cycle row::

    { "field": "stance", "op": "eq", "value": "看涨" }

Supported **fields** (case-insensitive names):

| field | aliases | type | notes |
| symbol | base, pair | string | BTC, ETH; ``BTC/USDT`` normalized to ``BTC`` |
| stance | | string | 看涨 / 看跌 / 中性 |
| action | | string | buy, sell, hold, long, short, … |
| new_bars | new_bars | number | incremental bars this cycle |

Supported **ops**:

| op | value | example |
| eq | string or number | ``{"op":"eq","value":"看涨"}`` |
| neq | string or number | |
| in | string or list | ``{"op":"in","value":["buy","long"]}`` |
| not_in | string or list | |
| contains | substring | ``{"op":"contains","value":"涨"}`` |
| regex | pattern | ``{"op":"regex","value":"^买"}`` |
| gt, gte, lt, lte | number | ``{"op":"gte","value":1}`` for new_bars |

**symbol_scope**:

- ``any_symbol``: at least one symbol in the cycle matches (conditions combined with ``logic``).
- ``all_symbols``: every non-error symbol in the cycle must match.

Rows with ``error`` are skipped for signal rules.

**message** placeholders: ``{job_id}``, ``{symbol}``, ``{pair}``, ``{stance}``, ``{action}``, ``{new_bars}``, ``{rule_id}``, ``{rule_name}``.
"""

from __future__ import annotations

import re
from typing import Any, Literal

Logic = Literal["and", "or"]
SymbolScope = Literal["any_symbol", "all_symbols"]

_FIELD_ALIASES = {
    "symbol": "symbol",
    "base": "symbol",
    "pair": "symbol",
    "stance": "stance",
    "action": "action",
    "new_bars": "new_bars",
}


def normalize_symbol(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if "/" in s:
        s = s.split("/", 1)[0]
    if s.startswith("CRYPTO_"):
        s = s.replace("CRYPTO_", "", 1)
    return s


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    sym = normalize_symbol(row.get("symbol") or row.get("pair"))
    return {
        "symbol": sym,
        "pair": row.get("pair") or sym,
        "stance": str(row.get("stance") or "").strip(),
        "action": str(row.get("action") or "").strip().lower(),
        "new_bars": row.get("new_bars"),
        "error": row.get("error"),
    }


def _resolve_field(field: str) -> str | None:
    key = (field or "").strip().lower()
    return _FIELD_ALIASES.get(key)


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [v.strip() for v in str(value).split(",") if str(v).strip()]


def _compare(condition: dict[str, Any], row: dict[str, Any]) -> bool:
    field = _resolve_field(str(condition.get("field") or ""))
    if not field:
        return False
    op = str(condition.get("op") or "eq").strip().lower()
    value = condition.get("value")
    actual = row.get(field)

    if field == "symbol":
        actual = normalize_symbol(actual)
        if op in ("in", "not_in"):
            vals = [normalize_symbol(v) for v in _coerce_list(value)]
            return (actual in vals) if op == "in" else (actual not in vals)
        s_actual, s_val = actual, normalize_symbol(value)
        if op == "eq":
            return s_actual == s_val
        if op == "neq":
            return s_actual != s_val
        if op == "contains":
            return s_val in s_actual
        if op == "regex":
            return bool(re.search(str(value), s_actual, re.I))
        return False

    if field in ("stance", "action"):
        s_actual = str(actual or "")
        if field == "action":
            s_actual = s_actual.lower()
        if op in ("in", "not_in"):
            vals = _coerce_list(value)
            if field == "action":
                norm_vals = [str(v).strip().lower() for v in vals]
            else:
                norm_vals = [str(v).strip() for v in vals]
            hit = s_actual in norm_vals
            return hit if op == "in" else not hit
        s_val = str(value or "")
        if field == "action":
            s_val = s_val.lower()
        if op == "eq":
            return s_actual == s_val
        if op == "neq":
            return s_actual != s_val
        if op == "contains":
            return s_val in s_actual
        if op == "regex":
            return bool(re.search(str(value), s_actual, re.I))
        return False

    if field == "new_bars":
        try:
            num = float(actual if actual is not None else 0)
            thresh = float(value)
        except (TypeError, ValueError):
            return False
        if op == "eq":
            return num == thresh
        if op == "neq":
            return num != thresh
        if op == "gt":
            return num > thresh
        if op == "gte":
            return num >= thresh
        if op == "lt":
            return num < thresh
        if op == "lte":
            return num <= thresh
        return False

    return False


def row_matches_conditions(
    row: dict[str, Any],
    conditions: list[dict[str, Any]],
    *,
    logic: Logic = "and",
) -> bool:
    if not conditions:
        return False
    norm = normalize_row(row)
    if norm.get("error"):
        return False
    checks = [_compare(c, norm) for c in conditions if isinstance(c, dict)]
    if not checks:
        return False
    return all(checks) if logic == "and" else any(checks)


def rule_matches_cycle(
    rule: dict[str, Any],
    *,
    job_id: str,
    cycle_rows: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any] | None]:
    """Return (matched, best_row_for_message)."""
    if not rule.get("enabled", True):
        return False, None
    job_ids = rule.get("job_ids") or []
    if job_ids and job_id not in job_ids:
        return False, None

    conditions = rule.get("conditions") or []
    if not isinstance(conditions, list) or not conditions:
        return False, None

    logic: Logic = "or" if str(rule.get("logic") or "and").lower() == "or" else "and"
    scope: SymbolScope = (
        "all_symbols"
        if str(rule.get("symbol_scope") or "any_symbol").lower() == "all_symbols"
        else "any_symbol"
    )

    ok_rows = [r for r in cycle_rows if not r.get("error")]
    if not ok_rows:
        return False, None

    matched_rows = [r for r in ok_rows if row_matches_conditions(r, conditions, logic=logic)]
    if scope == "any_symbol":
        if matched_rows:
            return True, normalize_row(matched_rows[0])
        return False, None

    if len(matched_rows) == len(ok_rows):
        return True, normalize_row(matched_rows[0])
    return False, None


def format_message(template: str, *, job_id: str, row: dict[str, Any], rule: dict[str, Any]) -> str:
    tpl = template.strip() or "[{job_id}] {symbol} signal {stance} ({action})"
    return tpl.format(
        job_id=job_id,
        symbol=row.get("symbol", ""),
        pair=row.get("pair", ""),
        stance=row.get("stance", ""),
        action=row.get("action", ""),
        new_bars=row.get("new_bars", ""),
        rule_id=rule.get("id", ""),
        rule_name=rule.get("name", rule.get("id", "")),
    )


def validate_custom_rule(rule: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not str(rule.get("id") or "").strip():
        errors.append("id is required")
    conditions = rule.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        errors.append("conditions must be a non-empty list")
    else:
        for i, c in enumerate(conditions):
            if not isinstance(c, dict):
                errors.append(f"conditions[{i}] must be an object")
                continue
            if not _resolve_field(str(c.get("field") or "")):
                errors.append(f"conditions[{i}].field unsupported: {c.get('field')}")
    logic = str(rule.get("logic") or "and").lower()
    if logic not in ("and", "or"):
        errors.append("logic must be 'and' or 'or'")
    scope = str(rule.get("symbol_scope") or "any_symbol").lower()
    if scope not in ("any_symbol", "all_symbols"):
        errors.append("symbol_scope must be 'any_symbol' or 'all_symbols'")
    return errors
