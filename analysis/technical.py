"""技术指标计算 - 纯pandas/numpy实现"""
import pandas as pd
import numpy as np


def calc_ma(df: pd.DataFrame, periods: list = None) -> pd.DataFrame:
    """计算均线 MA5/10/20/60"""
    if periods is None:
        periods = [5, 10, 20, 60]
    for p in periods:
        if len(df) >= p:
            df[f"MA{p}"] = df["close"].rolling(window=p).mean().round(4)
    return df


def calc_ema(series: pd.Series, span: int) -> pd.Series:
    """计算EMA"""
    return series.ewm(span=span, adjust=False).mean()


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """计算MACD: DIF, DEA, MACD柱"""
    if len(df) < slow + signal:
        return df
    ema_fast = calc_ema(df["close"], fast)
    ema_slow = calc_ema(df["close"], slow)
    df["DIF"] = (ema_fast - ema_slow).round(4)
    df["DEA"] = calc_ema(df["DIF"], signal).round(4)
    df["MACD_H"] = ((df["DIF"] - df["DEA"]) * 2).round(4)
    return df


def calc_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """计算KDJ"""
    if len(df) < n:
        return df
    low_n = df["low"].rolling(window=n).min()
    high_n = df["high"].rolling(window=n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n) * 100
    rsv = rsv.fillna(50)  # 默认值
    df["K"] = rsv.ewm(com=m1 - 1, adjust=False).mean().round(2)
    df["D"] = df["K"].ewm(com=m2 - 1, adjust=False).mean().round(2)
    df["J"] = (3 * df["K"] - 2 * df["D"]).round(2)
    return df


def calc_rsi(df: pd.DataFrame, periods: list = None) -> pd.DataFrame:
    """计算RSI"""
    if periods is None:
        periods = [6, 12, 24]
    delta = df["close"].diff()
    for p in periods:
        if len(df) < p:
            continue
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=p).mean()
        avg_loss = loss.rolling(window=p).mean()
        rs = avg_gain / avg_loss
        rs = rs.replace([np.inf, -np.inf], 0)
        df[f"RSI{p}"] = (100 - 100 / (1 + rs)).round(2)
    return df


def calc_bollinger(df: pd.DataFrame, period: int = 20, std_dev: int = 2) -> pd.DataFrame:
    """计算布林带"""
    if len(df) < period:
        return df
    df["BOLL_MID"] = df["close"].rolling(window=period).mean().round(4)
    std = df["close"].rolling(window=period).std()
    df["BOLL_UP"] = (df["BOLL_MID"] + std_dev * std).round(4)
    df["BOLL_LOW"] = (df["BOLL_MID"] - std_dev * std).round(4)
    return df


def calc_volume_analysis(df: pd.DataFrame) -> dict:
    """量能分析"""
    if len(df) < 20:
        return {"avg_vol_5d": 0, "avg_vol_20d": 0, "vol_ratio": 1.0, "is_volume_surge": False}
    avg_5 = df["volume"].tail(5).mean()
    avg_20 = df["volume"].tail(20).mean()
    ratio = round(avg_5 / avg_20, 2) if avg_20 > 0 else 1.0
    latest_vol = df["volume"].iloc[-1]
    return {
        "avg_vol_5d": round(avg_5, 0),
        "avg_vol_20d": round(avg_20, 0),
        "vol_ratio": ratio,
        "is_volume_surge": latest_vol > avg_20 * 2,
    }


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有技术指标"""
    df = df.copy()
    df = calc_ma(df)
    df = calc_macd(df)
    df = calc_kdj(df)
    df = calc_rsi(df)
    df = calc_bollinger(df)
    return df
