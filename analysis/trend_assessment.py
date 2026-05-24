"""趋势判断与超卖评分"""
import pandas as pd
import numpy as np
from analysis.technical import compute_all_indicators, calc_volume_analysis


class TrendAssessment:
    """单只ETF的趋势分析"""

    def __init__(self, code: str, name: str, df: pd.DataFrame):
        self.code = code
        self.name = name
        self.df = compute_all_indicators(df.copy())
        self.vol_analysis = calc_volume_analysis(df)

    def assess(self) -> dict:
        """综合评估"""
        trend_6m, trend_6m_pct = self._trend_by_period(120)
        trend_3m, trend_3m_pct = self._trend_by_period(60)
        trend_1m, trend_1m_pct = self._trend_by_period(20)
        trend_1w, trend_1w_pct = self._trend_by_period(5)

        is_prolonged, down_days = self._prolonged_downtrend()
        oversold = self._oversold_score()
        signals = self._individual_signals()
        strength = self._signal_strength(oversold, signals)

        if oversold >= 6 and is_prolonged:
            grid_rec = "aggressive"
        elif oversold >= 4:
            grid_rec = "normal"
        elif trend_1m == "涨" and trend_1w == "涨":
            grid_rec = "conservative"
        else:
            grid_rec = "normal"

        latest = self.df.iloc[-1]
        return {
            "code": self.code,
            "name": self.name,
            "trend_6m": trend_6m,
            "trend_3m": trend_3m,
            "trend_1m": trend_1m,
            "trend_1w": trend_1w,
            "trend_6m_pct": trend_6m_pct,
            "trend_3m_pct": trend_3m_pct,
            "trend_1m_pct": trend_1m_pct,
            "trend_1w_pct": trend_1w_pct,
            "is_prolonged_downtrend": is_prolonged,
            "downtrend_days": down_days,
            "oversold_score": oversold,
            "signal_strength": strength,
            "signals_detail": signals,
            "grid_recommendation": grid_rec,
            "volume_analysis": self.vol_analysis,
            "rsi_value": round(float(latest.get("RSI6", 50)), 1),
            "kdj_j": round(float(latest.get("J", 50)), 1),
        }

    def _trend_by_period(self, days: int) -> tuple:
        """判断指定周期内的趋势，返回 (趋势标签, 累计涨跌幅%)"""
        df = self.df.tail(days)
        if len(df) < 5:
            return "未知", 0.0
        first_close = df["close"].iloc[0]
        last_close = df["close"].iloc[-1]
        change_pct = round((last_close - first_close) / first_close * 100, 2)

        if "MA20" not in df.columns or df["MA20"].isna().all():
            if change_pct > 3:
                return "涨", change_pct
            elif change_pct < -3:
                return "跌", change_pct
            return "横盘", change_pct

        valid = df.dropna(subset=["MA20"])
        if len(valid) < 5:
            return "横盘", change_pct
        above = (valid["close"] > valid["MA20"]).sum()
        ratio = above / len(valid)
        if ratio > 0.6:
            return "涨", change_pct
        elif ratio < 0.4:
            return "跌", change_pct
        return "横盘", change_pct

    def _prolonged_downtrend(self) -> tuple:
        """判断是否长期下跌（连续低于MA20）"""
        df = self.df
        if "MA20" not in df.columns:
            return False, 0
        consecutive = 0
        for i in range(len(df) - 1, -1, -1):
            if pd.isna(df["MA20"].iloc[i]):
                break
            if df["close"].iloc[i] < df["MA20"].iloc[i]:
                consecutive += 1
            else:
                break
        return consecutive > 20, consecutive

    def _oversold_score(self) -> int:
        """超卖评分 0-10"""
        score = 0
        latest = self.df.iloc[-1]

        # KDJ超卖 +3
        if "K" in self.df.columns and not pd.isna(latest.get("K")):
            if latest["K"] < 20:
                score += 3
            elif latest["K"] < 30:
                score += 1

        # RSI超卖 +2
        if "RSI6" in self.df.columns and not pd.isna(latest.get("RSI6")):
            if latest["RSI6"] < 30:
                score += 2
            elif latest["RSI6"] < 40:
                score += 1

        # 布林带下轨 +2
        if "BOLL_LOW" in self.df.columns and not pd.isna(latest.get("BOLL_LOW")):
            if latest["close"] <= latest["BOLL_LOW"] * 1.01:
                score += 2

        # MACD柱转正 +2
        if "MACD_H" in self.df.columns and len(self.df) >= 3:
            recent_h = self.df["MACD_H"].tail(5).dropna()
            if len(recent_h) >= 3:
                if recent_h.iloc[-1] > 0 and recent_h.iloc[-2] <= 0:
                    score += 2

        # 放量 +1
        if self.vol_analysis.get("is_volume_surge"):
            score += 1

        return min(score, 10)

    def _individual_signals(self) -> dict:
        """各指标独立信号"""
        latest = self.df.iloc[-1]
        signals = {}

        # MA信号
        ma_signals = []
        for p in [5, 10, 20]:
            col = f"MA{p}"
            if col in self.df.columns and not pd.isna(latest.get(col)):
                if latest["close"] > latest[col]:
                    ma_signals.append("above")
                else:
                    ma_signals.append("below")
        if len(ma_signals) >= 2:
            above_count = ma_signals.count("above")
            if above_count >= 2:
                signals["MA"] = "bullish"
            elif above_count == 0:
                signals["MA"] = "bearish"
            else:
                signals["MA"] = "neutral"
        else:
            signals["MA"] = "neutral"

        # MACD信号
        if "DIF" in self.df.columns and not pd.isna(latest.get("DIF")):
            if latest["DIF"] > latest.get("DEA", 0):
                signals["MACD"] = "bullish"
            else:
                signals["MACD"] = "bearish"
        else:
            signals["MACD"] = "neutral"

        # KDJ信号
        if "K" in self.df.columns and not pd.isna(latest.get("K")):
            k = latest["K"]
            if k < 20:
                signals["KDJ"] = "oversold"
            elif k > 80:
                signals["KDJ"] = "overbought"
            else:
                signals["KDJ"] = "neutral"
        else:
            signals["KDJ"] = "neutral"

        # RSI信号
        if "RSI6" in self.df.columns and not pd.isna(latest.get("RSI6")):
            rsi = latest["RSI6"]
            if rsi < 30:
                signals["RSI"] = "oversold"
            elif rsi > 70:
                signals["RSI"] = "overbought"
            else:
                signals["RSI"] = "neutral"
        else:
            signals["RSI"] = "neutral"

        # 布林带信号
        if "BOLL_UP" in self.df.columns and not pd.isna(latest.get("BOLL_UP")):
            up = latest["BOLL_UP"]
            low = latest["BOLL_LOW"]
            price = latest["close"]
            if price <= low * 1.02:
                signals["BOLL"] = "near_lower"
            elif price >= up * 0.98:
                signals["BOLL"] = "near_upper"
            else:
                signals["BOLL"] = "middle"
        else:
            signals["BOLL"] = "middle"

        # 量能信号
        if self.vol_analysis.get("is_volume_surge"):
            signals["Volume"] = "surge"
        elif self.vol_analysis.get("vol_ratio", 1) < 0.7:
            signals["Volume"] = "shrink"
        else:
            signals["Volume"] = "normal"

        return signals

    def _signal_strength(self, oversold: int, signals: dict) -> str:
        """综合信号强度"""
        bullish = sum(1 for v in signals.values() if v in ("bullish", "oversold", "near_lower"))
        bearish = sum(1 for v in signals.values() if v in ("bearish", "overbought", "near_upper"))

        if oversold >= 6 and bullish >= 3:
            return "强买"
        elif oversold >= 4 or (bullish >= 3 and bearish <= 1):
            return "买入"
        elif bearish >= 4:
            return "卖出"
        elif bearish >= 3:
            return "弱势"
        return "中性"
