"""大盘指数数据获取 - A股/港股/美股"""
import akshare as ak
import pandas as pd
import time
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


def fetch_ashare_index(code: str, name: str, days: int = 30) -> dict:
    """获取A股指数数据，使用新浪数据源"""
    try:
        df = ak.stock_zh_index_daily(symbol=code)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").tail(days).reset_index(drop=True)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        change_pct = round((latest["close"] - prev["close"]) / prev["close"] * 100, 2)
        return {
            "name": name, "code": code,
            "close": round(latest["close"], 2),
            "change_pct": change_pct,
            "open": round(latest["open"], 2),
            "high": round(latest["high"], 2),
            "low": round(latest["low"], 2),
        }
    except Exception as e:
        log.error(f"A股指数 {name}({code}) 获取失败: {e}")
        return {"name": name, "code": code, "error": str(e)}


def fetch_hk_index(symbol: str, name: str, days: int = 30) -> dict:
    """获取港股指数数据，使用新浪数据源"""
    try:
        df = ak.stock_hk_index_daily_sina(symbol=symbol)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").tail(days).reset_index(drop=True)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        change_pct = round((latest["close"] - prev["close"]) / prev["close"] * 100, 2)
        return {
            "name": name, "code": symbol,
            "close": round(float(latest["close"]), 2),
            "change_pct": change_pct,
            "open": round(float(latest["open"]), 2),
            "high": round(float(latest["high"]), 2),
            "low": round(float(latest["low"]), 2),
        }
    except Exception as e:
        log.error(f"港股指数 {name}({symbol}) 获取失败: {e}")
        return {"name": name, "code": symbol, "error": str(e)}


def fetch_us_index(symbol: str, name: str, days: int = 30) -> dict:
    """获取美股指数数据，使用新浪数据源"""
    try:
        df = ak.index_us_stock_sina(symbol=symbol)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").tail(days).reset_index(drop=True)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        change_pct = round((latest["close"] - prev["close"]) / prev["close"] * 100, 2)
        return {
            "name": name, "code": symbol,
            "close": round(float(latest["close"]), 2),
            "change_pct": change_pct,
            "open": round(float(latest["open"]), 2),
            "high": round(float(latest["high"]), 2),
            "low": round(float(latest["low"]), 2),
        }
    except Exception as e:
        log.error(f"美股指数 {name}({symbol}) 获取失败: {e}")
        return {"name": name, "code": symbol, "error": str(e)}


def fetch_all_indices() -> dict:
    """获取全部7个大盘指数"""
    from config import A_SHARE_INDICES, HK_INDICES, US_INDICES

    ashare = {}
    for name, code in A_SHARE_INDICES.items():
        ashare[name] = fetch_ashare_index(code, name)
        time.sleep(0.5)

    hk = {}
    for name, symbol in HK_INDICES.items():
        hk[name] = fetch_hk_index(symbol, name)
        time.sleep(0.5)

    us = {}
    for name, symbol in US_INDICES.items():
        us[name] = fetch_us_index(symbol, name)
        time.sleep(0.5)

    return {
        "ashare": ashare,
        "hk": hk,
        "us": us,
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
