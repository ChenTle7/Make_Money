"""网格策略回测 - 验证网格交易策略的历史表现"""
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# 项目根目录加入path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import WATCHLIST, COMMISSION_RATE, GRID_COUNT, CAPITAL_PER_ETF
from data.etf_data import fetch_etf_daily
from analysis.grid_params import calculate_grid, _find_support_resistance
from analysis.trend_assessment import TrendAssessment

log = logging.getLogger(__name__)


def _simulate_grid(
    df_bt: pd.DataFrame,
    grid_params,
    commission_rate: float = COMMISSION_RATE,
    max_active_grids: int = 5,      # 最多同时持有5格（防止6格全满）
    stop_loss_pct: float = 10.0,    # 持仓亏损超10%强制清仓
    reset_threshold: int = 3,       # 价格偏离网格中心超3格间距时重置网格
) -> dict:
    """逐日模拟网格交易（含3个风控机制）

    风控机制：
    1. 最大持仓格数限制：最多同时持有 max_active_grids 格
    2. 强制止损：持仓总亏损超过 stop_loss_pct% 时清仓
    3. 网格重置：价格偏离网格中心超过 reset_threshold 格间距时重建网格
    """
    spacing_price = grid_params.spacing_price
    capital = grid_params.capital
    grid_count = grid_params.grid_count

    # 动态网格中心（会随价格重置）
    grid_center = float(df_bt["close"].iloc[0])

    def build_levels(center):
        """以 center 为中心构建网格"""
        lvls = []
        per_grid = capital / grid_count
        for i in range(grid_count):
            buy_price = round(center - spacing_price * (i + 1), 4)
            shares = max(100, int(per_grid / buy_price / 100) * 100)
            lvls.append({"buy_price": buy_price, "shares": shares})
        return lvls

    levels = build_levels(grid_center)

    # 持仓状态: {buy_price: {"shares": int, "buy_date": str}}
    holdings = {}
    trades = []
    equity_curve = []
    peak_equity = capital
    max_drawdown = 0.0
    total_realized = 0.0
    stop_loss_count = 0
    reset_count = 0

    for _, row in df_bt.iterrows():
        day_high = float(row["high"])
        day_low = float(row["low"])
        day_close = float(row["close"])
        day_date = str(row["date"])[:10]

        # === 1. 卖出：检查已持仓位 ===
        sell_targets = []
        for buy_price, info in list(holdings.items()):
            sell_price = round(buy_price + spacing_price, 4)
            if day_high >= sell_price:
                sell_targets.append((buy_price, sell_price, info))

        for buy_price, sell_price, info in sell_targets:
            shares = info["shares"]
            profit = round(shares * (sell_price - buy_price), 2)
            fee = round(shares * (buy_price + sell_price) * commission_rate, 2)
            net_profit = round(profit - fee, 2)
            total_realized += net_profit
            trades.append({
                "buy_date": info["buy_date"],
                "sell_date": day_date,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "shares": shares,
                "gross_profit": profit,
                "fee": fee,
                "net_profit": net_profit,
                "holding_days": (pd.Timestamp(day_date) - pd.Timestamp(info["buy_date"])).days,
                "type": "grid",
            })
            del holdings[buy_price]

        # === 2. 买入：限格 + 未持仓 ===
        active_count = len(holdings)
        for lv in levels:
            buy_price = lv["buy_price"]
            if buy_price not in holdings and day_low <= buy_price:
                if active_count >= max_active_grids:
                    break  # 超过最大持仓格数，跳过
                shares = lv["shares"]
                fee = round(shares * buy_price * commission_rate, 2)
                holdings[buy_price] = {
                    "shares": shares,
                    "buy_date": day_date,
                    "buy_fee": fee,
                }
                active_count += 1

        # === 3. 强制止损 ===
        if holdings:
            unrealized = sum(
                info["shares"] * (day_close - bp)
                for bp, info in holdings.items()
            )
            cost_basis = sum(
                info["shares"] * bp
                for bp, info in holdings.items()
            )
            if cost_basis > 0:
                loss_pct = abs(unrealized) / cost_basis * 100 if unrealized < 0 else 0
                if loss_pct >= stop_loss_pct:
                    # 强制清仓
                    for bp, info in list(holdings.items()):
                        shares = info["shares"]
                        loss = round(shares * (day_close - bp), 2)
                        fee = round(shares * (bp + day_close) * commission_rate, 2)
                        total_realized += round(loss - fee, 2)
                        trades.append({
                            "buy_date": info["buy_date"],
                            "sell_date": day_date,
                            "buy_price": bp,
                            "sell_price": round(day_close, 4),
                            "shares": shares,
                            "gross_profit": loss,
                            "fee": fee,
                            "net_profit": round(loss - fee, 2),
                            "holding_days": (pd.Timestamp(day_date) - pd.Timestamp(info["buy_date"])).days,
                            "type": "stop_loss",
                        })
                    holdings.clear()
                    stop_loss_count += 1

        # === 4. 网格重置检测 ===
        if spacing_price > 0:
            deviation = abs(day_close - grid_center) / spacing_price
            if deviation > reset_threshold:
                grid_center = day_close
                levels = build_levels(grid_center)
                reset_count += 1

        # === 计算当日权益 ===
        unrealized = sum(
            info["shares"] * (day_close - bp)
            for bp, info in holdings.items()
        )
        equity = capital + total_realized + unrealized
        equity_curve.append({"date": day_date, "equity": round(equity, 2)})

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

    # 统计
    grid_trades = [t for t in trades if t.get("type") == "grid"]
    stop_loss_trades = [t for t in trades if t.get("type") == "stop_loss"]
    winning = [t for t in grid_trades if t["net_profit"] > 0]
    total_profit = sum(t["net_profit"] for t in trades)
    grid_profit = sum(t["net_profit"] for t in grid_trades)
    sl_profit = sum(t["net_profit"] for t in stop_loss_trades)
    total_fees = sum(t["fee"] for t in trades)

    # 期末未实现盈亏
    last_close = float(df_bt["close"].iloc[-1])
    unrealized_eod = 0.0
    for buy_price, info in holdings.items():
        unrealized_eod += info["shares"] * (last_close - buy_price)
    unrealized_eod = round(unrealized_eod, 2)

    # 包含未实现盈亏的总盈亏
    total_pnl = round(total_profit + unrealized_eod, 2)

    return {
        "total_profit": round(total_profit, 2),
        "grid_profit": round(grid_profit, 2),
        "sl_profit": round(sl_profit, 2),
        "unrealized_pnl": unrealized_eod,
        "total_pnl": total_pnl,
        "total_fees": round(total_fees, 2),
        "total_trades": len(grid_trades),
        "stop_loss_trades": len(stop_loss_trades),
        "stop_loss_count": stop_loss_count,
        "reset_count": reset_count,
        "winning_trades": len(winning),
        "win_rate": round(len(winning) / len(grid_trades) * 100, 1) if grid_trades else 0,
        "avg_profit_per_trade": round(grid_profit / len(grid_trades), 2) if grid_trades else 0,
        "max_drawdown_pct": round(max_drawdown, 2),
        "max_drawdown_amount": round(peak_equity * max_drawdown / 100, 2),
        "final_equity": round(equity_curve[-1]["equity"], 2) if equity_curve else capital,
        "return_pct": round(total_pnl / capital * 100, 2),
        "open_positions": len(holdings),
        "trades": trades,
        "equity_curve": equity_curve,
    }


def _backtest_single_etf(code, name, df_full, df_bt, capital, grid_count_override=None):
    """对单只ETF执行回测，返回结果dict"""
    from analysis.grid_backtest import get_optimal_params

    start_price = float(df_bt["close"].iloc[0])
    avg_amp = float(df_full["amplitude"].mean())

    # 趋势评估（基于历史数据）
    split_idx = len(df_full) - len(df_bt)
    df_history = df_full.iloc[:split_idx].copy() if split_idx >= 30 else df_full.iloc[:30].copy()
    ta = TrendAssessment(code, name, df_history)
    trend = ta.assess()

    grid = calculate_grid(
        code, name, start_price, avg_amp, trend,
        capital=capital,
        etf_df=df_full,
    )

    bt_result = _simulate_grid(df_bt, grid)

    bt_result["code"] = code
    bt_result["name"] = name
    bt_result["start_price"] = round(start_price, 3)
    bt_result["end_price"] = round(float(df_bt["close"].iloc[-1]), 3)
    bt_result["price_change_pct"] = round(
        (bt_result["end_price"] - start_price) / start_price * 100, 2
    )
    bt_result["hold_pnl"] = round(capital * bt_result["price_change_pct"] / 100, 2)
    bt_result["spacing_pct"] = grid.spacing_pct
    bt_result["grid_count"] = grid.grid_count
    bt_result["capital"] = capital
    bt_result["bt_start"] = str(df_bt["date"].iloc[0])[:10]
    bt_result["bt_end"] = str(df_bt["date"].iloc[-1])[:10]
    bt_result["signal_strength"] = trend.get("signal_strength", "中性")
    bt_result["oversold_score"] = trend.get("oversold_score", 0)
    return bt_result


def run_backtest(days: int = 30) -> list:
    """对所有自选股执行网格策略回测"""
    results = []
    capital_per_etf = CAPITAL_PER_ETF

    for etf_cfg in WATCHLIST:
        code = etf_cfg["code"]
        name = etf_cfg["name"]
        log.info(f"回测 {code} {name}...")

        try:
            df_full = fetch_etf_daily(code, days=180)
            if df_full is None or len(df_full) < 60:
                log.warning(f"  {code} 数据不足，跳过")
                continue

            split_idx = len(df_full) - days
            if split_idx < 30:
                split_idx = 30
            df_bt = df_full.iloc[split_idx:].copy().reset_index(drop=True)

            if len(df_bt) < 5:
                log.warning(f"  {code} 回测期数据不足，跳过")
                continue

            bt_result = _backtest_single_etf(code, name, df_full, df_bt, capital_per_etf)
            results.append(bt_result)
            log.info(
                f"  {code}: {bt_result['total_trades']}笔, "
                f"已实现={bt_result['total_profit']:+.2f}, "
                f"未实现={bt_result['unrealized_pnl']:+.2f}, "
                f"胜率={bt_result['win_rate']}%, "
                f"回撤={bt_result['max_drawdown_pct']}%"
            )

        except Exception as e:
            log.error(f"  {code} 回测失败: {e}")

    return results


def _calc_dynamic_allocation(code, df_bt, total_budget):
    """根据近一周涨跌幅计算动态资金分配

    涨幅过大(>5%): 分配系数 0.6（减仓）
    涨幅偏大(3~5%): 分配系数 0.8
    正常(-3%~3%): 分配系数 1.0
    下跌(<-3%): 分配系数 1.1（加仓抄底）
    """
    if df_bt is None or len(df_bt) < 5:
        return total_budget

    # 用回测期前5天的涨跌幅作为"近一周"参考
    start = float(df_bt["close"].iloc[0])
    # 取回测期第1天 vs 第5天（近一周）
    end_idx = min(5, len(df_bt) - 1)
    week_price = float(df_bt["close"].iloc[end_idx])
    week_change = (week_price - start) / start * 100

    if week_change > 5:
        factor = 0.6
    elif week_change > 3:
        factor = 0.8
    elif week_change < -3:
        factor = 1.1
    else:
        factor = 1.0

    allocation = round(total_budget * factor, 0)
    log.info(f"  {code} 近一周{week_change:+.2f}%, 分配系数{factor}, 资金={allocation}")
    return allocation


def _enrich_indicators(df):
    """为指标DataFrame添加每日评分所需的辅助列（向量化操作）"""
    # 1. 每日oversold_score (0-10)
    score = pd.Series(0, index=df.index)
    if "K" in df.columns:
        score = score + np.where(df["K"] < 20, 3, np.where(df["K"] < 30, 1, 0))
    if "RSI6" in df.columns:
        score = score + np.where(df["RSI6"] < 30, 2, np.where(df["RSI6"] < 40, 1, 0))
    if "BOLL_LOW" in df.columns:
        score = score + np.where(df["close"] <= df["BOLL_LOW"] * 1.01, 2, 0)
    if "MACD_H" in df.columns:
        macd_cross = (df["MACD_H"] > 0) & (df["MACD_H"].shift(1) <= 0)
        score = score + np.where(macd_cross, 2, 0)
    if "volume" in df.columns:
        vol_20 = df["volume"].rolling(20, min_periods=1).mean()
        is_surge = df["volume"] > vol_20 * 2
        score = score + np.where(is_surge, 1, 0)
    df["_oversold_score"] = score.clip(upper=10)

    # 2. vol_ratio (5日均量/20日均量)
    if "volume" in df.columns:
        vol_5 = df["volume"].rolling(5, min_periods=1).mean()
        vol_20 = df["volume"].rolling(20, min_periods=1).mean()
        df["_vol_ratio"] = (vol_5 / vol_20.replace(0, np.nan)).fillna(1.0)
    else:
        df["_vol_ratio"] = 1.0

    # 3. is_prolonged_downtrend (连续低于MA20超20天)
    if "MA20" in df.columns:
        below_ma20 = df["close"] < df["MA20"]
        # 计算每个位置之前连续below_ma20的天数
        groups = (~below_ma20).cumsum()
        consecutive = below_ma20.groupby(groups).cumsum()
        df["_prolonged_dt"] = consecutive > 20
        df["_down_days"] = consecutive
    else:
        df["_prolonged_dt"] = False
        df["_down_days"] = 0

    # 4. bullish_count (6个信号中看多个数)
    cnt = pd.Series(0, index=df.index)
    if "MA5" in df.columns and "MA10" in df.columns and "MA20" in df.columns:
        above = (df["close"] > df["MA5"]).astype(int) + (df["close"] > df["MA10"]).astype(int) + (df["close"] > df["MA20"]).astype(int)
        cnt = cnt + np.where(above >= 2, 1, 0)
    if "DIF" in df.columns and "DEA" in df.columns:
        cnt = cnt + np.where(df["DIF"] > df["DEA"], 1, 0)
    if "K" in df.columns:
        cnt = cnt + np.where(df["K"] < 20, 1, 0)
    if "RSI6" in df.columns:
        cnt = cnt + np.where(df["RSI6"] < 30, 1, 0)
    if "BOLL_LOW" in df.columns:
        cnt = cnt + np.where(df["close"] <= df["BOLL_LOW"] * 1.02, 1, 0)
    if "volume" in df.columns:
        cnt = cnt + np.where(df["volume"] > df["volume"].rolling(20, min_periods=1).mean() * 2, 1, 0)
    df["_bullish_cnt"] = cnt

    # 5b. 超卖连续天数（_oversold_score >= 3 的连续天数）
    is_os = df["_oversold_score"] >= 3
    groups = (~is_os).cumsum()
    df["_oversold_streak"] = is_os.groupby(groups).cumsum().astype(float)

    # 5. 趋势代理列（近5/60/120日涨跌%）
    if "MA20" in df.columns:
        ma20 = df["MA20"].replace(0, np.nan)
        df["_trend_proxy_5"] = ((df["close"] - df["close"].shift(5)) / df["close"].shift(5) * 100).fillna(0)
        df["_trend_proxy_60"] = ((df["close"] - df["close"].shift(60)) / df["close"].shift(60) * 100).fillna(0)
        df["_trend_proxy_120"] = ((df["close"] - df["close"].shift(120)) / df["close"].shift(120) * 100).fillna(0)
    else:
        df["_trend_proxy_5"] = 0.0
        df["_trend_proxy_60"] = 0.0
        df["_trend_proxy_120"] = 0.0

    return df


def run_backtest_daily_top2(days: int = 30) -> dict:
    """每日动态Top-2回测：每天重新评估所有ETF，只对当天最推荐的2只执行网格买入

    核心逻辑：
    1. 每天对所有ETF评分（超卖+趋势+网格推荐信号）
    2. 选当天Top-2，只对Top-2执行网格新买入
    3. 非Top-2 ETF：已持有仓位可触发卖出，但不开新仓
    4. 共用资金池18000元，买入扣钱、卖出回钱
    """
    from analysis.technical import compute_all_indicators

    log.info("=== 每日动态Top-2回测 ===")

    # 加载所有ETF数据
    etf_daily = {}
    for etf_cfg in WATCHLIST:
        code = etf_cfg["code"]
        name = etf_cfg["name"]
        try:
            df_full = fetch_etf_daily(code, days=180)
            if df_full is not None and len(df_full) >= 60:
                split_idx = max(0, len(df_full) - days - 30)
                etf_daily[code] = {
                    "name": name,
                    "df_full": df_full,
                    "df_history": df_full.iloc[:max(split_idx, 30)].copy(),
                    "avg_amp": float(df_full["amplitude"].mean()),
                }
        except Exception:
            pass

    if len(etf_daily) < 2:
        log.warning("数据不足，回退全ETF模式")
        return {"results": run_backtest(days), "mode": "all_fallback"}

    # 找回测期范围
    first_code = list(etf_daily.keys())[0]
    df0 = etf_daily[first_code]["df_full"]
    bt_start_idx = max(30, len(df0) - days)
    bt_dates_all = df0.iloc[bt_start_idx:]["date"].reset_index(drop=True)
    n_days = len(bt_dates_all)
    log.info(f"  回测期: {n_days}天, {str(bt_dates_all.iloc[0])[:10]} ~ {str(bt_dates_all.iloc[-1])[:10]}")
    log.info(f"  参与评估ETF: {len(etf_daily)}只")

    # 预计算所有ETF的技术指标 + 评分辅助列
    log.info("  预计算技术指标...")
    indicators_cache = {}
    for code, info in etf_daily.items():
        try:
            df = compute_all_indicators(info["df_full"].copy())
            df = _enrich_indicators(df)
            indicators_cache[code] = df
        except Exception:
            pass

    def _score_etf(code, day_idx):
        """基于预计算指标评分（利用_enrich_indicators添加的列）

        核心思路：网格交易需要价格在区间内震荡，而非单边下跌。
        因此优先选趋势稳定/超卖反弹的ETF，坚决回避持续下跌的"飞刀"。
        """
        if code not in indicators_cache:
            return -999, {}
        df = indicators_cache[code]
        actual_idx = len(df) - (n_days - day_idx)
        if actual_idx < 60:
            return -999, {}

        row = df.iloc[actual_idx]
        close = float(row["close"])

        # 从enriched列读取预计算值
        oversold = int(row.get("_oversold_score", 0))
        vol_ratio = float(row.get("_vol_ratio", 1.0))
        is_prolonged = bool(row.get("_prolonged_dt", False))
        bullish_cnt = int(row.get("_bullish_cnt", 0))
        downtrend_days = int(row.get("_down_days", 0))

        # 超卖持续衰减：连续超卖>3天，每天衰减20%
        oversold_streak = int(row.get("_oversold_streak", 0))
        if oversold_streak > 3:
            oversold_decay = 0.8 ** (oversold_streak - 3)
        else:
            oversold_decay = 1.0

        # 趋势判断（相对MA20的位置%）
        ma20_val = float(row.get("MA20", close))
        ma_pos_pct = round((close - ma20_val) / ma20_val * 100, 2) if ma20_val > 0 else 0

        # MACD金叉检测
        macd_h = float(row.get("MACD_H", 0))
        prev_macd_h = float(df.iloc[actual_idx - 1].get("MACD_H", 0)) if actual_idx > 0 else 0
        macd_cross_up = macd_h > 0 and prev_macd_h <= 0

        # RSI回升检测
        rsi = float(row.get("RSI6", 50))
        prev_rsi = float(df.iloc[actual_idx - 1].get("RSI6", 50)) if actual_idx > 0 else 50
        rsi_turning_up = rsi > prev_rsi and prev_rsi < 35

        # 4周期趋势
        trend_3m_pct = float(row.get("_trend_proxy_60", ma_pos_pct))
        trend_6m_pct = float(row.get("_trend_proxy_120", ma_pos_pct))
        trend_1w_pct = float(row.get("_trend_proxy_5", ma_pos_pct))
        trend_1m_pct = ma_pos_pct

        has_recovery = macd_cross_up or rsi_turning_up

        # === 评分 ===
        score = 0.0

        # 1. 稳定区间奖励（网格最佳场景：价格在MA20附近震荡）
        if -2 <= trend_1m_pct <= 3:
            score += 5  # 大幅提高：稳定震荡才是网格的甜区
        elif -4 <= trend_1m_pct <= 5:
            score += 2  # 轻微偏离也给一定分

        # 2. 超卖信号（三重打折：趋势深度×衰减×系数）
        if oversold > 0:
            if trend_1m_pct < -5:
                oversold_eff = oversold * 0.2  # 深跌中超卖几乎无效
            elif trend_1m_pct < -3:
                oversold_eff = oversold * 0.4
            elif trend_1m_pct < -1:
                oversold_eff = oversold * 0.7
            else:
                oversold_eff = oversold * 1.0
            # 持续超卖衰减：连续>3天后每天×0.8
            oversold_eff *= oversold_decay
            score += oversold_eff * 1.0

        # 3. 多指标共振
        if bullish_cnt >= 4:
            score += 4
        elif bullish_cnt >= 3:
            score += 2
        elif bullish_cnt >= 2:
            score += 1

        # 4. 放量确认
        if vol_ratio > 1.5 and trend_1m_pct > -3:
            score += 2
        elif vol_ratio > 1.2 and trend_1m_pct > -3:
            score += 1

        # 5. 布林下轨（仅在非深跌时加分）
        boll_low = float(row.get("BOLL_LOW", 0))
        if boll_low > 0 and close <= boll_low * 1.02 and trend_1m_pct > -3:
            score += 2

        # 6. 真实反弹信号加分（MACD金叉 + RSI从超卖区回升），同样受衰减影响
        if has_recovery and oversold >= 3:
            score += 4 * oversold_decay  # 持续超卖中的反弹信号可信度降低

        # === 风控惩罚 ===

        # 7. 持续下跌惩罚（核心防飞刀，按天数递增）
        if is_prolonged:
            penalty = -8  # 基础惩罚加强
            if downtrend_days > 40:
                penalty -= 8  # 两个月以上的下跌
            elif downtrend_days > 30:
                penalty -= 4
            score += penalty

        # 8. 深跌无反弹（最危险的"接飞刀"场景）
        if trend_1m_pct < -5 and not has_recovery:
            score -= 8  # 从-5加强到-8
        elif trend_1m_pct < -3 and not has_recovery:
            score -= 4  # 从-2加强到-4

        # 9. 4周期全跌
        all_down = (trend_6m_pct < 0 and trend_3m_pct < 0 and
                    trend_1m_pct < 0 and trend_1w_pct < 0)
        if all_down:
            score -= 5  # 从-3加强到-5

        # 10. 远离MA20（偏离过大不利于网格）
        if abs(trend_1m_pct) > 6:
            score -= 3  # 距MA20超过6%不利于网格

        oversold_decayed = round(oversold * oversold_decay, 1)
        grid_rec = "aggressive" if oversold_decayed >= 5 else ("conservative" if trend_1m_pct > 3 else "normal")

        return score, {
            "oversold": oversold,
            "oversold_decay": round(oversold_decay, 2),
            "oversold_streak": oversold_streak,
            "grid_rec": grid_rec,
            "rsi": round(rsi, 1),
            "trend_1m_pct": trend_1m_pct,
            "bullish_cnt": bullish_cnt,
        }

    # 网格交易状态
    _TOTAL_BT_CAPITAL = CAPITAL_PER_ETF * 2  # 回测总资金（按2只ETF）
    funds = float(_TOTAL_BT_CAPITAL)
    holdings = {}  # {code: {grid_center, spacing_price, positions: {buy_price: {shares, buy_date, buy_fee}}, levels}}
    trades = []
    realized = 0.0
    equity_curve = []
    daily_picks = []

    for d in range(n_days):
        day_date = str(bt_dates_all.iloc[d])[:10]

        # === 1. 每天评分所有ETF，选Top-2 ===
        scores = []
        for code in etf_daily:
            s, info = _score_etf(code, d)
            scores.append({"code": code, "name": etf_daily[code]["name"], "score": s, "info": info})

        # 连续确认：非昨日Top-3的ETF扣1分（轻度确认，避免信号抖动但不锁死选择）
        if d > 0 and daily_picks:
            yesterday_top3 = set(c for c, _, _ in daily_picks[-1].get("top3", []))
            if yesterday_top3:
                for s in scores:
                    if s["code"] not in yesterday_top3:
                        s["score"] -= 1

        scores.sort(key=lambda x: x["score"], reverse=True)
        top2_codes = set(s["code"] for s in scores[:2])
        daily_picks.append({
            "date": day_date,
            "top2": [(s["code"], s["name"], round(s["score"], 2)) for s in scores[:2]],
            "top3": [(s["code"], s["name"], round(s["score"], 2)) for s in scores[:3]],
            "all": [(s["code"], s["name"], round(s["score"], 2), s["info"]) for s in scores],
        })

        # === 2. 获取当日价格（所有有持仓或Top-2的ETF）===
        day_prices = {}
        active_codes = top2_codes | set(holdings.keys())
        for code in active_codes:
            if code not in etf_daily:
                continue
            df = etf_daily[code]["df_full"]
            actual_idx = len(df) - (n_days - d)
            if actual_idx < 0 or actual_idx >= len(df):
                continue
            row = df.iloc[actual_idx]
            day_prices[code] = {
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }

        # === 3. 卖出检查（所有有持仓的ETF都检查）===
        for code in list(holdings.keys()):
            if code not in day_prices:
                continue
            st = holdings[code]
            prices = day_prices[code]
            sold_keys = []
            for bp, pos in list(st["positions"].items()):
                sell_price = round(bp + st["spacing_price"], 4)
                if prices["high"] >= sell_price:
                    shares = pos["shares"]
                    profit = round(shares * (sell_price - bp), 2)
                    fee = round(shares * (bp + sell_price) * COMMISSION_RATE, 2)
                    net = round(profit - fee, 2)
                    realized += net
                    funds += round(shares * sell_price - fee, 2)
                    trades.append({
                        "buy_date": pos["buy_date"], "sell_date": day_date,
                        "buy_price": round(bp, 3), "sell_price": round(sell_price, 3),
                        "shares": shares, "net_profit": net, "fee": fee,
                        "holding_days": (pd.Timestamp(day_date) - pd.Timestamp(pos["buy_date"])).days,
                        "type": "grid", "code": code, "name": etf_daily[code]["name"],
                    })
                    sold_keys.append(bp)
            for k in sold_keys:
                del st["positions"][k]

        # === 4. 买入检查（仅Top-2）===
        for code in top2_codes:
            if code not in day_prices:
                continue
            prices = day_prices[code]

            # 确保网格状态存在
            if code not in holdings:
                avg_amp = etf_daily[code]["avg_amp"]
                grid_params = calculate_grid(
                    code, etf_daily[code]["name"], prices["close"], avg_amp,
                    {"oversold_score": 0, "grid_recommendation": "normal"},
                    capital=CAPITAL_PER_ETF,
                    etf_df=etf_daily[code]["df_full"],
                )
                holdings[code] = {
                    "grid_center": prices["close"],
                    "spacing_price": grid_params.spacing_price,
                    "spacing_pct": grid_params.spacing_pct,
                    "grid_count": grid_params.grid_count,
                    "per_grid": grid_params.capital / grid_params.grid_count,
                    "positions": {},
                }

            st = holdings[code]
            per_grid = st["per_grid"]

            # 网格重置：偏离超3格
            if st["spacing_price"] > 0:
                dev = abs(prices["close"] - st["grid_center"]) / st["spacing_price"]
                if dev > 3:
                    st["grid_center"] = prices["close"]
                    st["positions"].clear()

            # 构建网格档位并检查买入
            for i in range(st["grid_count"]):
                buy_price = round(st["grid_center"] - st["spacing_price"] * (i + 1), 4)
                if buy_price <= 0:
                    continue
                if buy_price in st["positions"]:
                    continue
                if prices["low"] <= buy_price:
                    shares = max(100, int(per_grid / buy_price / 100) * 100)
                    cost = round(shares * buy_price, 2)
                    fee = round(shares * buy_price * COMMISSION_RATE, 2)
                    total_need = cost + fee
                    if funds < total_need:
                        if funds < 1000:
                            break
                        shares = max(100, int((funds - 50) / buy_price / 100) * 100)
                        cost = round(shares * buy_price, 2)
                        fee = round(shares * buy_price * COMMISSION_RATE, 2)
                        total_need = cost + fee
                        if shares < 100 or funds < total_need:
                            break
                    funds -= total_need
                    st["positions"][buy_price] = {
                        "shares": shares,
                        "buy_date": day_date,
                        "buy_fee": fee,
                    }

        # === 5. 当日权益（现金 + 持仓市值）===
        equity = funds
        for code, st in holdings.items():
            if code in day_prices:
                close_p = day_prices[code]["close"]
                for bp, pos in st["positions"].items():
                    equity += pos["shares"] * close_p

        equity_curve.append({"date": day_date, "equity": round(equity, 2)})

    # 期末未实现
    unrealized_eod = 0.0
    for code, st in holdings.items():
        if code in etf_daily:
            df = etf_daily[code]["df_full"]
            last_close = float(df["close"].iloc[-1])
            for bp, pos in st["positions"].items():
                unrealized_eod += pos["shares"] * (last_close - bp)
    unrealized_eod = round(unrealized_eod, 2)

    total_pnl = round(realized + unrealized_eod, 2)
    total_fees = sum(t["fee"] for t in trades)

    # 最大回撤
    max_dd = 0.0
    peak = 0
    for e in equity_curve:
        if e["equity"] > peak:
            peak = e["equity"]
        dd = (peak - e["equity"]) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    winning = [t for t in trades if t["net_profit"] > 0]

    # Top-2选择统计
    pick_counts = {}
    for dp in daily_picks:
        for code, name, score in dp["top2"]:
            pick_counts.setdefault(code, {"name": name, "days": 0, "total_score": 0})
            pick_counts[code]["days"] += 1
            pick_counts[code]["total_score"] += score

    result = {
        "total_profit": round(realized, 2),
        "unrealized_pnl": unrealized_eod,
        "total_pnl": total_pnl,
        "total_fees": round(total_fees, 2),
        "total_trades": len(trades),
        "winning_trades": len(winning),
        "win_rate": round(len(winning) / len(trades) * 100, 1) if trades else 0,
        "avg_profit_per_trade": round(realized / len(trades), 2) if trades else 0,
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_amount": round(peak * max_dd / 100, 2) if peak else 0,
        "final_equity": round(equity_curve[-1]["equity"], 2) if equity_curve else _TOTAL_BT_CAPITAL,
        "return_pct": round(total_pnl / _TOTAL_BT_CAPITAL * 100, 2),
        "capital": _TOTAL_BT_CAPITAL,
        "equity_curve": equity_curve,
        "trades": trades,
        "daily_picks": daily_picks,
        "pick_counts": pick_counts,
        "bt_start": str(bt_dates_all.iloc[0])[:10],
        "bt_end": str(bt_dates_all.iloc[-1])[:10],
        "n_days": n_days,
    }

    log.info(f"  总盈亏: {total_pnl:+.2f} (已实现{realized:+.2f} + 未实现{unrealized_eod:+.2f})")
    log.info(f"  交易: {len(trades)}笔, 胜率{result['win_rate']}%, 最大回撤{max_dd:.2f}%")
    log.info(f"  Top-2选择频率:")
    for code, info in sorted(pick_counts.items(), key=lambda x: x[1]["days"], reverse=True):
        log.info(f"    {code} {info['name']}: 被选{info['days']}/{n_days}天")

    return result


def generate_daily_top2_html(result: dict) -> str:
    """生成每日Top-2回测报告HTML"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    equity_curve = result.get("equity_curve", [])
    trades = result.get("trades", [])
    daily_picks = result.get("daily_picks", [])
    pick_counts = result.get("pick_counts", {})

    total_pnl = result["total_pnl"]
    profit_color = "#EF4444" if total_pnl >= 0 else "#22C55E"

    # 每日选择日志表格
    pick_rows = ""
    for dp in daily_picks:
        top2_str = " | ".join(f"{n}({s:+.1f})" for _, n, s in dp["top2"])
        # 找当天的买卖记录
        day_buys = [t for t in trades if t["buy_date"] == dp["date"] and t.get("type") == "grid"]
        day_sells = [t for t in trades if t["sell_date"] == dp["date"]]
        action_parts = []
        for t in day_sells:
            pnl_sign = "+" if t["net_profit"] >= 0 else ""
            action_parts.append(f"卖出{t['code']}({pnl_sign}{t['net_profit']:.0f})")
        for t in day_buys:
            action_parts.append(f"买入{t['code']}")
        action_str = " / ".join(action_parts) if action_parts else "-"
        pick_rows += f"<tr><td>{dp['date'][:10]}</td><td>{top2_str}</td><td>{action_str}</td></tr>\n"

    # 选择频率统计
    freq_items = []
    for code, info in sorted(pick_counts.items(), key=lambda x: x[1]["days"], reverse=True):
        pct = round(info["days"] / result["n_days"] * 100, 1)
        freq_items.append(f'<span class="freq-tag">{code} {info["name"]}: {info["days"]}天({pct}%)</span>')
    freq_html = " ".join(freq_items)

    # 交易明细
    trade_rows = ""
    for t in trades[-30:]:
        t_color = "#EF4444" if t["net_profit"] >= 0 else "#22C55E"
        trade_rows += f"""<tr>
            <td>{t.get('code','')}</td><td>{t['buy_date']}</td><td>{t['sell_date']}</td>
            <td>{t['buy_price']:.3f}</td><td>{t['sell_price']:.3f}</td>
            <td>{t['shares']}</td>
            <td style="color:{t_color};font-weight:600;">{t['net_profit']:+.2f}</td>
            <td>{t['holding_days']}天</td>
        </tr>"""

    # 权益曲线
    eq_dates = [e["date"] for e in equity_curve]
    eq_values = [e["equity"] for e in equity_curve]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日Top-2动态回测报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#0F172A;color:#E2E8F0;font-family:-apple-system,'Segoe UI',sans-serif;padding:16px;}}
.container{{max-width:960px;margin:0 auto;}}
h1{{font-size:20px;margin-bottom:4px;color:#F0F4F8;}}
h2{{font-size:16px;margin:20px 0 10px;color:#CBD5E1;}}
.subtitle{{color:#64748B;font-size:13px;margin-bottom:20px;}}
.summary{{background:linear-gradient(135deg,#0F172A,#1E293B);border:1px solid rgba(255,255,255,0.08);
    border-radius:12px;padding:20px;margin-bottom:20px;display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:16px;}}
.summary-item{{text-align:center;}}
.summary-value{{font-size:22px;font-weight:700;}}
.summary-label{{font-size:12px;color:#64748B;margin-top:4px;}}
.chart-container{{height:260px;margin:20px 0;}}
.freq-tag{{display:inline-block;background:rgba(59,130,246,0.15);color:#93C5FD;
    padding:4px 10px;border-radius:6px;font-size:12px;margin:3px;}}
.pick-table,.trade-table{{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px;}}
.pick-table th,.pick-table td,.trade-table th,.trade-table td{{padding:6px 8px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.06);}}
.pick-table th,.trade-table th{{color:#94A3B8;font-weight:600;}}
.pick-table tr:nth-child(even){{background:rgba(255,255,255,0.02);}}
details{{margin-top:12px;}}
summary{{cursor:pointer;color:#3B82F6;font-size:13px;padding:6px 0;}}
.footer{{text-align:center;color:#475569;font-size:11px;margin-top:20px;padding:12px;}}
</style>
</head>
<body>
<div class="container">
    <h1>每日Top-2动态回测报告</h1>
    <p class="subtitle">每天重新评估11只ETF，只对当天最推荐的2只执行网格买入 | {result['bt_start']} ~ {result['bt_end']} ({result['n_days']}天) | {now}</p>

    <div class="summary">
        <div class="summary-item">
            <div class="summary-value" style="color:{profit_color};">{total_pnl:+.2f}</div>
            <div class="summary-label">总盈亏(元)</div>
        </div>
        <div class="summary-item">
            <div class="summary-value" style="color:{'#EF4444' if result['total_profit']>=0 else '#22C55E'};">{result['total_profit']:+.2f}</div>
            <div class="summary-label">已实现利润</div>
        </div>
        <div class="summary-item">
            <div class="summary-value" style="color:{'#EF4444' if result['unrealized_pnl']>=0 else '#22C55E'};">{result['unrealized_pnl']:+.2f}</div>
            <div class="summary-label">未实现盈亏</div>
        </div>
        <div class="summary-item">
            <div class="summary-value" style="color:{profit_color};">{result['return_pct']:+.2f}%</div>
            <div class="summary-label">总收益率</div>
        </div>
        <div class="summary-item">
            <div class="summary-value">{result['total_trades']}</div>
            <div class="summary-label">总交易笔数</div>
        </div>
        <div class="summary-item">
            <div class="summary-value">{result['win_rate']}%</div>
            <div class="summary-label">整体胜率</div>
        </div>
        <div class="summary-item">
            <div class="summary-value" style="color:#EAB308;">{result['max_drawdown_pct']:.2f}%</div>
            <div class="summary-label">最大回撤</div>
        </div>
        <div class="summary-item">
            <div class="summary-value">{result['total_fees']:.2f}</div>
            <div class="summary-label">总手续费</div>
        </div>
    </div>

    <h2>ETF被选频率</h2>
    <div style="margin-bottom:16px;">{freq_html}</div>

    <div class="chart-container"><canvas id="equityChart"></canvas></div>

    <h2>每日Top-2选择日志</h2>
    <table class="pick-table">
        <thead><tr><th>日期</th><th>Top-2 (评分)</th><th>当日操作</th></tr></thead>
        <tbody>{pick_rows}</tbody>
    </table>

    <details>
        <summary>交易明细 ({result['total_trades']}笔)</summary>
        <table class="trade-table">
            <thead><tr><th>ETF</th><th>买入日</th><th>卖出日</th><th>买入价</th><th>卖出价</th><th>股数</th><th>净利润</th><th>持仓天数</th></tr></thead>
            <tbody>{trade_rows}</tbody>
        </table>
    </details>

    <div class="footer">数据仅供参考，不构成投资建议 | 每日动态Top-2网格策略模拟</div>
</div>

<script>
new Chart(document.getElementById('equityChart'),{{
    type:'line',
    data:{{labels:{eq_dates},datasets:[{{label:'账户权益',
        data:{eq_values},borderColor:'#3B82F6',borderWidth:2,
        fill:true,backgroundColor:'rgba(59,130,246,0.1)',pointRadius:0,tension:0.3}},
        {{label:'初始资金',data:Array({len(eq_dates)}).fill({CAPITAL_PER_ETF * 2}),
        borderColor:'rgba(148,163,184,0.3)',borderWidth:1,borderDash:[5,5],pointRadius:0,fill:false}}
    ]}},
    options:{{responsive:true,maintainAspectRatio:false,
        plugins:{{legend:{{labels:{{color:'#94A3B8'}}}}}},
        scales:{{
            x:{{ticks:{{color:'#94A3B8',font:{{size:10}},maxTicksLimit:15}},grid:{{display:false}}}},
            y:{{ticks:{{color:'#94A3B8'}},grid:{{color:'rgba(148,163,184,0.1)'}}}}
        }}
    }}
}});
</script>
</body>
</html>"""
    return html


def generate_backtest_html(results: list, bt_days: int = 30) -> str:
    """生成回测报告HTML"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 汇总统计
    total_profit = sum(r["total_profit"] for r in results)
    total_unrealized = sum(r.get("unrealized_pnl", 0) for r in results)
    total_pnl = sum(r.get("total_pnl", r["total_profit"]) for r in results)
    total_trades = sum(r["total_trades"] for r in results)
    total_winning = sum(r["winning_trades"] for r in results)
    overall_win_rate = round(total_winning / total_trades * 100, 1) if total_trades else 0
    max_dd = max((r["max_drawdown_pct"] for r in results), default=0)
    avg_profit = round(total_profit / total_trades, 2) if total_trades else 0
    total_capital = sum(r["capital"] for r in results)
    overall_return = round(total_pnl / total_capital * 100, 2) if total_capital else 0

    # 满仓持有对比
    total_hold_pnl = sum(r.get("hold_pnl", 0) for r in results)
    hold_return = round(total_hold_pnl / total_capital * 100, 2) if total_capital else 0
    grid_advantage = round(total_pnl - total_hold_pnl, 2)

    # 按利润排序
    sorted_results = sorted(results, key=lambda r: r["total_profit"], reverse=True)

    # ETF详情卡片
    cards = []
    for r in sorted_results:
        profit_color = "#EF4444" if r.get("total_pnl", r["total_profit"]) >= 0 else "#22C55E"
        dd_color = "#EF4444" if r["max_drawdown_pct"] > 5 else "#EAB308" if r["max_drawdown_pct"] > 2 else "#22C55E"
        unrealized = r.get("unrealized_pnl", 0)
        total_pnl = r.get("total_pnl", r["total_profit"])

        # 交易明细表格
        trade_rows = ""
        for t in r.get("trades", )[-15:]:  # 最近15笔
            t_color = "#EF4444" if t["net_profit"] >= 0 else "#22C55E"
            t_type = "止损" if t.get("type") == "stop_loss" else ""
            t_type_html = f'<span style="color:#EAB308;font-size:11px;">{t_type}</span>' if t_type else ""
            trade_rows += f"""<tr>
                <td>{t['buy_date']}</td><td>{t['sell_date']}</td>
                <td>{t['buy_price']:.3f}</td><td>{t['sell_price']:.3f}</td>
                <td>{t['shares']}</td>
                <td style="color:{t_color};font-weight:600;">{t['net_profit']:+.2f} {t_type_html}</td>
                <td>{t['holding_days']}天</td>
            </tr>"""

        # 权益曲线数据
        eq_dates = [e["date"] for e in r.get("equity_curve", [])]
        eq_values = [e["equity"] for e in r.get("equity_curve", [])]

        cards.append(f"""
    <div class="etf-card">
        <div class="etf-header">
            <span class="etf-name">{r['code']} {r['name']}</span>
            <span class="etf-profit" style="color:{profit_color};">总盈亏 {total_pnl:+.2f} ({r['return_pct']:+.2f}%)</span>
        </div>
        <div class="etf-meta">
            回测期: {r['bt_start']} ~ {r['bt_end']} |
            价格: {r['start_price']} → {r['end_price']} ({r['price_change_pct']:+.2f}%) |
            间距: {r['spacing_pct']}% |
            信号: {r['signal_strength']} | 超卖: {r['oversold_score']}/10
        </div>
        <div class="etf-stats">
            <div class="stat">
                <div class="stat-value" style="color:{profit_color};">{r['total_profit']:+.2f}</div>
                <div class="stat-label">已实现</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color:{'#EF4444' if unrealized>=0 else '#22C55E'};">{unrealized:+.2f}</div>
                <div class="stat-label">未实现</div>
            </div>
            <div class="stat">
                <div class="stat-value">{r['total_trades']}</div>
                <div class="stat-label">网格交易</div>
            </div>
            <div class="stat">
                <div class="stat-value">{r['win_rate']}%</div>
                <div class="stat-label">胜率</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color:{profit_color};">{r['avg_profit_per_trade']:+.2f}</div>
                <div class="stat-label">平均利润</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color:{dd_color};">{r['max_drawdown_pct']}%</div>
                <div class="stat-label">最大回撤</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color:{'#EAB308' if r.get('stop_loss_count',0)>0 else '#94A3B8'};">{r.get('stop_loss_count',0)}</div>
                <div class="stat-label">止损次数</div>
            </div>
            <div class="stat">
                <div class="stat-value">{r.get('reset_count',0)}</div>
                <div class="stat-label">网格重置</div>
            </div>
        </div>
        <div class="chart-container">
            <canvas id="chart_{r['code']}" height="180"></canvas>
        </div>
        <details class="trade-details">
            <summary>交易明细 ({r['total_trades']}笔)</summary>
            <table class="trade-table">
                <thead><tr>
                    <th>买入日</th><th>卖出日</th><th>买入价</th><th>卖出价</th>
                    <th>股数</th><th>净利润</th><th>持仓天数</th>
                </tr></thead>
                <tbody>{trade_rows}</tbody>
            </table>
        </details>
    </div>""")

    # 汇总图表数据
    summary_labels = [r["code"] for r in sorted_results]
    summary_profits = [r.get("total_pnl", r["total_profit"]) for r in sorted_results]
    summary_dd = [r["max_drawdown_pct"] for r in sorted_results]

    # 生成每只ETF的权益曲线JS
    chart_js_list = []
    for r in sorted_results:
        eq_dates = [e["date"] for e in r.get("equity_curve", [])]
        eq_values = [e["equity"] for e in r.get("equity_curve", [])]
        chart_js_list.append(f"""new Chart(document.getElementById('chart_{r["code"]}'),{{
            type:'line',data:{{labels:{eq_dates},datasets:[{{label:'权益',
            data:{eq_values},borderColor:'#3B82F6',borderWidth:1.5,
            fill:true,backgroundColor:'rgba(59,130,246,0.1)',pointRadius:0,
            tension:0.3}}]}},
            options:{{responsive:true,maintainAspectRatio:false,
            plugins:{{legend:{{display:false}}}},
            scales:{{x:{{display:false}},y:{{ticks:{{color:'#94A3B8',font:{{size:10}}}},
            grid:{{color:'rgba(148,163,184,0.1)'}}}}}}}}}});""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>网格策略回测报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#0F172A;color:#E2E8F0;font-family:-apple-system,'Segoe UI',sans-serif;padding:16px;}}
.container{{max-width:960px;margin:0 auto;}}
h1{{font-size:20px;margin-bottom:4px;color:#F0F4F8;}}
.subtitle{{color:#64748B;font-size:13px;margin-bottom:20px;}}
.summary{{background:linear-gradient(135deg,#0F172A,#1E293B);border:1px solid rgba(255,255,255,0.08);
    border-radius:12px;padding:20px;margin-bottom:20px;display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:16px;}}
.summary-item{{text-align:center;}}
.summary-value{{font-size:22px;font-weight:700;}}
.summary-label{{font-size:12px;color:#64748B;margin-top:4px;}}
.etf-card{{background:rgba(255,255,255,0.04);border-radius:10px;padding:16px;margin-bottom:14px;}}
.etf-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:8px;}}
.etf-name{{font-weight:600;font-size:15px;color:#F0F4F8;}}
.etf-profit{{font-size:16px;font-weight:700;}}
.etf-meta{{font-size:12px;color:#64748B;margin-bottom:12px;line-height:1.6;}}
.etf-stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;}}
.stat{{text-align:center;background:rgba(255,255,255,0.03);border-radius:6px;padding:10px 4px;}}
.stat-value{{font-size:18px;font-weight:700;color:#F0F4F8;}}
.stat-label{{font-size:11px;color:#64748B;margin-top:2px;}}
.chart-container{{height:180px;margin-bottom:12px;}}
details{{margin-top:8px;}}
summary{{cursor:pointer;color:#3B82F6;font-size:13px;padding:6px 0;}}
.trade-table{{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px;}}
.trade-table th,.trade-table td{{padding:6px 8px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.06);}}
.trade-table th{{color:#94A3B8;font-weight:600;}}
.bar-chart{{height:260px;margin:20px 0;}}
.footer{{text-align:center;color:#475569;font-size:11px;margin-top:20px;padding:12px;}}
</style>
</head>
<body>
<div class="container">
    <h1>网格策略回测报告</h1>
    <p class="subtitle">回测周期: 最近{bt_days}个交易日 | 生成时间: {now}</p>

    <div class="summary">
        <div class="summary-item">
            <div class="summary-value" style="color:{'#EF4444' if total_pnl>=0 else '#22C55E'};">{total_pnl:+.2f}</div>
            <div class="summary-label">总盈亏(元)</div>
        </div>
        <div class="summary-item">
            <div class="summary-value" style="color:{'#EF4444' if total_profit>=0 else '#22C55E'};">{total_profit:+.2f}</div>
            <div class="summary-label">已实现利润</div>
        </div>
        <div class="summary-item">
            <div class="summary-value" style="color:{'#EF4444' if total_unrealized>=0 else '#22C55E'};">{total_unrealized:+.2f}</div>
            <div class="summary-label">未实现盈亏</div>
        </div>
        <div class="summary-item">
            <div class="summary-value">{overall_return:+.2f}%</div>
            <div class="summary-label">总收益率</div>
        </div>
        <div class="summary-item">
            <div class="summary-value">{total_trades}</div>
            <div class="summary-label">总交易笔数</div>
        </div>
        <div class="summary-item">
            <div class="summary-value">{overall_win_rate}%</div>
            <div class="summary-label">整体胜率</div>
        </div>
        <div class="summary-item">
            <div class="summary-value">{avg_profit:+.2f}</div>
            <div class="summary-label">平均利润/笔</div>
        </div>
        <div class="summary-item">
            <div class="summary-value" style="color:#EAB308;">{max_dd:.2f}%</div>
            <div class="summary-label">最大回撤</div>
        </div>
    </div>

    <div class="summary" style="border-left:3px solid {'#22C55E' if grid_advantage>=0 else '#EF4444'};">
        <div class="summary-item">
            <div class="summary-value" style="color:{'#22C55E' if grid_advantage>=0 else '#EF4444'};">{grid_advantage:+.2f}</div>
            <div class="summary-label">网格 vs 持有</div>
        </div>
        <div class="summary-item">
            <div class="summary-value">{total_hold_pnl:+.2f}</div>
            <div class="summary-label">满仓持有盈亏</div>
        </div>
        <div class="summary-item">
            <div class="summary-value">{hold_return:+.2f}%</div>
            <div class="summary-label">持有收益率</div>
        </div>
        <div class="summary-item">
            <div class="summary-value" style="color:{'#22C55E' if overall_return > hold_return else '#EF4444'};">{overall_return:+.2f}%</div>
            <div class="summary-label">网格收益率</div>
        </div>
    </div>

    <div class="bar-chart"><canvas id="summaryChart" height="260"></canvas></div>

    {''.join(cards)}

    <div class="footer">数据仅供参考，不构成投资建议 | 基于实际网格参数模拟</div>
</div>

<script>
new Chart(document.getElementById('summaryChart'),{{
    type:'bar',
    data:{{
        labels:{summary_labels},
        datasets:[
            {{label:'净利润(元)',data:{summary_profits},
              backgroundColor:{summary_profits}.map(v=>v>=0?'rgba(239,68,68,0.7)':'rgba(34,197,94,0.7)'),
              borderRadius:4,yAxisID:'y'}},
            {{label:'最大回撤(%)',data:{summary_dd},
              type:'line',borderColor:'#EAB308',backgroundColor:'rgba(234,179,8,0.1)',
              borderWidth:2,pointRadius:4,pointBackgroundColor:'#EAB308',yAxisID:'y1'}}
        ]
    }},
    options:{{
        responsive:true,maintainAspectRatio:false,
        plugins:{{legend:{{labels:{{color:'#94A3B8'}}}}}},
        scales:{{
            x:{{ticks:{{color:'#94A3B8',font:{{size:10}}}},grid:{{display:false}}}},
            y:{{position:'left',ticks:{{color:'#94A3B8'}},grid:{{color:'rgba(148,163,184,0.1)'}},title:{{display:true,text:'净利润(元)',color:'#94A3B8'}}}},
            y1:{{position:'right',ticks:{{color:'#EAB308'}},grid:{{display:false}},title:{{display:true,text:'回撤(%)',color:'#EAB308'}}}}
        }}
    }}
}});

{''.join(chart_js_list)}
</script>
</body>
</html>"""
    return html


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    out_dir = Path(__file__).parent.parent / "reports" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # === 模式1: 全ETF回测 ===
    print("=" * 50)
    print("模式1: 全ETF回测")
    print("=" * 50)
    results_all = run_backtest(days=30)

    if results_all:
        html_all = generate_backtest_html(results_all, bt_days=30)
        (out_dir / "backtest_all.html").write_text(html_all, encoding="utf-8")
        total_pnl_all = sum(r.get("total_pnl", r["total_profit"]) for r in results_all)
        total_capital_all = sum(r["capital"] for r in results_all)
        print(f"\n全ETF汇总: 总盈亏={total_pnl_all:+.2f}, 资金={total_capital_all}")
        for r in sorted(results_all, key=lambda x: x.get("total_pnl", x["total_profit"]), reverse=True):
            pnl = r.get("total_pnl", r["total_profit"])
            print(f"  {r['code']} {r['name']}: {pnl:+.2f} ({r['total_trades']}笔, 胜率{r['win_rate']}%, 回撤{r['max_drawdown_pct']}%)")

    # === 模式2: 每日动态Top-2回测 ===
    print("\n" + "=" * 50)
    print("模式2: 每日动态Top-2回测")
    print("=" * 50)
    daily_result = run_backtest_daily_top2(days=30)

    if daily_result:
        html_daily = generate_daily_top2_html(daily_result)
        (out_dir / "backtest_daily_top2.html").write_text(html_daily, encoding="utf-8")
        print(f"\n每日Top-2汇总:")
        print(f"  总盈亏: {daily_result['total_pnl']:+.2f} (已实现{daily_result['total_profit']:+.2f} + 未实现{daily_result['unrealized_pnl']:+.2f})")
        print(f"  收益率: {daily_result['return_pct']:+.2f}%")
        print(f"  交易: {daily_result['total_trades']}笔, 胜率{daily_result['win_rate']}%, 回撤{daily_result['max_drawdown_pct']}%")
        print(f"  被选频率:")
        for code, info in sorted(daily_result["pick_counts"].items(), key=lambda x: x[1]["days"], reverse=True):
            pct = round(info["days"] / daily_result["n_days"] * 100, 1)
            print(f"    {code} {info['name']}: {info['days']}/{daily_result['n_days']}天({pct}%)")

    # === 对比 ===
    if results_all and daily_result:
        print("\n" + "=" * 50)
        print("对比: 全ETF vs 每日Top-2")
        print("=" * 50)
        pnl_all = sum(r.get("total_pnl", r["total_profit"]) for r in results_all)
        capital_all = sum(r["capital"] for r in results_all)
        dd_all = max(r["max_drawdown_pct"] for r in results_all)
        ret_all = pnl_all / capital_all * 100 if capital_all else 0

        print(f"  全ETF:      盈亏={pnl_all:+.2f}, 资金={capital_all}, 收益率={ret_all:+.2f}%, 回撤={dd_all:.2f}%")
        print(f"  每日Top-2:  盈亏={daily_result['total_pnl']:+.2f}, 资金={daily_result['capital']}, 收益率={daily_result['return_pct']:+.2f}%, 回撤={daily_result['max_drawdown_pct']}%")

    print(f"\n报告已生成: {out_dir}")
