"""A-share company list, profile, management, news via akshare."""

from __future__ import annotations
from quant_rd_tool.time_util import now_iso

import json
import logging
import re
import time
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd

from quant_rd_tool.akshare_data import _retry, to_ak_code, to_qlib_code

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("data/stocks/_cache")
_LIST_CACHE_FILE = _CACHE_DIR / "a_stock_list.json"
_LIST_CACHE_TTL_SEC = 3600 * 12


def _df_records(df: pd.DataFrame | None, *, limit: int | None = None) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    out = df.copy()
    if limit is not None and limit > 0:
        out = out.head(int(limit))
    out = out.where(pd.notna(out), None)
    return json.loads(out.to_json(orient="records", force_ascii=False))


def _load_list_cache() -> list[dict[str, str]] | None:
    if not _LIST_CACHE_FILE.exists():
        return None
    try:
        payload = json.loads(_LIST_CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("ts", 0)) > _LIST_CACHE_TTL_SEC:
            return None
        return list(payload.get("items") or [])
    except Exception:
        return None


def _save_list_cache(items: list[dict[str, str]]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _LIST_CACHE_FILE.write_text(
        json.dumps({"ts": time.time(), "items": items}, ensure_ascii=False),
        encoding="utf-8",
    )


@lru_cache(maxsize=1)
def _fetch_a_stock_list_raw() -> list[dict[str, str]]:
    cached = _load_list_cache()
    if cached is not None:
        return cached

    df = _retry(lambda: ak.stock_info_a_code_name(), source="stock_info_a_code_name")
    items: list[dict[str, str]] = []
    for _, row in df.iterrows():
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        if not code:
            continue
        items.append(
            {
                "code": code,
                "name": name,
                "qlib_code": to_qlib_code(code),
            }
        )
    _save_list_cache(items)
    return items


def refresh_a_stock_list() -> dict[str, Any]:
    """Clear cached A-share universe and fetch fresh list from akshare."""
    _fetch_a_stock_list_raw.cache_clear()
    if _LIST_CACHE_FILE.exists():
        _LIST_CACHE_FILE.unlink(missing_ok=True)
    items = _fetch_a_stock_list_raw()
    return {"count": len(items), "refreshed_at": now_iso()}


def list_a_stocks(
    *,
    q: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    items = _fetch_a_stock_list_raw()
    q_norm = (q or "").strip().lower()
    if q_norm:
        filtered = [
            it
            for it in items
            if q_norm in it["code"].lower()
            or q_norm in it["name"].lower()
            or q_norm in it["qlib_code"].lower()
        ]
    else:
        filtered = items

    total = len(filtered)
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), 200)
    start = (page - 1) * page_size
    page_items = filtered[start : start + page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": page_items,
    }


def fetch_stock_profile_em(symbol: str) -> list[dict[str, Any]]:
    """East Money spot metrics (price, industry, market cap, ...)."""
    code = to_ak_code(symbol)
    df = _retry(
        lambda: ak.stock_individual_info_em(symbol=code),
        source="stock_individual_info_em",
    )
    if df is None or df.empty:
        return []
    # columns: item, value
    if "item" in df.columns and "value" in df.columns:
        rows = [
            {"key": str(r["item"]), "value": r["value"]}
            for _, r in df.iterrows()
        ]
        return rows
    return _df_records(df)


def fetch_stock_profile_cninfo(symbol: str) -> list[dict[str, Any]]:
    """CNINFO company profile (legal rep, address, business scope, ...)."""
    code = to_ak_code(symbol)
    df = _retry(
        lambda: ak.stock_profile_cninfo(symbol=code),
        source="stock_profile_cninfo",
    )
    if df is None or df.empty:
        return []
    row = df.iloc[0]
    return [{"key": str(c), "value": row[c]} for c in df.columns]


def fetch_company_profile(symbol: str) -> dict[str, Any]:
    code = to_ak_code(symbol)
    em: list[dict[str, Any]] = []
    cninfo: list[dict[str, Any]] = []
    em_err = ""
    cninfo_err = ""
    try:
        em = fetch_stock_profile_em(code)
    except Exception as e:
        em_err = str(e)
        logger.warning("stock_individual_info_em failed %s: %s", code, e)
    try:
        cninfo = fetch_stock_profile_cninfo(code)
    except Exception as e:
        cninfo_err = str(e)
        logger.warning("stock_profile_cninfo failed %s: %s", code, e)

    name = ""
    for row in em:
        if row.get("key") in ("股票简称", "名称"):
            name = str(row.get("value") or "")
            break
    if not name and cninfo:
        for row in cninfo:
            if row.get("key") == "A股简称":
                name = str(row.get("value") or "")
                break

    return {
        "code": code,
        "qlib_code": to_qlib_code(code),
        "name": name,
        "em": em,
        "cninfo": cninfo,
        "errors": {"em": em_err, "cninfo": cninfo_err},
    }


def fetch_management_changes(symbol: str) -> list[dict[str, Any]]:
    """THS management / executive change records for one symbol."""
    code = to_ak_code(symbol)
    df = _retry(
        lambda: ak.stock_management_change_ths(symbol=code),
        source="stock_management_change_ths",
    )
    return _df_records(df)


def fetch_stock_notices(
    symbol: str,
    *,
    category: str = "全部",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """
    Company announcements from CNINFO via akshare.

    ``security`` param = stock code; ``symbol`` param = report category.
    """
    code = to_ak_code(symbol)
    df = _retry(
        lambda: ak.stock_individual_notice_report(security=code, symbol=category),
        source="stock_individual_notice_report",
    )
    return _df_records(df, limit=limit)


def fetch_stock_news_em(symbol: str, *, limit: int = 30) -> list[dict[str, Any]]:
    """
    East Money news search (akshare stock_news_em with regex fix).
    """
    import json as _json

    from curl_cffi import requests

    code = to_ak_code(symbol)
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    inner_param = {
        "uid": "",
        "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": min(max(limit, 10), 50),
                "preTag": "<em>",
                "postTag": "</em>",
            }
        },
    }
    params = {
        "cb": "jQuery_cb",
        "param": _json.dumps(inner_param, ensure_ascii=False),
        "_": str(int(time.time() * 1000)),
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://so.eastmoney.com/news/s?keyword={code}",
    }

    def _call():
        r = requests.get(url, params=params, headers=headers, timeout=30)
        text = r.text.strip()
        m = re.match(r"^[^(]+\((.*)\)\s*$", text, re.DOTALL)
        if not m:
            raise ValueError("unexpected jsonp response")
        data = _json.loads(m.group(1))
        articles = (data.get("result") or {}).get("cmsArticleWebOld") or []
        if not articles:
            return pd.DataFrame()
        temp_df = pd.DataFrame(articles)
        temp_df["url"] = "http://finance.eastmoney.com/a/" + temp_df["code"].astype(str) + ".html"
        temp_df = temp_df.rename(
            columns={
                "date": "发布时间",
                "mediaName": "文章来源",
                "title": "新闻标题",
                "content": "新闻内容",
                "url": "新闻链接",
            }
        )
        for col in ("新闻标题", "新闻内容"):
            if col in temp_df.columns:
                temp_df[col] = (
                    temp_df[col]
                    .astype(str)
                    .str.replace("<em>", "", regex=False)
                    .str.replace("</em>", "", regex=False)
                )
        if "新闻内容" in temp_df.columns:
            temp_df["新闻内容"] = (
                temp_df["新闻内容"]
                .str.replace("\u3000", "", regex=False)
                .str.replace("\r\n", " ", regex=False)
            )
        temp_df["关键词"] = code
        cols = [c for c in ("关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接") if c in temp_df.columns]
        return temp_df[cols]

    df = _retry(_call, source="stock_news_em")
    return _df_records(df, limit=limit)


def _default_start_date_years(years: int = 2) -> str:
    y = max(int(years), 1)
    return (date.today() - timedelta(days=365 * y)).isoformat()


def summarize_qlib_report(report: dict[str, Any]) -> dict[str, Any]:
    """Compact view for API / UI from full analyze_stock report."""
    narrative = report.get("narrative") or {}
    analysis = report.get("analysis") or {}
    ml = report.get("ml_analysis") or {}

    ml_latest: dict[str, Any] = {}
    if ml.get("models"):
        for algo, m in (ml.get("models") or {}).items():
            if isinstance(m, dict) and m.get("enabled"):
                latest = m.get("latest") or {}
                ml_latest[algo] = {
                    "signal": latest.get("signal"),
                    "predicted_return": latest.get("predicted_return"),
                }
    elif ml.get("enabled") and ml.get("latest"):
        ml_latest["model"] = {
            "signal": ml["latest"].get("signal"),
            "predicted_return": ml["latest"].get("predicted_return"),
        }

    return {
        "symbol": report.get("symbol"),
        "period": analysis.get("period"),
        "stance": narrative.get("stance"),
        "summary": narrative.get("summary"),
        "observations": narrative.get("observations") or [],
        "risks": narrative.get("risks") or [],
        "disclaimer": narrative.get("disclaimer"),
        "price": analysis.get("price"),
        "returns": analysis.get("returns"),
        "technical": analysis.get("technical"),
        "risk": analysis.get("risk"),
        "benchmark": analysis.get("benchmark"),
        "ml": ml_latest,
        "ml_skipped": bool(ml.get("skipped")),
        "ml_skip_reason": ml.get("reason") if ml.get("skipped") else "",
        "fetched_new_data": report.get("fetched_new_data"),
        "data_paths": report.get("data_paths"),
        "generated_at": report.get("generated_at"),
    }


def run_qlib_stock_analysis(
    symbol: str,
    *,
    years: int = 2,
    refresh: bool = True,
    data_dir: str = "data/stocks",
    with_ml: bool = True,
    ml_algorithm: str = "both",
    with_openbb_enrichment: bool = False,
) -> dict[str, Any]:
    """
    Pull ~N years of daily bars, dump qlib bins, run technical + qlib risk + optional ML.

    Returns full report plus ``summary`` for the console UI.
    """
    from quant_rd_tool.stock_analysis import analyze_stock

    start_date = _default_start_date_years(years)
    end_date = date.today().isoformat()
    report = analyze_stock(
        symbol,
        start_date=start_date,
        end_date=end_date,
        data_dir=data_dir,
        refresh=refresh,
        with_benchmark=True,
        benchmark="sh000300",
        with_ml=with_ml,
        ml_algorithm=ml_algorithm,  # type: ignore[arg-type]
        with_openbb_enrichment=with_openbb_enrichment,
    )
    summary = summarize_qlib_report(report)
    return {
        "code": to_ak_code(symbol),
        "qlib_code": report.get("symbol"),
        "start_date": start_date,
        "end_date": end_date,
        "years": years,
        "summary": summary,
        "markdown": report.get("markdown"),
        "report": report,
    }
