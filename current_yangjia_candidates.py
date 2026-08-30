"""Build a current A-share watchlist from public short-term trading signals.

This is a research proxy inspired by the public descriptions associated with
"炒股养家": market-phase awareness, leading-stock/board structure, main-line
co-movement, intraday strength, and capital-flow confirmation.  It is not a
claim to reproduce any person's private rules or trading record.

The script is deliberately as-of safe for a completed trading day:

* Eastmoney limit-up, previous-limit-up, broken-board, limit-down and 龙虎榜
  tables are queried only through ``--asof-date``.
* Recent daily history is fetched from the Tencent quote endpoint exposed by
  AKShare when the Eastmoney quote endpoint is unavailable in the local
  network.  The source and endpoint are written to the output.
* Five-minute data is fetched from the Sina quote endpoint exposed by AKShare
  as a fallback for the same reason.
* No future return is used in the score.  A blank forward-validation template
  is emitted for later checking.

The result is a candidate list, not an order instruction.  Short-term A-share
signals are especially vulnerable to limit-up/limit-down execution constraints,
slippage, suspension, and regime changes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import akshare as ak
import numpy as np
import pandas as pd

from config import OUTPUT_DIR, PROJECT_ROOT


CURRENT_CACHE_DIR = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "current"
CURRENT_OUTPUT_DIR = OUTPUT_DIR / "current_yangjia_candidates"


@dataclass(frozen=True)
class CurrentConfig:
    asof_date: str = ""
    lookback_sessions: int = 20
    lhb_lookback_sessions: int = 20
    max_daily_codes: int = 220
    max_minute_codes: int = 60
    top_n: int = 20
    workers: int = 4
    daily_calendar_days: int = 150
    no_cache: bool = False


def _clear_proxy_environment() -> None:
    """The local proxy breaks push2/push2his; direct requests are reachable."""

    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ[name] = ""
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def _safe_value(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if pd.isna(value) if not isinstance(value, (list, tuple, dict)) else False:
        return None
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=_safe_value)
    temporary.replace(path)


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp" + path.suffix)
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def _normalise_code(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper()
    text = text.replace("SH", "").replace("SZ", "").replace("BJ", "")
    text = re.sub(r"[^0-9]", "", text)
    if not text:
        return None
    return text.zfill(6)


def _market_symbol(code: str) -> str:
    code = _normalise_code(code) or ""
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("4", "8", "9")):
        return "bj" + code
    return "sz" + code


def _instrument(code: str) -> str:
    symbol = _market_symbol(code)
    return symbol[:2].upper() + symbol[2:]


def _parse_asof(raw: str) -> pd.Timestamp:
    if raw:
        value = pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
        if pd.isna(value):
            value = pd.to_datetime(raw, errors="coerce")
        if pd.isna(value):
            raise ValueError(f"invalid as-of date: {raw}")
        return value.normalize()
    return pd.Timestamp(datetime.now().date())


def _trade_dates(asof: pd.Timestamp, sessions: int) -> list[pd.Timestamp]:
    calendar = ak.tool_trade_date_hist_sina()
    calendar["trade_date"] = pd.to_datetime(calendar["trade_date"], errors="coerce").dt.normalize()
    dates = sorted(set(calendar.loc[calendar["trade_date"] <= asof, "trade_date"].dropna()))
    if not dates:
        dates = list(pd.bdate_range(end=asof, periods=sessions))
    return dates[-sessions:]


def _parse_date_value(value: Any) -> pd.Timestamp | pd.NaT:
    if value is None or pd.isna(value):
        return pd.NaT
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).normalize()
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric):
        if numeric >= 1e12:
            return pd.to_datetime(numeric, unit="ms", errors="coerce").normalize()
        if numeric >= 1e9:
            return pd.to_datetime(numeric, unit="s", errors="coerce").normalize()
        text = str(int(numeric))
        if len(text) == 8:
            return pd.to_datetime(text, format="%Y%m%d", errors="coerce").normalize()
    return pd.to_datetime(str(value), errors="coerce").normalize()


def _parse_date_series(series: pd.Series) -> pd.Series:
    return series.map(_parse_date_value)


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _clamp(series: pd.Series | float, low: float = 0.0, high: float = 1.0) -> pd.Series:
    if isinstance(series, pd.Series):
        return series.astype(float).clip(lower=low, upper=high).fillna(0.0)
    return pd.Series([float(min(high, max(low, series)))])


def _rename(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    return df.rename(columns={key: value for key, value in mapping.items() if key in df.columns})


def _cache_path(kind: str, name: str) -> Path:
    return CURRENT_CACHE_DIR / kind / name


def _fetch_cached_table(
    kind: str,
    name: str,
    fetcher: Callable[[], pd.DataFrame],
    fetch_log: list[dict[str, Any]],
    no_cache: bool = False,
    retries: int = 3,
) -> pd.DataFrame:
    path = _cache_path(kind, name)
    if path.exists() and not no_cache:
        try:
            frame = pd.read_parquet(path)
            fetch_log.append({"kind": kind, "name": name, "status": "cache", "rows": len(frame)})
            return frame
        except Exception as exc:
            fetch_log.append({"kind": kind, "name": name, "status": "cache_error", "error": str(exc)})

    errors: list[str] = []
    for attempt in range(1, retries + 1):
        try:
            frame = fetcher()
            if frame is None:
                frame = pd.DataFrame()
            _write_frame(path, frame)
            fetch_log.append({"kind": kind, "name": name, "status": "fetched", "rows": len(frame)})
            return frame
        except Exception as exc:
            errors.append(str(exc))
            if attempt < retries:
                time.sleep(0.5 * attempt)
    fetch_log.append({"kind": kind, "name": name, "status": "error", "error": " | ".join(errors)})
    return pd.DataFrame()


def _normalise_pool(frame: pd.DataFrame, pool_date: pd.Timestamp, pool_type: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    result = _rename(
        frame.copy(),
        {
            "代码": "code",
            "名称": "name",
            "涨跌幅": "pct_chg",
            "最新价": "latest_price",
            "成交额": "amount",
            "流通市值": "float_mv",
            "总市值": "total_mv",
            "换手率": "turnover_pct",
            "封板资金": "seal_amount",
            "封单资金": "seal_amount",
            "首次封板时间": "first_seal_time",
            "最后封板时间": "last_seal_time",
            "炸板次数": "broken_count",
            "开板次数": "broken_count",
            "涨停统计": "limit_up_stat",
            "连板数": "board_days",
            "昨日连板数": "previous_board_days",
            "所属行业": "industry",
            "昨日封板时间": "previous_seal_time",
            "涨停原因": "limit_reason",
        },
    )
    if "code" not in result:
        return pd.DataFrame()
    result["code"] = result["code"].map(_normalise_code)
    result = result.dropna(subset=["code"]).copy()
    for column in (
        "pct_chg",
        "latest_price",
        "amount",
        "float_mv",
        "total_mv",
        "turnover_pct",
        "seal_amount",
        "broken_count",
        "board_days",
        "previous_board_days",
    ):
        if column in result:
            result[column] = _number(result[column])
    result["pool_date"] = pool_date
    result["pool_type"] = pool_type
    return result


def _normalise_lhb(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    result = _rename(
        frame.copy(),
        {
            "代码": "code",
            "名称": "name",
            "上榜日": "billboard_date",
            "龙虎榜净买额": "lhb_net_amount",
            "龙虎榜买入额": "lhb_buy_amount",
            "龙虎榜卖出额": "lhb_sell_amount",
            "龙虎榜成交额": "lhb_turnover_amount",
            "市场总成交额": "market_turnover_amount",
            "净买额占总成交比": "lhb_net_ratio_pct",
            "成交额占总成交比": "lhb_turnover_ratio_pct",
            "换手率": "turnover_pct",
            "流通市值": "float_mv",
            "上榜原因": "lhb_reason",
            "上榜后1日": "after_1d",
            "上榜后2日": "after_2d",
            "上榜后5日": "after_5d",
            "上榜后10日": "after_10d",
        },
    )
    if "code" not in result:
        return pd.DataFrame()
    result["code"] = result["code"].map(_normalise_code)
    result = result.dropna(subset=["code"]).copy()
    if "billboard_date" in result:
        result["billboard_date"] = _parse_date_series(result["billboard_date"])
    for column in (
        "lhb_net_amount",
        "lhb_buy_amount",
        "lhb_sell_amount",
        "lhb_turnover_amount",
        "market_turnover_amount",
        "lhb_net_ratio_pct",
        "lhb_turnover_ratio_pct",
        "turnover_pct",
        "float_mv",
    ):
        if column in result:
            result[column] = _number(result[column])
    return result


def _aggregate_lhb(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["code"])
    data = frame.sort_values(["code", "billboard_date"])
    rows: list[dict[str, Any]] = []
    for code, group in data.groupby("code", sort=False):
        net = group.get("lhb_net_amount", pd.Series(dtype=float)).dropna()
        net_ratio = group.get("lhb_net_ratio_pct", pd.Series(dtype=float)).dropna()
        last = group.iloc[-1]
        rows.append(
            {
                "code": code,
                "lhb_count": int(len(group)),
                "lhb_net_sum": float(net.sum()) if not net.empty else np.nan,
                "lhb_net_mean": float(net.mean()) if not net.empty else np.nan,
                "lhb_net_ratio_mean_pct": float(net_ratio.mean()) if not net_ratio.empty else np.nan,
                "lhb_positive_ratio": float((net > 0).mean()) if not net.empty else np.nan,
                "lhb_latest_date": last.get("billboard_date", pd.NaT),
                "lhb_latest_reason": last.get("lhb_reason", ""),
                "lhb_latest_net": last.get("lhb_net_amount", np.nan),
                "lhb_latest_net_ratio_pct": last.get("lhb_net_ratio_pct", np.nan),
            }
        )
    return pd.DataFrame(rows)


def _normalise_daily(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    result = _rename(
        frame.copy(),
        {"day": "date", "日期": "date", "成交量": "volume", "成交额": "amount"},
    )
    required = {"date", "open", "close", "high", "low"}
    if not required.issubset(result.columns):
        return pd.DataFrame()
    result["date"] = _parse_date_series(result["date"])
    for column in ("open", "close", "high", "low", "volume", "amount"):
        if column in result:
            result[column] = _number(result[column])
    result["code"] = code
    result = result.dropna(subset=["date", "close"]).drop_duplicates("date", keep="last")
    return result.sort_values("date")


def _fetch_daily_one(
    code: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    no_cache: bool,
) -> tuple[str, pd.DataFrame, str | None]:
    path = _cache_path("daily_tx", f"{code}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet")
    if path.exists() and not no_cache:
        try:
            return code, pd.read_parquet(path), None
        except Exception:
            pass
    try:
        raw = ak.stock_zh_a_hist_tx(
            symbol=_market_symbol(code),
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="",
        )
        result = _normalise_daily(raw, code)
        if result.empty:
            raise ValueError("Tencent daily endpoint returned no usable rows")
        _write_frame(path, result)
        return code, result, None
    except Exception as exc:
        return code, pd.DataFrame(), str(exc)


def _daily_features(frame: pd.DataFrame, asof: pd.Timestamp) -> dict[str, Any]:
    if frame.empty:
        return {"daily_rows": 0, "daily_available": False}
    data = frame.loc[frame["date"] <= asof].sort_values("date").copy()
    if data.empty:
        return {"daily_rows": 0, "daily_available": False}
    close = data["close"].astype(float)
    latest = data.iloc[-1]
    result: dict[str, Any] = {
        "daily_rows": int(len(data)),
        "daily_available": True,
        "daily_latest_date": latest["date"],
        "close": float(latest["close"]),
        "daily_open": float(latest["open"]),
        "daily_high": float(latest["high"]),
        "daily_low": float(latest["low"]),
        "daily_amount": float(latest["amount"]) if "amount" in latest and pd.notna(latest["amount"]) else np.nan,
    }
    for horizon in (1, 3, 5, 10, 20, 60):
        if len(close) > horizon:
            result[f"ret_{horizon}d"] = float(close.iloc[-1] / close.iloc[-1 - horizon] - 1.0)
        else:
            result[f"ret_{horizon}d"] = np.nan
    if len(close) >= 20:
        result["drawdown_20d"] = float(close.iloc[-1] / close.iloc[-20:].max() - 1.0)
    else:
        result["drawdown_20d"] = np.nan
    if len(data) >= 6 and "amount" in data:
        prior = data["amount"].iloc[-6:-1].dropna()
        result["daily_amount_ratio_5d"] = (
            float(latest["amount"] / prior.median()) if not prior.empty and prior.median() > 0 else np.nan
        )
    else:
        result["daily_amount_ratio_5d"] = np.nan
    return result


def _normalise_minute(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    result = _rename(
        frame.copy(),
        {
            "时间": "datetime",
            "日期": "datetime",
            "day": "datetime",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        },
    )
    required = {"datetime", "open", "close", "high", "low"}
    if not required.issubset(result.columns):
        return pd.DataFrame()
    result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
    for column in ("open", "close", "high", "low", "volume", "amount"):
        if column in result:
            result[column] = _number(result[column])
    result["code"] = code
    return (
        result.dropna(subset=["datetime", "open", "close"])
        .drop_duplicates("datetime", keep="last")
        .sort_values("datetime")
    )


def _fetch_minute_one(
    code: str,
    asof: pd.Timestamp,
    no_cache: bool,
) -> tuple[str, pd.DataFrame, str | None, str | None]:
    path = _cache_path("minute_sina", f"{code}.parquet")
    if path.exists() and not no_cache:
        try:
            cached = pd.read_parquet(path)
            if not cached.empty and pd.to_datetime(cached["datetime"]).dt.normalize().max() >= asof:
                return code, cached, None, "sina_5min_via_akshare"
        except Exception:
            pass
    try:
        raw = ak.stock_zh_a_minute(symbol=_market_symbol(code), period="5", adjust="")
        result = _normalise_minute(raw, code)
        result = result.loc[result["datetime"].dt.normalize() <= asof]
        if result.empty:
            raise ValueError("Sina 5-minute endpoint returned no usable rows")
        _write_frame(path, result)
        return code, result, None, "sina_5min_via_akshare"
    except Exception as exc:
        return code, pd.DataFrame(), str(exc), None


def _minute_features(frame: pd.DataFrame, asof: pd.Timestamp) -> dict[str, Any]:
    if frame.empty:
        return {"minute_available": False, "minute_rows": 0}
    data = frame.copy()
    data["date"] = data["datetime"].dt.normalize()
    today = data.loc[data["date"] == asof].sort_values("datetime")
    if today.empty:
        return {"minute_available": False, "minute_rows": int(len(data))}
    prior_dates = sorted(item for item in data["date"].unique() if item < asof)
    previous = data.loc[data["date"] == prior_dates[-1]].sort_values("datetime") if prior_dates else pd.DataFrame()
    previous_close = float(previous.iloc[-1]["close"]) if not previous.empty else np.nan
    current_close = float(today.iloc[-1]["close"])
    day_open = float(today.iloc[0]["open"])
    day_high = float(today["high"].max())
    latest_dt = today.iloc[-1]["datetime"]
    late = today.loc[today["datetime"] <= latest_dt - timedelta(minutes=30)]
    late_close = float(late.iloc[-1]["close"]) if not late.empty else day_open
    prior_amounts: list[float] = []
    for prior_date in prior_dates[-5:]:
        amount = data.loc[data["date"] == prior_date, "amount"].sum(min_count=1)
        if pd.notna(amount) and amount > 0:
            prior_amounts.append(float(amount))
    current_amount = data.loc[data["date"] == asof, "amount"].sum(min_count=1)
    prior_median = float(np.median(prior_amounts)) if prior_amounts else np.nan
    return {
        "minute_available": True,
        "minute_rows": int(len(today)),
        "minute_latest_datetime": latest_dt,
        "minute_close": current_close,
        "minute_from_prev_close": current_close / previous_close - 1.0 if previous_close > 0 else np.nan,
        "minute_from_open": current_close / day_open - 1.0 if day_open > 0 else np.nan,
        "minute_from_high": current_close / day_high - 1.0 if day_high > 0 else np.nan,
        "minute_late_momentum_30m": current_close / late_close - 1.0 if late_close > 0 else np.nan,
        "minute_amount": float(current_amount) if pd.notna(current_amount) else np.nan,
        "minute_amount_ratio_5d": float(current_amount / prior_median) if prior_median > 0 else np.nan,
    }


def _load_local_base_codes() -> set[str]:
    candidates: set[str] = set()
    for path in sorted(OUTPUT_DIR.glob("base_candidates_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for item in payload.get("candidates", []):
                instrument = str(item.get("instrument", ""))
                code = _normalise_code(instrument)
                if code:
                    candidates.add(code)
        except Exception:
            continue
    return candidates


def _aggregate_limit_up(
    history: pd.DataFrame,
    current: pd.DataFrame,
    previous: pd.DataFrame,
    dates: list[pd.Timestamp],
    asof: pd.Timestamp,
) -> pd.DataFrame:
    if history.empty:
        result = pd.DataFrame(columns=["code"])
    else:
        rows: list[dict[str, Any]] = []
        recent5 = set(dates[-5:])
        recent10 = set(dates[-10:])
        for code, group in history.groupby("code", sort=False):
            group = group.sort_values("pool_date")
            last = group.iloc[-1]
            last_date = last["pool_date"]
            try:
                age = len(dates) - 1 - dates.index(last_date)
            except ValueError:
                age = np.nan
            rows.append(
                {
                    "code": code,
                    "name": last.get("name", ""),
                    "industry": last.get("industry", ""),
                    "limit_up_count_20d": int(len(group)),
                    "limit_up_count_10d": int(group["pool_date"].isin(recent10).sum()),
                    "limit_up_count_5d": int(group["pool_date"].isin(recent5).sum()),
                    "last_limit_up_date": last_date,
                    "days_since_limit_up": age,
                    "max_board_days": float(_number(group.get("board_days", pd.Series(dtype=float))).max())
                    if "board_days" in group
                    else np.nan,
                    "last_limit_board_days": last.get("board_days", np.nan),
                    "last_limit_broken_count": last.get("broken_count", np.nan),
                }
            )
        result = pd.DataFrame(rows)
    if not current.empty:
        current_latest = current.sort_values("code").drop_duplicates("code", keep="last").copy()
        current_latest = current_latest.rename(
            columns={
                "name": "current_name",
                "industry": "current_industry",
                "pct_chg": "current_pct_chg",
                "latest_price": "current_price",
                "amount": "current_amount",
                "float_mv": "current_float_mv",
                "turnover_pct": "current_turnover_pct",
                "seal_amount": "current_seal_amount",
                "first_seal_time": "current_first_seal_time",
                "last_seal_time": "current_last_seal_time",
                "broken_count": "current_broken_count",
                "board_days": "current_board_days",
            }
        )
        keep = [
            column
            for column in (
                "code",
                "current_name",
                "current_industry",
                "current_pct_chg",
                "current_price",
                "current_amount",
                "current_float_mv",
                "current_turnover_pct",
                "current_seal_amount",
                "current_first_seal_time",
                "current_last_seal_time",
                "current_broken_count",
                "current_board_days",
            )
            if column in current_latest
        ]
        current_latest = current_latest[keep]
        result = result.merge(current_latest, on="code", how="outer")
        result["current_limit_up"] = result["current_name"].notna().astype(int)
    if result.empty:
        result = pd.DataFrame(columns=["code"])
    if "current_limit_up" not in result:
        result["current_limit_up"] = 0
    if not previous.empty:
        prev = previous.sort_values("code").drop_duplicates("code", keep="last")
        prev = prev.rename(
            columns={
                "name": "previous_name",
                "industry": "previous_industry",
                "previous_board_days": "previous_limit_board_days",
                "latest_price": "previous_observation_price",
                "pct_chg": "previous_observation_pct_chg",
            }
        )
        keep = [
            column
            for column in (
                "code",
                "previous_name",
                "previous_industry",
                "previous_limit_board_days",
                "previous_observation_price",
                "previous_observation_pct_chg",
            )
            if column in prev
        ]
        result = result.merge(prev[keep], on="code", how="outer")
        result["previous_limit_up"] = result["previous_name"].notna().astype(int)
    else:
        result["previous_limit_up"] = 0
    name = result["current_name"].copy() if "current_name" in result else result.get(
        "name", pd.Series(index=result.index, dtype=object)
    )
    industry = result["current_industry"].copy() if "current_industry" in result else result.get(
        "industry", pd.Series(index=result.index, dtype=object)
    )
    if "name" in result:
        name = name.fillna(result["name"])
    if "industry" in result:
        industry = industry.fillna(result["industry"])
    result["name"] = name
    result["industry"] = industry
    result["asof_date"] = asof
    return result


def _industry_heat(history: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    if history.empty or "industry" not in history:
        return pd.DataFrame(columns=["industry", "industry_heat_5d", "industry_heat_20d"])
    recent5 = history.loc[history["pool_date"].isin(set(dates[-5:]))]
    recent20 = history.loc[history["pool_date"].isin(set(dates))]
    heat5 = recent5.groupby("industry").size().rename("industry_heat_5d")
    heat20 = recent20.groupby("industry").size().rename("industry_heat_20d")
    result = pd.concat([heat5, heat20], axis=1).reset_index()
    return result


def _preliminary_priority(
    event_features: pd.DataFrame,
    lhb_features: pd.DataFrame,
    local_codes: set[str],
) -> pd.DataFrame:
    result = event_features.copy()
    if "lhb_count" not in result.columns and not lhb_features.empty:
        result = result.merge(lhb_features, on="code", how="outer")
    if result.empty:
        return result
    for column in ("current_limit_up", "previous_limit_up", "limit_up_count_5d", "limit_up_count_20d", "lhb_count"):
        if column not in result:
            result[column] = 0
        result[column] = _number(result[column]).fillna(0)
    result["local_base"] = result["code"].isin(local_codes).astype(int)
    result["preliminary_priority"] = (
        10 * result["current_limit_up"]
        + 4 * result["previous_limit_up"]
        + 3 * result["limit_up_count_5d"].clip(upper=4)
        + 1.5 * result["limit_up_count_20d"].clip(upper=8)
        + 2 * result["lhb_count"].clip(upper=4)
        + result["local_base"]
    )
    return result.sort_values(["current_limit_up", "preliminary_priority"], ascending=False)


def _rank01(series: pd.Series) -> pd.Series:
    numeric = _number(series)
    if numeric.notna().sum() == 0 or numeric.nunique(dropna=True) <= 1:
        return pd.Series(0.0, index=series.index)
    return numeric.rank(pct=True).fillna(0.0)


def _score_candidates(frame: pd.DataFrame, market: dict[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    numeric_defaults = {
        "limit_up_count_5d": 0,
        "limit_up_count_10d": 0,
        "limit_up_count_20d": 0,
        "max_board_days": 0,
        "last_limit_board_days": 0,
        "days_since_limit_up": 99,
        "current_limit_up": 0,
        "previous_limit_up": 0,
        "current_broken_count": 0,
        "lhb_count": 0,
        "lhb_net_sum": 0,
        "lhb_net_ratio_mean_pct": 0,
        "lhb_latest_net": 0,
        "lhb_latest_net_ratio_pct": 0,
        "industry_heat_5d": 0,
        "ret_1d": np.nan,
        "ret_5d": np.nan,
        "ret_20d": np.nan,
        "minute_from_prev_close": np.nan,
        "minute_late_momentum_30m": np.nan,
        "minute_amount_ratio_5d": np.nan,
        "daily_amount_ratio_5d": np.nan,
    }
    for column, default in numeric_defaults.items():
        if column not in result:
            result[column] = default
        result[column] = _number(result[column])
        if default == 0 or column in {"days_since_limit_up"}:
            result[column] = result[column].fillna(default)

    result["is_st"] = result.get("name", pd.Series("", index=result.index)).astype(str).str.contains(
        r"ST|退", case=False, regex=True
    )
    result["market_board"] = result["code"].map(lambda value: _market_symbol(value)[:2].upper())

    # Event/leader component: repeated limit-up activity, board height,
    # recency, capital-flow confirmation and industry co-movement.
    recency = np.exp(-result["days_since_limit_up"].clip(lower=0, upper=99) / 5.0)
    board_score = _clamp(result["max_board_days"] / 4.0)
    repeat_score = _clamp(result["limit_up_count_5d"] / 3.0) * 0.65 + _clamp(
        result["limit_up_count_20d"] / 6.0
    ) * 0.35
    lhb_activity = _clamp(result["lhb_count"] / 3.0)
    industry_score = _rank01(result["industry_heat_5d"])
    result["event_score"] = (
        28 * repeat_score
        + 18 * board_score
        + 12 * recency
        + 12 * lhb_activity
        + 5 * industry_score
    )

    # Momentum component.  These are end-of-day values for the current watchlist;
    # minute values are included only when the current 5-minute fetch succeeded.
    ret1 = result["ret_1d"].fillna(result["current_pct_chg"] / 100.0 if "current_pct_chg" in result else 0.0)
    ret5 = result["ret_5d"]
    intraday = result["minute_from_prev_close"].fillna(ret1)
    late = result["minute_late_momentum_30m"].fillna(0.0)
    amount_ratio = result["minute_amount_ratio_5d"].fillna(result["daily_amount_ratio_5d"]).fillna(1.0)
    result["momentum_score"] = (
        8 * _clamp((ret1 + 0.08) / 0.18)
        + 10 * _clamp((ret5.fillna(0.0) + 0.10) / 0.30)
        + 8 * _clamp((intraday + 0.03) / 0.15)
        + 4 * _clamp((late + 0.02) / 0.08)
        + 5 * _clamp(amount_ratio / 2.5)
    )

    # Risk controls: late/fragile boards, excessive recent extension, negative
    # LHB evidence, and Beijing-board liquidity/execution differences.
    broken = result["current_broken_count"].fillna(0)
    late_seal_penalty = pd.Series(0.0, index=result.index)
    if "current_last_seal_time" in result:
        seal_text = result["current_last_seal_time"].fillna("").astype(str).str.extract(r"(\d{4,6})", expand=False)
        seal_num = pd.to_numeric(seal_text, errors="coerce")
        # 13:30 -> 0, 14:30 -> 1, and later increases the penalty.
        seal_minutes = (seal_num // 100 - 9) * 60 + seal_num % 100
        late_seal_penalty = _clamp((seal_minutes - 270) / 60.0)
    overheat = _clamp((result["ret_20d"].fillna(0.0) - 0.35) / 0.45)
    negative_lhb = _clamp(-result["lhb_net_ratio_mean_pct"].fillna(0.0) / 5.0)
    result["risk_penalty"] = (
        8 * _clamp(broken / 3.0)
        + 8 * late_seal_penalty * result["current_limit_up"]
        + 8 * overheat
        + 5 * negative_lhb
        + 5 * (result["market_board"] == "BJ").astype(float)
    )
    result["score"] = (result["event_score"] + result["momentum_score"] - result["risk_penalty"]).clip(-20, 100)
    result.loc[result["is_st"], "score"] = -999.0

    def category(row: pd.Series) -> str:
        if bool(row.get("is_st", False)):
            return "排除-ST/退市风险"
        if row.get("current_limit_up", 0) and row.get("current_board_days", 0) >= 2:
            return "强势核心-收盘连板"
        if row.get("current_limit_up", 0):
            return "强势观察-当日涨停"
        if row.get("previous_limit_up", 0) and row.get("ret_1d", 0) > -0.05:
            return "分歧观察-昨日涨停"
        if row.get("lhb_count", 0) > 0:
            return "资金观察-龙虎榜"
        return "趋势备选"

    result["category"] = result.apply(category, axis=1)
    result["rank"] = result["score"].rank(method="first", ascending=False).astype(int)
    minute_available = (
        result["minute_available"].fillna(False).astype(bool)
        if "minute_available" in result
        else pd.Series(False, index=result.index)
    )
    daily_available = (
        result["daily_available"].fillna(False).astype(bool)
        if "daily_available" in result
        else pd.Series(False, index=result.index)
    )
    result["data_quality"] = np.select(
        [
            minute_available & daily_available,
            daily_available,
        ],
        ["A:事件+日线+5分钟", "B:事件+日线"],
        default="C:事件数据",
    )
    return result.sort_values(["is_st", "score"], ascending=[True, False]).reset_index(drop=True)


def _market_summary(
    asof: pd.Timestamp,
    current: pd.DataFrame,
    limit_down: pd.DataFrame,
    broken: pd.DataFrame,
    history: pd.DataFrame,
    lhb: pd.DataFrame,
    dates: list[pd.Timestamp],
) -> dict[str, Any]:
    industry = (
        current.groupby("industry").size().sort_values(ascending=False).head(10).to_dict()
        if not current.empty and "industry" in current
        else {}
    )
    max_board = float(_number(current.get("board_days", pd.Series(dtype=float))).max()) if not current.empty else 0
    if len(current) >= 2 * len(limit_down) and len(current) >= 40:
        regime = "偏强但分歧较大" if len(broken) >= max(10, int(len(current) * 0.25)) else "偏强"
    elif len(limit_down) >= len(current):
        regime = "偏弱"
    else:
        regime = "中性"
    return {
        "asof_date": asof,
        "latest_complete_session": asof,
        "trading_dates_used": dates,
        "limit_up_count": int(len(current)),
        "limit_down_count": int(len(limit_down)),
        "broken_board_stock_count": int(len(broken)),
        "broken_board_events": int(_number(broken.get("broken_count", pd.Series(dtype=float))).sum())
        if not broken.empty
        else 0,
        "max_board_days": max_board,
        "lhb_row_count": int(len(lhb)),
        "lhb_stock_count": int(lhb["code"].nunique()) if not lhb.empty and "code" in lhb else 0,
        "lhb_net_sum_native": float(_number(lhb.get("lhb_net_amount", pd.Series(dtype=float))).sum())
        if not lhb.empty
        else 0.0,
        "market_regime_proxy": regime,
        "top_limit_up_industries": industry,
        "interpretation": "情绪代理=涨停数量/炸板/跌停/连板高度；行业热度=近20个交易日涨停池的行业共振。",
        "data_cutoff_rule": "所有字段只使用不晚于 asof_date 收盘可见的数据；不含未来收益。",
    }


def _make_forward_template(result: pd.DataFrame, path: Path, top_n: int) -> None:
    columns = [
        "asof_date",
        "rank",
        "instrument",
        "code",
        "name",
        "category",
        "score",
        "close",
        "current_limit_up",
        "current_board_days",
        "industry",
        "ret_1d",
        "ret_5d",
        "lhb_count",
        "lhb_net_sum",
        "entry_date_next_session",
        "entry_price_reference",
        "forward_1d_return",
        "forward_3d_return",
        "forward_5d_return",
        "forward_10d_return",
        "notes",
    ]
    frame = result.loc[result["score"] > -900].head(top_n).copy()
    frame["instrument"] = frame["code"].map(_instrument)
    frame["entry_date_next_session"] = ""
    frame["entry_price_reference"] = np.nan
    for column in ("forward_1d_return", "forward_3d_return", "forward_5d_return", "forward_10d_return"):
        frame[column] = np.nan
    frame["notes"] = "收盘后生成；未来验证时填入下一交易日可成交价格和持有期收益"
    for column in columns:
        if column not in frame:
            frame[column] = np.nan
    frame[columns].to_csv(path, index=False, encoding="utf-8-sig")


def run(config: CurrentConfig) -> dict[str, Any]:
    _clear_proxy_environment()
    asof_requested = _parse_asof(config.asof_date)
    dates = _trade_dates(asof_requested, config.lookback_sessions)
    if not dates:
        raise RuntimeError("no trading dates available")
    asof = dates[-1]
    lhb_dates = dates[-config.lhb_lookback_sessions :]
    fetch_log: list[dict[str, Any]] = []

    # 1) Eastmoney event tables.
    limit_up_frames: list[pd.DataFrame] = []
    for date in dates:
        raw = _fetch_cached_table(
            "limit_up_pool",
            f"{date:%Y%m%d}.parquet",
            lambda date=date: ak.stock_zt_pool_em(date=date.strftime("%Y%m%d")),
            fetch_log,
            no_cache=config.no_cache,
        )
        normalized = _normalise_pool(raw, date, "limit_up")
        if not normalized.empty:
            limit_up_frames.append(normalized)
    history = pd.concat(limit_up_frames, ignore_index=True) if limit_up_frames else pd.DataFrame()

    latest_previous_raw = _fetch_cached_table(
        "previous_limit_up_pool",
        f"{asof:%Y%m%d}.parquet",
        lambda: ak.stock_zt_pool_previous_em(date=asof.strftime("%Y%m%d")),
        fetch_log,
        no_cache=config.no_cache,
    )
    previous_date = dates[-2] if len(dates) >= 2 else asof
    previous = _normalise_pool(latest_previous_raw, previous_date, "previous_limit_up")

    down_raw = _fetch_cached_table(
        "limit_down_pool",
        f"{asof:%Y%m%d}.parquet",
        lambda: ak.stock_zt_pool_dtgc_em(date=asof.strftime("%Y%m%d")),
        fetch_log,
        no_cache=config.no_cache,
    )
    limit_down = _normalise_pool(down_raw, asof, "limit_down")
    broken_raw = _fetch_cached_table(
        "broken_board_pool",
        f"{asof:%Y%m%d}.parquet",
        lambda: ak.stock_zt_pool_zbgc_em(date=asof.strftime("%Y%m%d")),
        fetch_log,
        no_cache=config.no_cache,
    )
    broken = _normalise_pool(broken_raw, asof, "broken_board")

    lhb_start = lhb_dates[0] if lhb_dates else asof
    lhb_raw = _fetch_cached_table(
        "lhb_detail",
        f"{lhb_start:%Y%m%d}_{asof:%Y%m%d}.parquet",
        lambda: ak.stock_lhb_detail_em(
            start_date=lhb_start.strftime("%Y%m%d"), end_date=asof.strftime("%Y%m%d")
        ),
        fetch_log,
        no_cache=config.no_cache,
    )
    lhb = _normalise_lhb(lhb_raw)
    lhb_features = _aggregate_lhb(lhb)

    current = history.loc[history["pool_date"] == asof].copy() if not history.empty else pd.DataFrame()
    event_features = _aggregate_limit_up(history, current, previous, dates, asof)
    heat = _industry_heat(history, dates)
    if not heat.empty and not event_features.empty:
        event_features = event_features.merge(heat, on="industry", how="left")
    local_codes = _load_local_base_codes()
    priority = _preliminary_priority(event_features, lhb_features, local_codes)
    if priority.empty:
        raise RuntimeError("no current event data returned")

    # Keep every current/previous-limit-up name, then use the public event score
    # to control the amount of quote traffic for less recent names.
    must_keep = set(current.get("code", pd.Series(dtype=str))) | set(previous.get("code", pd.Series(dtype=str)))
    must_keep |= local_codes
    priority_codes = priority["code"].tolist()
    selected_codes = [code for code in priority_codes if code in must_keep]
    remainder = [code for code in priority_codes if code not in set(selected_codes)]
    selected_codes.extend(remainder[: max(0, config.max_daily_codes - len(selected_codes))])
    selected_codes = selected_codes[: config.max_daily_codes]

    daily_start = asof - timedelta(days=config.daily_calendar_days)
    daily_frames: dict[str, pd.DataFrame] = {}
    daily_errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, config.workers)) as executor:
        futures = {
            executor.submit(_fetch_daily_one, code, daily_start, asof, config.no_cache): code
            for code in selected_codes
        }
        for future in as_completed(futures):
            code, frame, error = future.result()
            if error:
                daily_errors.append({"code": code, "error": error})
            elif not frame.empty:
                daily_frames[code] = frame

    daily_feature_rows: list[dict[str, Any]] = []
    for code in selected_codes:
        features = _daily_features(daily_frames.get(code, pd.DataFrame()), asof)
        features["code"] = code
        daily_feature_rows.append(features)
    daily_features = pd.DataFrame(daily_feature_rows)

    result = event_features.loc[event_features["code"].isin(selected_codes)].copy()
    result = result.merge(lhb_features, on="code", how="left").merge(daily_features, on="code", how="left")
    result["name"] = result["name"].fillna(result.get("current_name", ""))
    result["industry"] = result["industry"].fillna(result.get("current_industry", ""))

    # Fetch minute data only for the most relevant names, keeping the output
    # useful even if one provider is rate-limited.
    preliminary = _preliminary_priority(result, lhb_features, local_codes)
    minute_codes = preliminary["code"].head(config.max_minute_codes).tolist()
    minute_feature_rows: list[dict[str, Any]] = []
    minute_errors: list[dict[str, str]] = []
    minute_sources: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, config.workers)) as executor:
        futures = {
            executor.submit(_fetch_minute_one, code, asof, config.no_cache): code for code in minute_codes
        }
        for future in as_completed(futures):
            code, frame, error, source = future.result()
            features = _minute_features(frame, asof)
            features["code"] = code
            minute_feature_rows.append(features)
            if source:
                minute_sources[code] = source
            if error:
                minute_errors.append({"code": code, "error": error})
    if minute_feature_rows:
        result = result.merge(pd.DataFrame(minute_feature_rows), on="code", how="left")
    result["minute_source"] = result["code"].map(minute_sources)

    market = _market_summary(asof, current, limit_down, broken, history, lhb, dates)
    result = _score_candidates(result, market)
    result["instrument"] = result["code"].map(_instrument)
    result["source_event"] = "eastmoney_zt_pool_lhb_via_akshare"
    result["source_daily"] = "tencent_daily_via_akshare"
    result["knowledge_time"] = asof

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = CURRENT_OUTPUT_DIR / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    output_columns = [
        "rank",
        "instrument",
        "code",
        "name",
        "category",
        "score",
        "event_score",
        "momentum_score",
        "risk_penalty",
        "data_quality",
        "industry",
        "industry_heat_5d",
        "current_limit_up",
        "current_board_days",
        "previous_limit_up",
        "limit_up_count_5d",
        "limit_up_count_20d",
        "max_board_days",
        "days_since_limit_up",
        "current_broken_count",
        "current_last_seal_time",
        "current_turnover_pct",
        "lhb_count",
        "lhb_net_sum",
        "lhb_net_ratio_mean_pct",
        "lhb_latest_net",
        "lhb_latest_net_ratio_pct",
        "lhb_positive_ratio",
        "lhb_latest_date",
        "lhb_latest_reason",
        "close",
        "ret_1d",
        "ret_5d",
        "ret_20d",
        "drawdown_20d",
        "daily_amount_ratio_5d",
        "minute_from_prev_close",
        "minute_from_open",
        "minute_from_high",
        "minute_late_momentum_30m",
        "minute_amount_ratio_5d",
        "minute_source",
        "source_event",
        "source_daily",
        "knowledge_time",
    ]
    for column in output_columns:
        if column not in result:
            result[column] = np.nan
    result[output_columns].to_csv(output_dir / "candidate_scores.csv", index=False, encoding="utf-8-sig")
    result[output_columns].to_json(output_dir / "candidate_scores.json", orient="records", force_ascii=False, indent=2, date_format="iso")
    eligible = result.loc[result["score"] > -900].copy()
    current_watch = eligible.loc[eligible["current_limit_up"] == 1].head(config.top_n)
    recent_watch = eligible.loc[
        (eligible["current_limit_up"] == 0)
        & ((eligible["previous_limit_up"] == 1) | (eligible["lhb_count"].fillna(0) > 0))
    ].head(config.top_n)
    current_watch[output_columns].to_csv(
        output_dir / "current_limit_up_watchlist.csv", index=False, encoding="utf-8-sig"
    )
    recent_watch[output_columns].to_csv(
        output_dir / "recent_event_watchlist.csv", index=False, encoding="utf-8-sig"
    )
    _write_json(output_dir / "market_summary.json", market)
    _write_json(
        output_dir / "fetch_log.json",
        {
            "daily_error_count": len(daily_errors),
            "minute_error_count": len(minute_errors),
            "daily_errors": daily_errors,
            "minute_errors": minute_errors,
            "fetch_log": fetch_log,
        },
    )
    _make_forward_template(result, output_dir / "forward_validation_template.csv", config.top_n)

    latest_payload = {
        "generated_at": datetime.now(),
        "asof_date": asof,
        "requested_asof_date": asof_requested,
        "config": asdict(config),
        "market_summary": market,
        "top_candidates": json.loads(
            result.loc[result["score"] > -900, output_columns].head(config.top_n).to_json(
                orient="records", force_ascii=False, date_format="iso"
            )
        ),
        "current_limit_up_watchlist": json.loads(
            current_watch[output_columns].to_json(orient="records", force_ascii=False, date_format="iso")
        ),
        "recent_event_watchlist": json.loads(
            recent_watch[output_columns].to_json(orient="records", force_ascii=False, date_format="iso")
        ),
        "artifacts": {
            "candidate_scores_csv": str(output_dir / "candidate_scores.csv"),
            "candidate_scores_json": str(output_dir / "candidate_scores.json"),
            "current_limit_up_watchlist": str(output_dir / "current_limit_up_watchlist.csv"),
            "recent_event_watchlist": str(output_dir / "recent_event_watchlist.csv"),
            "market_summary": str(output_dir / "market_summary.json"),
            "forward_validation_template": str(output_dir / "forward_validation_template.csv"),
        },
    }
    _write_json(output_dir / "result.json", latest_payload)
    _write_json(OUTPUT_DIR / "current_yangjia_candidates_latest.json", latest_payload)

    print(f"asof={asof:%Y-%m-%d} limit_up={len(current)} limit_down={len(limit_down)} broken={len(broken)} lhb_rows={len(lhb)}")
    print(f"daily_success={len(daily_features.loc[daily_features.get('daily_available', False).astype(bool)]) if not daily_features.empty else 0}/{len(selected_codes)} minute_attempted={len(minute_codes)}")
    display = result.loc[result["score"] > -900].head(config.top_n)
    for _, row in display.iterrows():
        print(
            f"{int(row['rank']):>2} {row['instrument']:<8} {str(row.get('name', '')):<8} "
            f"score={row['score']:>6.2f} {row.get('category', '')} "
            f"行业={row.get('industry', '')} 连板={row.get('current_board_days', np.nan)} "
            f"龙虎榜={row.get('lhb_count', 0)}"
        )
    print(f"output={output_dir}")
    return latest_payload


def parse_args() -> CurrentConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asof-date", default="", help="YYYYMMDD; defaults to today then uses latest completed session")
    parser.add_argument("--lookback-sessions", type=int, default=20)
    parser.add_argument("--lhb-lookback-sessions", type=int, default=20)
    parser.add_argument("--max-daily-codes", type=int, default=220)
    parser.add_argument("--max-minute-codes", type=int, default=60)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--daily-calendar-days", type=int, default=150)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    return CurrentConfig(
        asof_date=args.asof_date,
        lookback_sessions=max(5, args.lookback_sessions),
        lhb_lookback_sessions=max(5, args.lhb_lookback_sessions),
        max_daily_codes=max(20, args.max_daily_codes),
        max_minute_codes=max(0, args.max_minute_codes),
        top_n=max(1, args.top_n),
        workers=max(1, args.workers),
        daily_calendar_days=max(60, args.daily_calendar_days),
        no_cache=args.no_cache,
    )


if __name__ == "__main__":
    run(parse_args())
