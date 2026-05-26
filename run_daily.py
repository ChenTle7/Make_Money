"""每日报告生成主入口"""
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import asdict

# 项目根目录加入path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    WATCHLIST, DATA_DIR, REPORT_DIR, TEMPLATE_DIR,
    A_SHARE_INDICES, HK_INDICES, US_INDICES,
    TRADE_CAPITAL, MAX_ACTIVE_ETFS,
)
from data.market_indices import fetch_all_indices, fetch_hk_index_daily
from data.etf_data import fetch_all_etfs, fetch_etf_realtime
from data.news_fetcher import fetch_all_news
from analysis.trend_assessment import TrendAssessment
from analysis.grid_params import calculate_grid
from analysis.daily_recommendation import generate_recommendation
from analysis.tomorrow_watch import generate_tomorrow_watch as generate_pro_tomorrow_watch
from analysis.future_timeline import generate_future_timeline
from reports.html_report import build_report, build_grid_doc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(DATA_DIR / "run.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)


def generate_market_commentary(indices: dict) -> str:
    """根据指数数据生成市场评论"""
    parts = []

    # A股
    ashare = indices.get("ashare", {})
    sh = ashare.get("上证指数", {})
    if "close" in sh:
        chg = sh.get("change_pct", 0)
        direction = "上涨" if chg > 0 else "下跌" if chg < 0 else "持平"
        parts.append(f"A股今日{direction}，上证指数{direction}{abs(chg)}%至{sh['close']}点")

        sz = ashare.get("深证成指", {})
        cy = ashare.get("创业板指", {})
        if "close" in sz and "close" in cy:
            sz_chg = sz.get("change_pct", 0)
            cy_chg = cy.get("change_pct", 0)
            if abs(cy_chg) > abs(sz_chg) and abs(cy_chg) > 0.5:
                parts.append(f"创业板指波动较大({cy_chg:+.2f}%)，成长股情绪{'偏乐观' if cy_chg > 0 else '偏谨慎'}")

    # 港股
    hk = indices.get("hk", {})
    hsi = hk.get("恒生指数", {})
    hstech = hk.get("恒生科技指数", {})
    if "close" in hsi:
        hsi_chg = hsi.get("change_pct", 0)
        parts.append(f"恒生指数{hsi_chg:+.2f}%，港股市场{'偏强' if hsi_chg > 0 else '偏弱'}")
    if "close" in hstech and "close" in hsi:
        tech_chg = hstech.get("change_pct", 0)
        hsi_chg = hsi.get("change_pct", 0)
        if abs(tech_chg) > abs(hsi_chg) and abs(tech_chg) > 0.5:
            parts.append(f"恒生科技指数波动大于大盘({tech_chg:+.2f}%)，科技板块{'领涨' if tech_chg > 0 else '领跌'}")

    # 对港股ETF的影响
    if hsi.get("change_pct", 0) < -1:
        parts.append("港股今日跌幅较大，港股ETF网格交易可关注下方买入机会")
    elif hsi.get("change_pct", 0) > 1:
        parts.append("港股今日涨幅可观，港股ETF关注上方卖出网格是否触发")
    else:
        parts.append("港股波动不大，按正常网格间距执行")

    return "。".join(parts) + "。"


def generate_tomorrow_watch(indices: dict, news: dict) -> list:
    """生成明日关注事项"""
    items = []

    # 美股走势影响
    us = indices.get("us", {})
    for name, idx in us.items():
        if "change_pct" in idx and abs(idx["change_pct"]) > 1:
            direction = "大涨" if idx["change_pct"] > 0 else "大跌"
            items.append(f"美股{name}{direction}{idx['change_pct']:+.2f}%，明日港股开盘可能受情绪影响")

    # 港股趋势
    hk = indices.get("hk", {})
    hsi = hk.get("恒生指数", {})
    if "change_pct" in hsi and abs(hsi["change_pct"]) > 1.5:
        items.append(f"恒指今日波动较大({hsi['change_pct']:+.2f}%)，明日注意仓位管理")

    # 从全球指标中提取关注
    global_idx = news.get("global_indicators", {}).get("indices", [])
    for idx in global_idx[:3]:
        pct = idx.get("change_pct", "0%")
        try:
            pct_val = float(pct.replace("%", "").replace("+", ""))
            if abs(pct_val) > 1.5:
                items.append(f"关注: {idx['name']}{pct}波动，注意港股联动")
        except ValueError:
            pass

    # 从要闻中提取关注
    top_news = news.get("top_news", [])
    for item in top_news[:2]:
        title = item.get("title", "")
        if title and len(title) > 5:
            items.append(f"关注: {title[:60]}")

    if not items:
        items.append("暂无特别关注事项，按网格计划正常执行")

    return items[:6]


def run():
    """主流程"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    log.info(f"{'='*50}")
    log.info(f"开始生成 {date_str} 港股ETF日报")
    log.info(f"{'='*50}")

    # === Step 1: 获取指数数据 ===
    log.info("[1/5] 获取大盘指数数据...")
    try:
        indices = fetch_all_indices()
        ashare_ok = sum(1 for v in indices["ashare"].values() if "close" in v)
        hk_ok = sum(1 for v in indices["hk"].values() if "close" in v)
        us_ok = sum(1 for v in indices["us"].values() if "close" in v)
        log.info(f"  A股: {ashare_ok}/3  港股: {hk_ok}/2  美股: {us_ok}/2")
    except Exception as e:
        log.error(f"  指数获取失败: {e}")
        indices = {"ashare": {}, "hk": {}, "us": {}}

    # === Step 1.5: 获取HSI日线数据（用于全局波动率）===
    log.info("[1.5] 获取恒生指数日线数据...")
    try:
        hsi_df = fetch_hk_index_daily("HSI", days=180)
        log.info(f"  HSI日线: {len(hsi_df)}天")
    except Exception as e:
        log.error(f"  HSI日线获取失败: {e}")
        hsi_df = None

    # === Step 2: 获取ETF数据 ===
    log.info("[2/5] 获取ETF日线数据 (180天)...")
    etf_daily = fetch_all_etfs(days=180)
    log.info(f"  成功获取 {len(etf_daily)}/{len(WATCHLIST)} 只ETF")

    # === Step 3: 获取新闻 ===
    log.info("[3/5] 获取市场新闻 (三部分)...")
    try:
        news = fetch_all_news()
        log.info(f"  要闻: {len(news.get('top_news',[]))}条  指标: {len(news.get('global_indicators',{}).get('indices',[]))+len(news.get('global_indicators',{}).get('commodities',[]))+len(news.get('global_indicators',{}).get('forex',[]))}项  研报: {len(news.get('research_reports',[]))}份")
    except Exception as e:
        log.error(f"  新闻获取失败: {e}")
        news = {"top_news": [], "global_indicators": {"indices": [], "commodities": [], "forex": []}, "research_reports": []}

    # === Step 4: 分析 ===
    log.info("[4/5] 技术分析 & 生成建议...")
    etf_analysis = []

    for etf_cfg in WATCHLIST:
        code = etf_cfg["code"]
        name = etf_cfg["name"]
        daily_df = etf_daily.get(code)

        if daily_df is None or len(daily_df) < 20:
            log.warning(f"  {code} {name}: 数据不足，跳过")
            continue

        log.info(f"  分析 {code} {name}...")

        # 趋势分析
        ta = TrendAssessment(code, name, daily_df)
        trend = ta.assess()

        # 网格参数
        current_price = float(daily_df["close"].iloc[-1])
        avg_amp = float(daily_df["amplitude"].mean())
        grid = calculate_grid(code, name, current_price, avg_amp, trend,
                              etf_df=daily_df, hsi_df=hsi_df)
        grid_dict = asdict(grid)

        # 实时行情（现价+涨跌幅，用自身日线计算涨跌幅更准确）
        try:
            realtime = fetch_etf_realtime(code)
            realtime_price = realtime.get("price", current_price)
        except Exception:
            realtime_price = current_price
        # 用日线数据计算涨跌幅（比实时接口的昨收更可靠）
        if len(daily_df) >= 2:
            prev_close = float(daily_df["close"].iloc[-2])
            change_pct = round((realtime_price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
        else:
            change_pct = 0

        # 每日建议
        rec = generate_recommendation(code, name, trend, grid, {
            "change_pct": change_pct,
            "volume_ratio": trend.get("volume_analysis", {}).get("vol_ratio", 1.0),
        })

        action = rec.get("action", "观望")
        action_class = {"买入": "buy", "持有": "hold", "减仓": "sell"}.get(action, "wait")

        # 网格优化指标（从缓存读取）
        from analysis.grid_backtest import load_spacing_cache
        spacing_cache = load_spacing_cache()
        opt = spacing_cache.get("etfs", {}).get(code, {})

        signals_detail = trend.get("signals_detail", {})
        bullish_count = sum(1 for v in signals_detail.values()
                           if v in ("bullish", "oversold", "near_lower"))

        etf_analysis.append({
            "code": code,
            "name": name,
            "current_price": round(realtime_price, 3),
            "change_pct": change_pct,
            "action": action,
            "action_class": action_class,
            "confidence": rec.get("confidence", 2),
            "reasoning": rec.get("reasoning", ""),
            "trend_6m": trend.get("trend_6m", "?"),
            "trend_3m": trend.get("trend_3m", "?"),
            "trend_1m": trend.get("trend_1m", "?"),
            "trend_1w": trend.get("trend_1w", "?"),
            "trend_6m_pct": trend.get("trend_6m_pct", 0),
            "trend_3m_pct": trend.get("trend_3m_pct", 0),
            "trend_1m_pct": trend.get("trend_1m_pct", 0),
            "trend_1w_pct": trend.get("trend_1w_pct", 0),
            "oversold_score": trend.get("oversold_score", 0),
            "signal_strength": trend.get("signal_strength", "中性"),
            "spacing_pct": grid_dict.get("spacing_pct", 0),
            "grid_count": grid_dict.get("grid_count", 6),
            "grid_capital": grid_dict.get("capital", 6000),
            "levels": grid_dict.get("levels", []),
            "grid_reason": grid_dict.get("reason", ""),
            "grid_recommendation": grid_dict.get("grid_recommendation", "normal"),
            # 价格区间
            "price_range_low": grid_dict.get("price_range_low", 0),
            "price_range_high": grid_dict.get("price_range_high", 0),
            # 同花顺条件单参数
            "ths_params": grid_dict.get("ths_params", {}),
            # 信号矩阵数据
            "signals_detail": signals_detail,
            "volume_analysis": trend.get("volume_analysis", {}),
            "bullish_count": bullish_count,
            "is_prolonged_downtrend": trend.get("is_prolonged_downtrend", False),
            "downtrend_days": trend.get("downtrend_days", 0),
            "rsi_value": trend.get("rsi_value", 50),
            "kdj_j": trend.get("kdj_j", 50),
            # 网格回测指标
            "grid_return_pct": opt.get("return_pct", 0),
            "grid_max_dd_pct": opt.get("max_drawdown_pct", 0),
            "grid_win_rate": opt.get("win_rate", 0),
        })

        # 风险预警
        levels = grid_dict.get("levels", [])
        if levels:
            lowest_buy = levels[-1]["buy_price"]
            grid_range_pct = (current_price - lowest_buy) / current_price * 100
            if grid_range_pct < 5:
                log.warning(f"  ⚠ {code} 网格底部仅距现价{grid_range_pct:.1f}%，存在击穿风险")
            if grid_dict.get("spacing_pct", 0) > 2.5:
                log.warning(f"  ⚠ {code} 间距{grid_dict['spacing_pct']}%，交易频率可能较低")

        time.sleep(0.3)

    # === Step 5: 生成报告 ===
    log.info("[5/5] 生成HTML报告...")
    commentary = generate_market_commentary(indices)

    log.info("  生成专业级明日关注...")
    tomorrow = generate_pro_tomorrow_watch(indices)

    log.info("  生成未来事件时间轴...")
    timeline = generate_future_timeline(max_per_day=3)

    generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report_path = build_report(
        date_str=date_str,
        indices=indices,
        market_commentary=commentary,
        top_news=news.get("top_news", []),
        global_indicators=news.get("global_indicators", {}),
        research_reports=news.get("research_reports", []),
        tomorrow_watch=tomorrow,
        etf_analysis=etf_analysis,
        generate_time=generate_time,
        future_timeline=timeline,
    )

    log.info(f"{'='*50}")
    log.info(f"报告已生成: {report_path}")

    # 生成简易网格推荐文档
    log.info("生成网格推荐文档...")
    build_grid_doc(date_str, etf_analysis, tomorrow)

    log.info(f"{'='*50}")

    return report_path


if __name__ == "__main__":
    report_path = run()
    print(f"\n报告路径: {report_path}")
    print(f"用浏览器打开查看")
