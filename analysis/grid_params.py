"""网格参数计算 - 趋势自适应 + 多因素调整"""
import logging
from dataclasses import dataclass, asdict
from config import COMMISSION_RATE, GRID_COUNT

log = logging.getLogger(__name__)


@dataclass
class GridLevel:
    grid_num: int
    buy_price: float
    sell_price: float
    shares: int
    profit_per_trade: float
    fee_per_trade: float


@dataclass
class GridParams:
    code: str
    name: str
    current_price: float
    grid_count: int
    spacing_pct: float
    spacing_price: float
    buy_spacing_pct: float = 0.0
    sell_spacing_pct: float = 0.0
    buy_spacing_price: float = 0.0
    sell_spacing_price: float = 0.0
    capital: float = 0.0
    levels: list = None
    recommendation: str = ""
    reason: str = ""
    grid_recommendation: str = ""
    price_range_low: float = 0.0
    price_range_high: float = 0.0
    ths_params: dict = None


def _find_support_resistance(df, window: int = 60):
    """从近N天数据中找支撑位和阻力位（局部极值点）"""
    recent = df.tail(window)
    if len(recent) < 11:
        return None, None

    # 支撑：最近的局部最低点（前后各5天内最低）
    lows = recent["low"].values
    supports = []
    for i in range(5, len(lows) - 5):
        if lows[i] == min(lows[i - 5:i + 6]):
            supports.append(float(lows[i]))
    support = max(supports) if supports else float(recent["low"].min())

    # 阻力：最近的局部最高点
    highs = recent["high"].values
    resistances = []
    for i in range(5, len(highs) - 5):
        if highs[i] == max(highs[i - 5:i + 6]):
            resistances.append(float(highs[i]))
    resistance = min(resistances) if resistances else float(recent["high"].max())

    return support, resistance


def calculate_grid(
    code: str,
    name: str,
    current_price: float,
    avg_amplitude: float,
    trend: dict,
    capital: float = None,
    grid_count: int = GRID_COUNT,
    etf_df=None,
    hsi_df=None,
) -> GridParams:
    """计算网格参数，多因素自适应调整

    调整因素（优先级从高到低）:
    1. 历史最优间距乘数（取代默认0.8，每周一回测更新）
    2. 近期波动率变化（7天/180天振幅比值）
    3. 恒生指数全局波动率（HSI 7天/180天振幅比值）
    4. 支撑/阻力位收窄（距关键位<3%时收紧20%）
    5. 趋势调整（超卖/强势等，原有逻辑）
    """
    if capital is None:
        from config import CAPITAL_PER_ETF
        capital = CAPITAL_PER_ETF

    # === 动态资金调整：根据推荐程度决定实际投入 ===
    grid_rec = trend.get("grid_recommendation", "normal")
    if grid_rec == "aggressive":
        capital = round(capital * 1.2, 0)
    elif grid_rec == "conservative":
        capital = round(capital * 0.7, 0)
    else:
        capital = round(capital * 0.9, 0)

    # === 基础间距 ===
    # 因素1: 历史最优参数（间距乘数 + 格数，资金由用户配置决定）
    optimal_mult = 0.8
    optimized_grid_count = None
    if etf_df is not None and len(etf_df) >= 30:
        from analysis.grid_backtest import get_optimal_params
        try:
            opt = get_optimal_params(code, etf_df)
            optimal_mult = opt.get("optimal_multiplier", 0.8)
            optimized_grid_count = opt.get("grid_count")
        except Exception as e:
            log.warning(f"  {code} 优化失败，使用默认参数: {e}")

    spacing_pct = round(avg_amplitude * optimal_mult, 2)
    # 防止振幅为0导致间距为0，后续除零崩溃
    if spacing_pct < 0.3:
        log.warning(f"  {code} 振幅过小({avg_amplitude:.2f}%)，间距设为最低0.3%")
        spacing_pct = 0.3
    adj_log = f"基础={avg_amplitude:.2f}×{optimal_mult}"

    # === 因素2: 近期波动率变化 ===
    vol_ratio = 1.0
    if etf_df is not None and len(etf_df) >= 7:
        amp_7d = float(etf_df["amplitude"].tail(7).mean())
        amp_180d = float(etf_df["amplitude"].mean())
        if amp_180d > 0:
            vol_ratio = amp_7d / amp_180d
            vol_ratio = max(0.7, min(1.5, vol_ratio))
            spacing_pct = round(spacing_pct * vol_ratio, 2)
            adj_log += f" ×波动率{vol_ratio:.2f}"

    # === 因素3: HSI 全局波动率 ===
    if hsi_df is not None and len(hsi_df) >= 7:
        hsi_amp_7d = float(hsi_df["amplitude"].tail(7).mean())
        hsi_amp_180d = float(hsi_df["amplitude"].mean())
        if hsi_amp_180d > 0:
            hsi_ratio = hsi_amp_7d / hsi_amp_180d
            hsi_ratio = max(0.8, min(1.3, hsi_ratio))
            if hsi_ratio > 1.2 or hsi_ratio < 0.85:
                spacing_pct = round(spacing_pct * hsi_ratio, 2)
                adj_log += f" ×HSI{hsi_ratio:.2f}"

    # === 因素4: 支撑/阻力位收窄 ===
    if etf_df is not None and len(etf_df) >= 60:
        support, resistance = _find_support_resistance(etf_df)
        sr_adj = 1.0
        if support is not None:
            dist = abs(current_price - support) / current_price
            if dist < 0.03:
                sr_adj *= 0.8
        if resistance is not None:
            dist = abs(resistance - current_price) / current_price
            if dist < 0.03:
                sr_adj *= 0.8
        if sr_adj < 1.0:
            spacing_pct = round(spacing_pct * sr_adj, 2)
            adj_log += f" ×S/R{sr_adj:.1f}"

    # === 因素5: 趋势调整 → 买卖步长分离 ===
    # 回测结论：下跌行情买紧卖松提升13-55%收益
    oversold = trend.get("oversold_score", 0)
    grid_rec = trend.get("grid_recommendation", "normal")

    if grid_rec == "aggressive":
        # 超卖/适合买入：买步长收窄多接筹码，卖步长放大多吃利润
        buy_spacing_pct = round(spacing_pct * 0.85, 2)
        sell_spacing_pct = round(spacing_pct * 1.2, 2)
        adj_log += f" 买{buy_spacing_pct}×0.85 卖{sell_spacing_pct}×1.2"
    elif grid_rec == "conservative":
        # 偏空/谨慎：买步长放宽避免接飞刀，卖步长收紧见好就收
        buy_spacing_pct = round(spacing_pct * 1.15, 2)
        sell_spacing_pct = round(spacing_pct * 0.9, 2)
        adj_log += f" 买{buy_spacing_pct}×1.15 卖{sell_spacing_pct}×0.9"
    else:
        # 中性：买卖步长基本对称，微调卖略宽
        buy_spacing_pct = spacing_pct
        sell_spacing_pct = round(spacing_pct * 1.1, 2)
        adj_log += f" 买{buy_spacing_pct} 卖{sell_spacing_pct}×1.1"

    log.info(f"  {code} 步长: {adj_log} → 买{buy_spacing_pct}% 卖{sell_spacing_pct}%")

    # === 全线下跌趋势放宽间距 ===
    all_down = all(
        trend.get(f"trend_{p}", "?") == "跌"
        for p in ["6m", "3m", "1m", "1w"]
    )
    if all_down:
        buy_spacing_pct = round(buy_spacing_pct * 1.3, 2)
        sell_spacing_pct = round(sell_spacing_pct * 1.3, 2)
        log.info(f"  {code} 全周期下跌，买卖间距均放宽×1.3")

    # 间距上限：超过3.5%强制收窄
    buy_spacing_pct = min(buy_spacing_pct, 3.5)
    sell_spacing_pct = min(sell_spacing_pct, 3.5)

    # 平均间距（用于格数判断）
    avg_spacing_pct = round((buy_spacing_pct + sell_spacing_pct) / 2, 2)

    # === 宽间距ETF自动缩减格数 ===
    effective_grid_count = grid_count
    if avg_spacing_pct > 2.0:
        effective_grid_count = max(4, grid_count - 1)
        if effective_grid_count != grid_count:
            log.info(f"  {code} 均间距>{2}%, 格数 {grid_count}→{effective_grid_count}")

    # 优先使用优化格数（覆盖自动缩减和默认值）
    if optimized_grid_count is not None:
        effective_grid_count = optimized_grid_count

    # 防止格数为0导致除零
    effective_grid_count = max(1, effective_grid_count)

    per_grid = capital / effective_grid_count

    buy_spacing_price = round(current_price * buy_spacing_pct / 100, 4)
    sell_spacing_price = round(current_price * sell_spacing_pct / 100, 4)

    levels = []
    for i in range(effective_grid_count):
        buy_price = round(current_price - buy_spacing_price * (i + 1), 4)
        sell_price = round(buy_price + sell_spacing_price, 4)
        shares = int(per_grid / buy_price / 100) * 100
        if shares < 100:
            shares = 100
        profit = round(shares * sell_spacing_price, 2)
        fee = round(shares * (buy_price + sell_price) * COMMISSION_RATE, 2)
        levels.append(GridLevel(
            grid_num=i + 1,
            buy_price=round(buy_price, 3),
            sell_price=round(sell_price, 3),
            shares=shares,
            profit_per_trade=profit,
            fee_per_trade=fee,
        ))

    # 建议
    risk_notes = []
    if all_down:
        risk_notes.append("各周期均下跌，间距已放宽")
    if avg_spacing_pct > 2.5:
        risk_notes.append(f"间距较大({avg_spacing_pct}%)，触发频率低")
    if effective_grid_count < grid_count:
        risk_notes.append(f"间距>2%，格数已缩减至{effective_grid_count}")

    risk_suffix = "；".join(risk_notes)
    risk_suffix = f"。注意：{risk_suffix}" if risk_suffix else ""

    if oversold >= 6:
        rec = "建议买入"
        reason = f"超卖评分{oversold}/10，买入间距收窄至{buy_spacing_pct}%以多接筹码，卖出间距{sell_spacing_pct}%吃足反弹{risk_suffix}"
    elif oversold >= 4:
        rec = "适度参与"
        reason = f"超卖评分{oversold}/10，买入{buy_spacing_pct}%/卖出{sell_spacing_pct}%挂单{risk_suffix}"
    elif trend.get("signal_strength") == "卖出":
        rec = "建议观望"
        reason = f"多项指标偏空，买入间距放宽至{buy_spacing_pct}%避免接飞刀，卖出{sell_spacing_pct}%见好就收{risk_suffix}"
    else:
        rec = "按计划挂单"
        reason = f"趋势中性，买入{buy_spacing_pct}%/卖出{sell_spacing_pct}%执行网格{risk_suffix}"

    # === 价格区间（条件单有效触发范围）===
    # 买入深、卖出浅：下方多留空间捕捉下跌机会，上方适度覆盖反弹
    buy_depth = effective_grid_count      # 买入基础深度：网格数
    sell_depth = max(2, effective_grid_count // 2)  # 卖出基础深度：网格数一半，至少2格

    if etf_df is not None and len(etf_df) >= 30:
        # 支撑/阻力位
        support, resistance = _find_support_resistance(etf_df)
        if support is not None and support < current_price:
            support_grids = int((current_price - support) / buy_spacing_price) + 1
            buy_depth = max(buy_depth, support_grids)
        if resistance is not None and resistance > current_price:
            resistance_grids = int((resistance - current_price) / sell_spacing_price)
            sell_depth = max(sell_depth, resistance_grids)

        # 历史振幅参考
        avg_amp_abs = current_price * float(etf_df["amplitude"].mean()) / 100
        if avg_amp_abs > 0:
            close_60 = etf_df["close"].tail(60)
            rolling_max = close_60.expanding().max()
            max_dd_pct = float(((rolling_max - close_60) / rolling_max).max())
            rolling_min = close_60.expanding().min()
            max_bounce_pct = float(((close_60 - rolling_min) / rolling_min).max())

            dd_grids = int(max_dd_pct * current_price / buy_spacing_price * 0.8) + 1
            buy_depth = max(buy_depth, dd_grids)
            bounce_grids = int(max_bounce_pct * current_price / sell_spacing_price * 0.6) + 1
            sell_depth = max(sell_depth, bounce_grids)

    # 合理上限：防止过度投入
    buy_depth = min(buy_depth, 10)
    sell_depth = min(sell_depth, 6)

    price_range_low = round(current_price - buy_depth * buy_spacing_price, 3)
    price_range_high = round(current_price + sell_depth * sell_spacing_price, 3)

    log.info(f"  {code} 价格区间: 下{buy_depth}格({buy_depth*buy_spacing_pct:.1f}%) "
             f"上{sell_depth}格({sell_depth*sell_spacing_pct:.1f}%) "
             f"→ {price_range_low} ~ {price_range_high}")

    # === 同花顺条件单参数 ===
    shares_per_grid = levels[0].shares if levels else 100
    buy_opt = round(buy_spacing_price * 0.1, 4)
    sell_opt = round(sell_spacing_price * 0.1, 4)
    buy_opt = round(max(0.001, min(buy_opt, 0.01)), 3)
    sell_opt = round(max(0.001, min(sell_opt, 0.01)), 3)
    max_position = shares_per_grid * effective_grid_count
    min_position = 0
    actual_deployed = sum(l.shares * l.buy_price for l in levels) if levels else capital
    per_grid_yuan = round(shares_per_grid * current_price, 0)
    range_low_pct = round((price_range_low - current_price) / current_price * 100, 1)
    range_high_pct = round((price_range_high - current_price) / current_price * 100, 1)
    max_pos_yuan = round(actual_deployed, 0)

    ths_params = {
        "buy_spacing_price": round(buy_spacing_price, 4),
        "sell_spacing_price": round(sell_spacing_price, 4),
        "buy_spacing_pct": buy_spacing_pct,
        "sell_spacing_pct": sell_spacing_pct,
        "shares_per_grid": shares_per_grid,
        "per_grid_yuan": per_grid_yuan,
        "buy_optimize": buy_opt,
        "sell_optimize": sell_opt,
        "max_position": max_position,
        "max_pos_yuan": max_pos_yuan,
        "range_low_pct": range_low_pct,
        "range_high_pct": range_high_pct,
        "min_position": min_position,
    }

    return GridParams(
        code=code,
        name=name,
        current_price=current_price,
        grid_count=effective_grid_count,
        spacing_pct=avg_spacing_pct,
        spacing_price=round((buy_spacing_price + sell_spacing_price) / 2, 4),
        buy_spacing_pct=buy_spacing_pct,
        sell_spacing_pct=sell_spacing_pct,
        buy_spacing_price=buy_spacing_price,
        sell_spacing_price=sell_spacing_price,
        capital=capital,
        levels=[asdict(l) for l in levels],
        recommendation=rec,
        reason=reason,
        grid_recommendation=grid_rec,
        price_range_low=price_range_low,
        price_range_high=price_range_high,
        ths_params=ths_params,
    )
