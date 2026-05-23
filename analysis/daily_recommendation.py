"""每日建议生成"""


def generate_recommendation(code: str, name: str, trend: dict, grid, today: dict) -> dict:
    """生成每日建议

    Args:
        code: ETF代码
        name: ETF名称
        trend: TrendAssessment.assess() 结果
        grid: GridParams 对象
        today: {"change_pct": float, "volume_ratio": float}
    """
    oversold = trend.get("oversold_score", 0)
    strength = trend.get("signal_strength", "中性")
    prolonged = trend.get("is_prolonged_downtrend", False)
    down_days = trend.get("downtrend_days", 0)
    signals = trend.get("signals_detail", {})
    change_pct = today.get("change_pct", 0)
    trend_text = _trend_commentary(trend, name)

    # 决定操作
    if oversold >= 6 and prolonged and strength in ("强买", "买入"):
        action = "买入"
        confidence = 5 if oversold >= 8 else 4
        reasoning = _buy_reasoning(oversold, down_days, signals, change_pct, name, trend_text)
    elif oversold >= 5 and strength == "买入":
        action = "买入"
        confidence = 3
        reasoning = _buy_reasoning(oversold, down_days, signals, change_pct, name, trend_text)
    elif strength == "卖出":
        action = "减仓"
        confidence = 3
        reasoning = f"{name}{trend_text}。多项指标偏空，建议暂停新增买入，已有仓位持有等待信号转暖"
    elif oversold >= 3:
        action = "持有"
        confidence = 3
        reasoning = f"{name}{trend_text}。有一定超卖迹象但信号不够强，继续持有现有仓位，等待更明确信号"
    else:
        action = "观望"
        confidence = 2
        reasoning = f"{name}{trend_text}。暂不建议新增网格仓位，等待更好的入场时机"

    # 支撑/阻力位
    levels = grid.levels if hasattr(grid, 'levels') else grid.get("levels", [])
    buy_levels = sorted([l["buy_price"] for l in levels]) if levels else []
    sell_levels = sorted([l["sell_price"] for l in levels]) if levels else []

    # 网格操作建议
    if oversold >= 6:
        grid_action = "缩小间距挂单"
    elif strength == "卖出":
        grid_action = "暂停网格"
    elif trend.get("trend_1w") == "涨":
        grid_action = "按计划挂单，适当上移"
    else:
        grid_action = "按计划挂单"

    return {
        "code": code,
        "name": name,
        "action": action,
        "confidence": confidence,
        "reasoning": reasoning,
        "key_levels": {
            "support": buy_levels[0] if buy_levels else 0,
            "resistance": sell_levels[-1] if sell_levels else 0,
        },
        "grid_action": grid_action,
    }


def _trend_commentary(trend: dict, name: str) -> str:
    """根据多周期趋势生成专业评论"""
    t6 = trend.get("trend_6m", "未知")
    t3 = trend.get("trend_3m", "未知")
    t1 = trend.get("trend_1m", "未知")
    tw = trend.get("trend_1w", "未知")
    p6 = trend.get("trend_6m_pct", 0)
    p3 = trend.get("trend_3m_pct", 0)
    p1 = trend.get("trend_1m_pct", 0)
    pw = trend.get("trend_1w_pct", 0)

    parts = []

    # 半年大趋势
    if t6 == "跌" and abs(p6) > 15:
        parts.append(f"半年累计下跌{abs(p6):.1f}%，中长期趋势偏弱")
    elif t6 == "跌":
        parts.append(f"半年下跌{abs(p6):.1f}%，中期偏弱")
    elif t6 == "涨" and p6 > 15:
        parts.append(f"半年累计上涨{p6:.1f}%，中长期趋势偏强")
    elif t6 == "涨":
        parts.append(f"半年上涨{p6:.1f}%，中期偏强")
    else:
        parts.append(f"半年震荡({p6:+.1f}%)，中期方向不明")

    # 近期变化
    if t1 == "横盘" and tw in ("涨", "横盘"):
        if t6 == "跌":
            parts.append("近月趋稳，长期下跌动能衰竭，适合加大网格仓位捕捉反弹")
        else:
            parts.append("近月横盘整理，等待方向选择")
    elif t1 == "涨" and t6 == "跌":
        if p1 > 0:
            parts.append(f"近月上涨{p1:+.1f}%出现企稳反弹信号，可适度参与")
        else:
            parts.append(f"近月趋稳({p1:+.1f}%)，下跌减速企稳中，可适度参与")
    elif t1 == "涨" and tw == "涨":
        parts.append(f"近月{p1:+.1f}%、近周{pw:+.1f}%，短期动能偏强")
    elif t1 == "跌" and tw == "跌":
        if t6 == "跌":
            parts.append("各周期均呈下跌，建议控制仓位等待企稳")
        else:
            parts.append(f"近期回调(月{p1:+.1f}%，周{pw:+.1f}%)，关注下方支撑")
    elif tw == "跌" and t1 in ("涨", "横盘"):
        parts.append(f"本周微调{pw:+.1f}%，属正常波动")
    elif tw == "涨" and t1 == "跌":
        parts.append(f"本周反弹{pw:+.1f}%，短期止跌信号初现")

    return "，".join(parts)


def _buy_reasoning(oversold, down_days, signals, change_pct, name, trend_text=""):
    """生成买入推理文字"""
    parts = [f"{name}{trend_text}"]

    if down_days > 20:
        parts.append(f"已连续{down_days}日处于均线下方，长期下跌动能可能衰竭")

    detail = []
    kdj = signals.get("KDJ", "")
    rsi = signals.get("RSI", "")
    boll = signals.get("BOLL", "")
    if kdj == "oversold":
        detail.append("KDJ进入超卖区")
    if rsi == "oversold":
        detail.append("RSI进入超卖区")
    if boll == "near_lower":
        detail.append("价格触及布林带下轨")
    if detail:
        parts.append("，".join(detail))

    if change_pct > 0:
        parts.append(f"今日上涨{change_pct}%，或已开始企稳反弹")
    elif change_pct < -1:
        parts.append(f"今日下跌{change_pct}%，但超卖评分较高，下跌空间有限")

    parts.append(f"超卖评分{oversold}/10，建议适度加大网格仓位")
    return "，".join(parts)
