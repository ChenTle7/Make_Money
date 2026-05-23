"""网格参数计算 - 趋势自适应"""
from dataclasses import dataclass, asdict
from config import COMMISSION_RATE, GRID_COUNT


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
    capital: float
    levels: list
    recommendation: str
    reason: str
    grid_recommendation: str


def calculate_grid(
    code: str,
    name: str,
    current_price: float,
    avg_amplitude: float,
    trend: dict,
    capital: float = None,
    grid_count: int = GRID_COUNT,
) -> GridParams:
    """计算网格参数，根据趋势调整间距

    - 基础间距 = 平均振幅 × 0.8
    - 超卖评分≥6: 间距×0.9 (潜在反弹，收窄网格)
    - 强势上涨: 间距×1.2 (趋势市场放宽)
    - 长期下跌: 间距×0.85，优先低位
    """
    if capital is None:
        from config import TRADE_CAPITAL, MAX_ACTIVE_ETFS
        capital = TRADE_CAPITAL / MAX_ACTIVE_ETFS

    # 基础间距
    spacing_pct = round(avg_amplitude * 0.8, 2)

    # 根据趋势调整
    oversold = trend.get("oversold_score", 0)
    grid_rec = trend.get("grid_recommendation", "normal")

    if grid_rec == "aggressive":
        spacing_pct = round(spacing_pct * 0.9, 2)
    elif grid_rec == "conservative":
        spacing_pct = round(spacing_pct * 1.2, 2)

    spacing_price = round(current_price * spacing_pct / 100, 4)
    per_grid = capital / grid_count

    levels = []
    for i in range(grid_count):
        buy_price = round(current_price - spacing_price * (i + 1), 4)
        sell_price = round(buy_price + spacing_price, 4)
        shares = int(per_grid / buy_price / 100) * 100
        if shares < 100:
            shares = 100
        profit = round(shares * spacing_price, 2)
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
    if oversold >= 6:
        rec = "建议买入"
        reason = f"超卖评分{oversold}/10，多项指标显示超卖，网格间距已收紧至{spacing_pct}%以捕捉反弹"
    elif oversold >= 4:
        rec = "适度参与"
        reason = f"超卖评分{oversold}/10，有一定超卖信号，按标准间距{spacing_pct}%挂单"
    elif trend.get("signal_strength") == "卖出":
        rec = "建议观望"
        reason = f"多项指标偏空，暂停网格或缩小仓位，间距{spacing_pct}%"
    else:
        rec = "按计划挂单"
        reason = f"趋势中性，按标准间距{spacing_pct}%执行网格"

    return GridParams(
        code=code,
        name=name,
        current_price=current_price,
        grid_count=grid_count,
        spacing_pct=spacing_pct,
        spacing_price=spacing_price,
        capital=capital,
        levels=[asdict(l) for l in levels],
        recommendation=rec,
        reason=reason,
        grid_recommendation=grid_rec,
    )
