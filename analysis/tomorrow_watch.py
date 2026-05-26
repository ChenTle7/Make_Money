"""明日关注 - 专业级分析模块

基于真实市场数据，从宏观、资金、技术面、风险四个维度生成明日关注内容。
信息来源标注清楚，区分确定性事件与市场预期。
"""
import akshare as ak
import pandas as pd
import requests
import logging
import time
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


# ============================================================
# 数据获取
# ============================================================

def fetch_northbound_flow() -> dict:
    """获取港股通（南向）资金流向"""
    result = {"recent_5d": [], "today_net": 0, "trend": "unknown"}
    try:
        df_hu = ak.stock_hsgt_hist_em(symbol="港股通沪")
        df_shen = ak.stock_hsgt_hist_em(symbol="港股通深")

        def _latest_net(df):
            """从港股通历史数据中取最近一天的净流入"""
            if df is None or len(df) == 0:
                return 0, ""
            latest = df.iloc[-1]
            date = str(latest.iloc[0])
            # 列[1]=当日成交总额(亿)，即买入-卖出的净流入
            # 列[5]=当日资金净流入(亿)，新数据可能为NaN
            if pd.notna(latest.iloc[1]):
                net = float(latest.iloc[1])
            elif pd.notna(latest.iloc[5]):
                net = float(latest.iloc[5])
            else:
                # 兜底: 用买入-卖出计算
                buy = float(latest.iloc[2]) if pd.notna(latest.iloc[2]) else 0
                sell = float(latest.iloc[3]) if pd.notna(latest.iloc[3]) else 0
                net = buy - sell
            return round(net, 2), date

        hu_net, hu_date = _latest_net(df_hu)
        shen_net, shen_date = _latest_net(df_shen)
        today_net = round(hu_net + shen_net, 2)
        today_date = hu_date or shen_date

        result["today_net"] = today_net
        result["trend"] = "流入" if today_net > 0 else "流出" if today_net < 0 else "持平"
        result["today_date"] = today_date
        result["hu_net"] = hu_net
        result["shen_net"] = shen_net

        # 最近5天数据
        if df_hu is not None and len(df_hu) >= 5:
            for _, row in df_hu.tail(5).iterrows():
                net = float(row.iloc[1]) if pd.notna(row.iloc[1]) else 0
                result["recent_5d"].append({
                    "date": str(row.iloc[0]),
                    "hu_net": round(net, 2),
                })
            # 补充深港通数据
            if df_shen is not None and len(df_shen) >= 5:
                for i, (_, row) in enumerate(df_shen.tail(5).iterrows()):
                    net = float(row.iloc[1]) if pd.notna(row.iloc[1]) else 0
                    if i < len(result["recent_5d"]):
                        result["recent_5d"][i]["shen_net"] = round(net, 2)
    except Exception as e:
        log.warning(f"港股通资金数据获取失败: {e}")

    return result


def fetch_margin_data() -> dict:
    """获取融资融券数据"""
    result = {"latest_date": "", "margin_balance": 0, "change": 0, "trend": "unknown", "day_span": 1}
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        df = ak.stock_margin_sse(start_date=start, end_date=end)
        if df is not None and len(df) > 0:
            df = df.sort_values(df.columns[0])
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            # 融资余额（第一列日期，第三列为融资余额）
            balance = float(latest.iloc[2]) if pd.notna(latest.iloc[2]) else 0
            prev_balance = float(prev.iloc[2]) if pd.notna(prev.iloc[2]) else 0
            change = balance - prev_balance
            # 计算日期跨度
            try:
                latest_date = pd.to_datetime(latest.iloc[0])
                prev_date = pd.to_datetime(prev.iloc[0])
                day_span = (latest_date - prev_date).days
            except Exception:
                day_span = 1
            result = {
                "latest_date": str(latest.iloc[0]),
                "prev_date": str(prev.iloc[0]),
                "margin_balance": round(balance / 1e8, 2),  # 亿元
                "change": round(change / 1e8, 2),
                "trend": "增加" if change > 0 else "减少",
                "day_span": day_span,
            }
    except Exception as e:
        log.warning(f"融资融券数据获取失败: {e}")
    return result


def fetch_limit_pool() -> dict:
    """获取涨跌停数据"""
    result = {"limit_up": 0, "limit_down": 0, "hot_sectors": []}
    try:
        date_str = datetime.now().strftime("%Y%m%d")
        df = ak.stock_zt_pool_em(date=date_str)
        if df is not None:
            result["limit_up"] = len(df)
            # 统计热门板块
            if len(df) > 0 and "所属行业" in df.columns:
                sectors = df["所属行业"].value_counts().head(5)
                result["hot_sectors"] = [{"name": k, "count": int(v)} for k, v in sectors.items()]
    except Exception:
        pass
    return result


def fetch_today_index_levels(indices: dict) -> dict:
    """从已有指数数据提取关键点位"""
    levels = {}
    for market_key in ["ashare", "hk"]:
        for name, idx in indices.get(market_key, {}).items():
            if "close" in idx and "high" in idx and "low" in idx:
                close = idx["close"]
                high = idx["high"]
                low = idx["low"]
                # 简单支撑/阻力计算
                pivot = round((high + low + close) / 3, 2)
                s1 = round(2 * pivot - high, 2)
                r1 = round(2 * pivot - low, 2)
                s2 = round(pivot - (high - low), 2)
                r2 = round(pivot + (high - low), 2)
                levels[name] = {
                    "close": close,
                    "pivot": pivot,
                    "support_1": s1, "support_2": s2,
                    "resist_1": r1, "resist_2": r2,
                    "high": high, "low": low,
                    "change_pct": idx.get("change_pct", 0),
                }
    return levels


# ============================================================
# 内容生成
# ============================================================

def _get_tomorrow_date() -> str:
    """获取明天日期（跳过周末）"""
    tomorrow = datetime.now() + timedelta(days=1)
    # 如果明天是周六，跳到周一
    if tomorrow.weekday() == 5:
        tomorrow += timedelta(days=2)
    elif tomorrow.weekday() == 6:
        tomorrow += timedelta(days=1)
    return tomorrow.strftime("%Y年%m月%d日")


def _get_weekday() -> str:
    tomorrow = datetime.now() + timedelta(days=1)
    if tomorrow.weekday() == 5:
        tomorrow += timedelta(days=2)
    elif tomorrow.weekday() == 6:
        tomorrow += timedelta(days=1)
    weekdays = ["周一", "周二", "周三", "周四", "周五"]
    return weekdays[tomorrow.weekday()]


def _event_relevance_score(row) -> float:
    """评估事件对港股ETF的相关度（越高越相关）"""
    event = str(row["事件"])
    region = str(row["地区"])
    imp = int(row["重要性"])

    score = 0.0

    # 地区权重
    region_scores = {"中国": 30, "香港": 25, "美国": 20, "日本": 5, "欧元区": 5}
    score += region_scores.get(region, 0)

    # 事件关键词权重（宏观经济 > 货币政策 > 行业数据 > 商品持仓）
    high_keywords = ["CPI", "PPI", "GDP", "PMI", "LPR", "MLF", "利率", "非农",
                     "就业", "工业利润", "社零", "进出口", "贸易帐", "制造业",
                     "FOMC", "联储", "央行", "零售", "失业率", "ADP"]
    mid_keywords = ["M2", "M1", "货币供应", "外汇", "国债", "通胀", "GDP",
                    "景气", "信心指数", "投资", "房地产"]
    low_keywords = ["持仓", "仓单", "ETF", "SPDR", "iShares", "黄金", "白银", "原油"]

    for kw in high_keywords:
        if kw in event:
            score += 15
            break
    else:
        for kw in mid_keywords:
            if kw in event:
                score += 8
                break
        else:
            for kw in low_keywords:
                if kw in event:
                    score -= 5
                    break

    # akshare 重要性加成
    score += imp * 5

    return score


def _generate_macro_calendar() -> list:
    """从百度财经日历获取明日宏观事件"""
    tomorrow = datetime.now() + timedelta(days=1)
    if tomorrow.weekday() >= 5:
        tomorrow += timedelta(days=7 - tomorrow.weekday()) if tomorrow.weekday() == 5 else timedelta(days=1)

    date_str = tomorrow.strftime("%Y%m%d")

    try:
        df = ak.news_economic_baidu(date=date_str)
        if df is None or len(df) == 0:
            return _fallback_calendar(tomorrow)

        df = df.copy()
        df["_score"] = df.apply(_event_relevance_score, axis=1)
        df = df.sort_values("_score", ascending=False)

        events = []
        seen_prefixes = set()
        for _, row in df.iterrows():
            if len(events) >= 5:
                break
            event_name = str(row["事件"]).strip()
            # 同类事件去重（如CPI有多个子指标，只取第1条）
            prefix = event_name[:8]
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)

            imp_map = {2: "高", 1: "中"}
            imp_label = imp_map.get(int(row["重要性"]), "中")

            actual = row.get("公布")
            expected = row.get("预期")
            if pd.notna(actual):
                evt_type = "已公布"
            elif pd.notna(expected):
                evt_type = "预期"
            else:
                evt_type = "关注"

            events.append({
                "time": str(row["时间"]),
                "event": event_name,
                "type": evt_type,
                "importance": imp_label,
                "source": str(row["地区"]),
            })

        if not events:
            return _fallback_calendar(tomorrow)

        return events

    except Exception as e:
        log.warning(f"财经日历获取失败: {e}")
        return _fallback_calendar(tomorrow)


def _fallback_calendar(tomorrow) -> list:
    """财经日历API不可用时的备用方案"""
    day = tomorrow.day
    month = tomorrow.month

    events = [{
        "time": "09:20",
        "event": "央行公开市场操作（逆回购）",
        "type": "确定",
        "importance": "中",
        "source": "央行官网",
    }]

    if 14 <= day <= 16:
        events.append({
            "time": "09:20",
            "event": "央行MLF续作（关注利率是否调整）",
            "type": "预期", "importance": "极高", "source": "央行操作日历",
        })
    if day == 20:
        events.append({
            "time": "09:15",
            "event": "央行公布LPR报价",
            "type": "确定", "importance": "极高", "source": "央行官网",
        })
    if 15 <= day <= 20 and month in [1, 4, 7, 10]:
        q = "第一" if month <= 3 else "第二" if month <= 6 else "第三" if month <= 9 else "第四"
        events.append({
            "time": "10:00",
            "event": f"国家统计局发布{q}季度GDP数据",
            "type": "预期", "importance": "极高", "source": "统计局",
        })

    return events


def quarter_label(month):
    if month <= 3: return "第一"
    if month <= 6: return "第二"
    if month <= 9: return "第三"
    return "第四"


def _generate_capital_flow_section(north: dict, margin: dict, limit_pool: dict) -> dict:
    """资金动向分析"""
    section = {
        "northbound": north,
        "margin": margin,
        "limit_pool": limit_pool,
        "analysis": [],
    }

    # 港股通南向资金分析
    if north.get("trend") == "流入":
        total = abs(north['today_net'])
        hu = abs(north.get('hu_net', 0))
        shen = abs(north.get('shen_net', 0))
        date = north.get('today_date', '')
        section["analysis"].append(
            f"港股通南向资金{date}净流入{total}亿元"
            f"（沪港通{hu}亿、深港通{shen}亿），内资情绪偏积极，"
            f"对港股ETF形成支撑。来源: 东方财富港股通数据"
        )
    elif north.get("trend") == "流出":
        total = abs(north['today_net'])
        hu = abs(north.get('hu_net', 0))
        shen = abs(north.get('shen_net', 0))
        date = north.get('today_date', '')
        section["analysis"].append(
            f"港股通南向资金{date}净流出{total}亿元"
            f"（沪港通{hu}亿、深港通{shen}亿），内资谨慎情绪升温，"
            f"港股ETF可能承压。来源: 东方财富港股通数据"
        )

    # 融资融券分析
    if margin.get("margin_balance", 0) > 0:
        direction = margin["trend"]
        change = abs(margin["change"])
        latest_date = margin.get("latest_date", "")
        prev_date = margin.get("prev_date", "")
        day_span = margin.get("day_span", 1)
        # 格式化日期显示
        date_display = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}" if len(latest_date) == 8 else latest_date
        prev_display = f"{prev_date[:4]}-{prev_date[4:6]}-{prev_date[6:]}" if len(prev_date) == 8 else prev_date
        if day_span > 1:
            span_text = f"较{prev_display}（{day_span}天）{direction}{change}亿元"
        else:
            span_text = f"较前日{direction}{change}亿元"
        section["analysis"].append(
            f"融资余额（{date_display}）{margin['margin_balance']}亿元（{span_text}），"
            f"两融资金{'偏乐观' if direction == '增加' else '偏谨慎'}。来源: 上交所融资融券数据"
        )

    # 涨停分析
    if limit_pool.get("limit_up", 0) > 0:
        count = limit_pool["limit_up"]
        section["analysis"].append(
            f"今日涨停{count}只，市场赚钱效应{'较好' if count > 50 else '一般' if count > 20 else '偏弱'}。"
        )
        if limit_pool.get("hot_sectors"):
            sectors_str = "、".join([f"{s['name']}({s['count']}只)" for s in limit_pool["hot_sectors"][:3]])
            section["analysis"].append(f"热门涨停板块: {sectors_str}。来源: 东方财富涨停板数据")

    return section


def _generate_technical_section(levels: dict) -> list:
    """技术面分析"""
    items = []

    for name, data in levels.items():
        chg = data.get("change_pct", 0)
        if "上证" in name:
            trend_desc = "收涨" if chg > 0 else "收跌" if chg < 0 else "持平"
            items.append(
                f"{name}今日{trend_desc}{abs(chg)}%（收于{data['close']}点），"
                f"明日支撑位 {data['support_1']} / {data['support_2']}，"
                f"压力位 {data['resist_1']} / {data['resist_2']}"
            )
        elif "恒生指数" == name:
            trend_desc = "收涨" if chg > 0 else "收跌" if chg < 0 else "持平"
            items.append(
                f"{name}今日{trend_desc}{abs(chg)}%（收于{data['close']}点），"
                f"明日支撑位 {data['support_1']} / {data['support_2']}，"
                f"压力位 {data['resist_1']} / {data['resist_2']}。"
                f"港股ETF网格交易关注此区间。"
            )
        elif "恒生科技" in name:
            trend_desc = "收涨" if chg > 0 else "收跌" if chg < 0 else "持平"
            items.append(
                f"{name}今日{trend_desc}{abs(chg)}%（收于{data['close']}点），"
                f"支撑位 {data['support_1']}，压力位 {data['resist_1']}"
            )

    return items


def _generate_strategy_section(levels: dict) -> dict:
    """操作策略建议"""
    # 判断大盘情绪
    sh_data = levels.get("上证指数", {})
    sh_chg = sh_data.get("change_pct", 0)
    hsi_data = levels.get("恒生指数", {})
    hsi_chg = hsi_data.get("change_pct", 0)

    if sh_chg > 1 and hsi_chg > 1:
        mood = "偏多"
        aggressive_pos = "7-8成"
        moderate_pos = "5-6成"
        conservative_pos = "3-4成"
    elif sh_chg < -1 or hsi_chg < -1:
        mood = "偏空"
        aggressive_pos = "5-6成"
        moderate_pos = "3-4成"
        conservative_pos = "2-3成"
    else:
        mood = "震荡"
        aggressive_pos = "6-7成"
        moderate_pos = "4-5成"
        conservative_pos = "2-3成"

    return {
        "mood": mood,
        "aggressive": {
            "position": aggressive_pos,
            "advice": f"港股ETF网格按计划执行，可适当{('加仓' if mood == '偏多' else '控制仓位')}，"
                      f"关注超卖反弹机会",
        },
        "moderate": {
            "position": moderate_pos,
            "advice": f"港股ETF保持标准网格间距，关注恒生指数支撑位，"
                      f"跌到位再加仓，{('短线可追' if mood == '偏多' else '暂不追高')}",
        },
        "conservative": {
            "position": conservative_pos,
            "advice": f"港股ETF以防守为主，网格间距可适当放宽，"
                      f"等待更明确信号再增加仓位",
        },
    }


def _generate_risk_alerts(indices: dict, limit_pool: dict) -> list:
    """风险提示（不少于3条）"""
    risks = []

    # 系统性风险
    us = indices.get("us", {})
    for name, idx in us.items():
        chg = idx.get("change_pct", 0)
        if abs(chg) > 1.5:
            risks.append({
                "category": "市场系统性风险",
                "detail": f"美股{name}前夜{'大涨' if chg > 0 else '大跌'}{chg:+.2f}%，"
                          f"港股开盘可能受联动影响，注意仓位控制",
                "source": "新浪财经美股数据",
            })

    hk = indices.get("hk", {})
    hsi = hk.get("恒生指数", {})
    if abs(hsi.get("change_pct", 0)) > 2:
        risks.append({
            "category": "市场系统性风险",
            "detail": f"恒指今日波动较大({hsi['change_pct']:+.2f}%)，明日可能延续波动",
            "source": "AKShare港股数据",
        })

    # 政策风险（通用模板）
    risks.append({
        "category": "政策风险",
        "detail": "关注是否有突发行业监管政策或贸易摩擦相关新闻",
        "source": "一般性风险提示",
    })

    # 个股/ETF风险
    if limit_pool.get("limit_up", 0) > 80:
        risks.append({
            "category": "市场过热风险",
            "detail": f"今日涨停{limit_pool['limit_up']}只，市场情绪过热，"
                      f"注意追高风险，港股ETF网格不必急于加仓",
            "source": "涨停板数据",
        })

    # 流动性风险
    risks.append({
        "category": "流动性风险",
        "detail": "注意北向资金和两融资金变化，若大幅流出可能影响港股ETF",
        "source": "一般性风险提示",
    })

    # 地缘风险
    risks.append({
        "category": "地缘政治风险",
        "detail": "关注中美关系、国际贸易局势等可能影响港股的外部因素",
        "source": "一般性风险提示",
    })

    return risks


# ============================================================
# 主函数
# ============================================================

def generate_tomorrow_watch(indices: dict) -> dict:
    """生成完整的明日关注分析

    Returns:
        dict with keys:
        - date: 明天日期
        - weekday: 星期几
        - macro_calendar: 宏观事件日历列表
        - capital_flow: 资金动向分析
        - technical_analysis: 技术面分析
        - strategy: 操作策略
        - risk_alerts: 风险提示列表
    """
    log.info("  生成明日关注分析...")

    # 获取数据
    log.info("    获取北向资金...")
    north = fetch_northbound_flow()
    time.sleep(1)

    log.info("    获取融资融券...")
    margin = fetch_margin_data()
    time.sleep(1)

    log.info("    获取涨跌停数据...")
    limit_pool = fetch_limit_pool()

    # 技术面点位
    levels = fetch_today_index_levels(indices)

    # 生成各部分
    tomorrow_date = _get_tomorrow_date()
    weekday = _get_weekday()

    macro_calendar = _generate_macro_calendar()
    capital_flow = _generate_capital_flow_section(north, margin, limit_pool)
    technical = _generate_technical_section(levels)
    strategy = _generate_strategy_section(levels)
    risks = _generate_risk_alerts(indices, limit_pool)

    return {
        "date": tomorrow_date,
        "weekday": weekday,
        "macro_calendar": macro_calendar,
        "capital_flow": capital_flow,
        "technical_analysis": technical,
        "strategy": strategy,
        "risk_alerts": risks,
    }
