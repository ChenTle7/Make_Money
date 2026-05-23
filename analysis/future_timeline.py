"""未来重要事件时间轴 - 生成未来一个月内关键经济事件"""
import akshare as ak
import logging
import time
from urllib.parse import quote
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# 东方财富搜索URL模板
EM_SEARCH_URL = "https://so.eastmoney.com/news/s?keyword={}"

# 关键词→搜索词映射（用于生成搜索链接）
_KEYWORD_SEARCH = {
    "CPI": "CPI数据",
    "PPI": "PPI数据",
    "GDP": "GDP数据",
    "LPR": "LPR报价",
    "MLF": "MLF续作",
    "PMI": "PMI数据",
    "美联储": "美联储议息",
    "降息": "央行降息",
    "加息": "央行加息",
    "非农": "美国非农",
    "就业": "非农就业",
    "通胀": "美国CPI通胀",
    "央行": "央行货币政策",
    "利率": "利率调整",
    "制造业": "制造业PMI",
    "消费": "社会消费品零售",
}


def _get_news_urls() -> dict:
    """从财经简报中提取关键词→URL映射，用于事件链接"""
    mapping = {}
    try:
        df = ak.stock_info_cjzc_em()
        for _, row in df.head(300).iterrows():
            title = str(row.iloc[0]).strip()
            url = str(row.iloc[3]).strip() if len(row) > 3 else ""
            if not url or url == "nan" or len(title) < 4:
                continue
            for kw in _KEYWORD_SEARCH:
                if kw in title and kw not in mapping:
                    mapping[kw] = url
                    break
    except Exception as e:
        log.warning(f"获取新闻URL映射失败: {e}")
    return mapping


def _build_calendar_events() -> list:
    """构建未来30天的重要经济事件日历"""
    now = datetime.now()
    events = []

    for day_offset in range(1, 31):
        d = now + timedelta(days=day_offset)
        day = d.day
        month = d.month
        weekday = d.weekday()
        date_str = d.strftime("%m月%d日")
        weekday_str = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][weekday]

        # === 国内事件 ===

        # CPI/PPI发布（每月12日左右）
        if day == 12:
            events.append({
                "date": date_str,
                "weekday": weekday_str,
                "date_obj": d,
                "event": f"国家统计局发布{month}月CPI、PPI数据",
                "importance": "high",
                "keywords": ["CPI", "PPI"],
                "category": "经济数据",
            })

        # 经济数据密集发布期（每月15日）
        if day == 15:
            events.append({
                "date": date_str,
                "weekday": weekday_str,
                "date_obj": d,
                "event": f"统计局发布{month}月工业增加值、社零、固投等经济数据",
                "importance": "high",
                "keywords": ["制造业", "消费"],
                "category": "经济数据",
            })

        # GDP发布（1/4/7/10月17日）
        if day == 17 and month in [1, 4, 7, 10]:
            events.append({
                "date": date_str,
                "weekday": weekday_str,
                "date_obj": d,
                "event": f"统计局发布季度GDP数据",
                "importance": "critical",
                "keywords": ["GDP"],
                "category": "经济数据",
            })

        # MLF续作（每月15日附近）
        if day == 15:
            events.append({
                "date": date_str,
                "weekday": weekday_str,
                "date_obj": d,
                "event": "央行MLF续作（关注利率是否调整）",
                "importance": "critical",
                "keywords": ["MLF", "央行"],
                "category": "货币政策",
            })

        # LPR报价（每月20日）
        if day == 20:
            events.append({
                "date": date_str,
                "weekday": weekday_str,
                "date_obj": d,
                "event": "央行公布LPR报价",
                "importance": "critical",
                "keywords": ["LPR", "利率"],
                "category": "货币政策",
            })

        # PMI发布（每月最后一天）
        last_day = (d.replace(month=month % 12 + 1, day=1) - timedelta(days=1)).day
        if day == last_day:
            events.append({
                "date": date_str,
                "weekday": weekday_str,
                "date_obj": d,
                "event": f"统计局发布{month}月PMI数据",
                "importance": "high",
                "keywords": ["PMI", "制造业"],
                "category": "经济数据",
            })

        # === 海外事件 ===

        # 美联储议息会议（大约每6周一次，只取第一天）
        if month in [1, 3, 5, 6, 7, 9, 11, 12] and day == 17:
            events.append({
                "date": date_str,
                "weekday": weekday_str,
                "date_obj": d,
                "event": "美联储FOMC议息会议（关注利率决议）",
                "importance": "critical",
                "keywords": ["美联储", "降息"],
                "category": "海外央行",
            })

        # 美国非农（每月第一个周五）
        if weekday == 4 and 1 <= day <= 7:
            events.append({
                "date": date_str,
                "weekday": weekday_str,
                "date_obj": d,
                "event": f"美国{month}月非农就业数据发布",
                "importance": "high",
                "keywords": ["非农", "就业"],
                "category": "海外经济",
            })

        # 美国CPI（每月13日）
        if day == 13:
            events.append({
                "date": date_str,
                "weekday": weekday_str,
                "date_obj": d,
                "event": f"美国{month}月CPI数据发布",
                "importance": "high",
                "keywords": ["通胀"],
                "category": "海外经济",
            })

    events.sort(key=lambda x: x["date_obj"])
    return events


def _resolve_url(event: dict, url_map: dict) -> str:
    """为事件解析链接：优先匹配真实新闻，否则生成搜索链接"""
    # 先尝试从新闻中匹配真实URL
    for kw in event.get("keywords", []):
        if kw in url_map:
            return url_map[kw]
    # 兜底：用第一个关键词生成东方财富搜索链接
    kws = event.get("keywords", [])
    if kws:
        search_term = _KEYWORD_SEARCH.get(kws[0], kws[0])
        return EM_SEARCH_URL.format(quote(search_term))
    return ""


def generate_future_timeline(max_per_day: int = 3) -> list:
    """生成未来一个月的事件时间轴，按天分组

    Args:
        max_per_day: 每天最多显示几个事件

    Returns:
        list of dicts, 每个dict代表一天:
        [
            {
                "date": "06月15日",
                "weekday": "周日",
                "events": [
                    {"event": "...", "importance": "critical", "url": "...", "category": "..."},
                    ...
                ]
            },
            ...
        ]
    """
    log.info("  生成未来事件时间轴...")

    url_map = _get_news_urls()
    time.sleep(0.3)

    all_events = _build_calendar_events()

    # 为每个事件解析链接
    for evt in all_events:
        evt["url"] = _resolve_url(evt, url_map)

    # 按日期分组
    by_date = {}
    for evt in all_events:
        key = evt["date"]
        if key not in by_date:
            by_date[key] = {
                "date": evt["date"],
                "weekday": evt["weekday"],
                "events": [],
            }
        by_date[key]["events"].append({
            "event": evt["event"],
            "importance": evt["importance"],
            "url": evt["url"],
            "category": evt["category"],
        })

    # 每天最多 max_per_day 个事件，critical优先
    for day_data in by_date.values():
        evts = day_data["events"]
        evts.sort(key=lambda e: 0 if e["importance"] == "critical" else 1)
        day_data["events"] = evts[:max_per_day]

    # 按日期排序
    result = sorted(by_date.values(), key=lambda x: x["date"])
    total_events = sum(len(d["events"]) for d in result)
    log.info(f"  未来事件: {len(result)}天, 共{total_events}个事件")
    return result
