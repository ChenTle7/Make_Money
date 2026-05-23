"""ETF数据获取 - 日线/分钟线/实时行情"""
import akshare as ak
import requests
import pandas as pd
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


def fetch_etf_daily(code: str, days: int = 180) -> pd.DataFrame:
    """获取ETF日K线，AKShare优先，腾讯fallback"""
    # 尝试AKShare
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        df = ak.fund_etf_hist_em(symbol=code, period="daily",
                                 start_date=start, end_date=end, adjust="qfq")
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume"
        })
        log.info(f"  {code}: AKShare日线成功")
    except Exception as e:
        log.warning(f"  {code}: AKShare失败({e.__class__.__name__})，使用腾讯接口")
        market = "sh" if code.startswith(("5", "6")) else "sz"
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        params = {"param": f"{market}{code},day,,,{days},qfq"}
        r = requests.get(url, params=params, timeout=10)
        raw = r.json()["data"][f"{market}{code}"]["day"]
        df = pd.DataFrame(raw, columns=["date", "open", "close", "high", "low", "volume"])

    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "close", "high", "low"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(float)
    df["amplitude"] = ((df["high"] - df["low"]) / df["low"] * 100).round(2)
    df = df.sort_values("date").tail(days).reset_index(drop=True)
    return df


def fetch_etf_minute(code: str, scale: int = 5) -> pd.DataFrame:
    """获取分钟K线，新浪接口"""
    market = "sh" if code.startswith(("5", "6")) else "sz"
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": f"{market}{code}", "scale": str(scale), "ma": "no", "datalen": "240"}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    df = pd.DataFrame(data)
    df["day"] = pd.to_datetime(df["day"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df


def fetch_etf_realtime(code: str) -> dict:
    """获取ETF实时行情，使用新浪接口"""
    market = "sh" if code.startswith(("5", "6")) else "sz"
    url = f"https://hq.sinajs.cn/list={market}{code}"
    try:
        r = requests.get(url, timeout=10, headers={"Referer": "https://finance.sina.com.cn"})
        r.encoding = "gbk"
        line = r.text.strip()
        # 解析: var hq_str_sh513090="名称,昨收,今开,现价,最高,最低,...";
        data_str = line.split('"')[1]
        parts = data_str.split(",")
        return {
            "code": code,
            "name": parts[0],
            "prev_close": float(parts[1]),
            "open": float(parts[2]),
            "price": float(parts[3]),
            "high": float(parts[4]),
            "low": float(parts[5]),
            "change_pct": round((float(parts[3]) - float(parts[1])) / float(parts[1]) * 100, 2) if float(parts[1]) > 0 else 0,
            "volume": float(parts[8]),
            "amount": float(parts[9]),
        }
    except Exception as e:
        log.error(f"  {code}: 实时行情获取失败: {e}")
        return {"code": code, "error": str(e)}


def fetch_all_etfs(codes: list = None, days: int = 180, use_cache: bool = True) -> dict:
    """批量获取所有ETF日线数据，带缓存"""
    from config import WATCHLIST, DATA_DIR

    if codes is None:
        codes = [etf["code"] for etf in WATCHLIST]

    date_str = datetime.now().strftime("%Y-%m-%d")
    cache_dir = DATA_DIR / date_str
    cache_dir.mkdir(parents=True, exist_ok=True)

    result = {}
    for i, code in enumerate(codes):
        cache_file = cache_dir / f"etf_{code}.json"

        # 尝试读缓存
        if use_cache and cache_file.exists():
            try:
                df = pd.read_json(cache_file, orient="split")
                df["date"] = pd.to_datetime(df["date"])
                result[code] = df
                log.info(f"  {code}: 使用缓存 ({len(df)}条)")
                continue
            except Exception:
                pass

        # 获取数据
        try:
            df = fetch_etf_daily(code, days=days)
            result[code] = df
            # 写缓存
            df.to_json(cache_file, orient="split", date_format="iso")
            log.info(f"  {code}: 获取成功 ({len(df)}条)")
        except Exception as e:
            log.error(f"  {code}: 获取失败: {e}")

        # 限速
        if i < len(codes) - 1:
            time.sleep(1)

    return result
