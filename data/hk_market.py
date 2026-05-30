"""港股市场板块分析"""
import akshare as ak
import logging
import time

log = logging.getLogger(__name__)

# ============================================================
# 板块定义：每个板块含代表个股 + 关键词（用于新闻匹配）
# ============================================================
HK_SECTORS = {
    "互联网科技": {
        "stocks": [
            ("00700", "腾讯"), ("09988", "阿里巴巴"), ("03690", "美团"),
            ("09999", "网易"), ("01810", "小米"), ("09618", "京东"),
        ],
        "keywords": ["互联网", "科技", "AI", "人工智能", "云计算", "电商", "游戏"],
    },
    "医疗健康": {
        "stocks": [
            ("02269", "药明生物"), ("01093", "石药集团"),
            ("06160", "百济神州"), ("01177", "中国生物制药"),
        ],
        "keywords": ["医药", "医疗", "创新药", "生物医药", "CXO", "器械", "集采"],
    },
    "消费板块": {
        "stocks": [
            ("02020", "安踏体育"), ("02331", "李宁"), ("09633", "农夫山泉"),
            ("06862", "海底捞"), ("01458", "周黑鸭"),
        ],
        "keywords": ["消费", "零售", "餐饮", "食品", "白酒", "消费复苏"],
    },
    "金融地产": {
        "stocks": [
            ("01299", "友邦保险"), ("02318", "中国平安"),
            ("00005", "汇丰控股"), ("03968", "招商银行"),
            ("02007", "碧桂园"), ("01109", "华润置地"),
        ],
        "keywords": ["地产", "房地产", "房贷", "房企", "楼市", "保险", "港股通"],
    },
    "新能源汽车": {
        "stocks": [
            ("01211", "比亚迪"), ("09868", "小鹏汽车"), ("02015", "理想汽车"),
            ("09866", "蔚来"), ("02333", "长城汽车"),
        ],
        "keywords": ["新能源", "电动车", "汽车", "电池", "锂电", "自动驾驶"],
    },
    "半导体硬件": {
        "stocks": [
            ("00981", "中芯国际"), ("01810", "小米"), ("02382", "舜宇光学"),
            ("00285", "比亚迪电子"),
        ],
        "keywords": ["半导体", "芯片", "晶圆", "光学", "硬件", "华为"],
    },
}


def fetch_hk_indices() -> list:
    """获取主要港股指数"""
    target_codes = {"HSI": "恒生指数", "HSCEI": "国企指数", "HSTECH": "恒生科技指数"}
    result = []
    try:
        df = ak.stock_hk_index_spot_sina()
        for _, row in df.iterrows():
            code = str(row.get("代码", ""))
            if code in target_codes:
                result.append({
                    "code": code,
                    "name": target_codes[code],
                    "close": float(row["最新价"]),
                    "change_pct": float(row["涨跌幅"]),
                })
    except Exception as e:
        log.warning(f"港股指数获取失败: {e}")
    return result


def _fetch_stock_daily(code: str, days: int = 21) -> dict:
    """获取单只港股日线数据，返回今日/5日/20日涨跌幅"""
    try:
        df = ak.stock_hk_daily(symbol=code, adjust="qfq")
        if df is None or len(df) < 2:
            return None
        close = df["close"].astype(float)
        today = float(close.iloc[-1])
        yesterday = float(close.iloc[-2])
        today_chg = round((today - yesterday) / yesterday * 100, 2)

        chg_5d = 0
        if len(close) >= 6:
            chg_5d = round((today - float(close.iloc[-6])) / float(close.iloc[-6]) * 100, 2)

        chg_20d = 0
        if len(close) >= 21:
            chg_20d = round((today - float(close.iloc[-21])) / float(close.iloc[-21]) * 100, 2)

        return {
            "price": today,
            "today_chg": today_chg,
            "chg_5d": chg_5d,
            "chg_20d": chg_20d,
        }
    except Exception:
        return None


def _analyze_sector(name: str, cfg: dict) -> dict:
    """分析单个板块"""
    stocks_data = []
    for code, stock_name in cfg["stocks"]:
        data = _fetch_stock_daily(code)
        if data:
            data["code"] = code
            data["name"] = stock_name
            stocks_data.append(data)
        time.sleep(0.3)

    if not stocks_data:
        return None

    # 板块平均涨跌幅
    avg_today = round(sum(s["today_chg"] for s in stocks_data) / len(stocks_data), 2)
    avg_5d = round(sum(s["chg_5d"] for s in stocks_data) / len(stocks_data), 2)
    avg_20d = round(sum(s["chg_20d"] for s in stocks_data) / len(stocks_data), 2)

    # 排序
    stocks_data.sort(key=lambda x: x["today_chg"], reverse=True)
    best = stocks_data[0]
    worst = stocks_data[-1]

    return {
        "name": name,
        "avg_today": avg_today,
        "avg_5d": avg_5d,
        "avg_20d": avg_20d,
        "best": best,
        "worst": worst,
        "stocks": stocks_data,
    }


def _is_valid_news(title: str) -> bool:
    """过滤低质量新闻"""
    if not title or len(title) < 10:
        return False
    # 去掉疑问句
    if title.endswith("？") or title.endswith("?"):
        return False
    if any(kw in title for kw in ["如何", "为何", "能否", "是否", "怎样", "怎么办"]):
        return False
    # 去掉数据通专享前缀
    if "数据通用户提前专享" in title:
        return False
    # 去掉无关内容
    blacklist = ["爱泼斯坦", "生日贺信", "下流", "丑闻", "绯闻"]
    if any(kw in title for kw in blacklist):
        return False
    return True


def _is_sector_relevant(title: str, keywords: list) -> bool:
    """检查新闻是否与板块真正相关"""
    # 宽泛词需要搭配具体语境才算命中
    broad_words = {
        "消费": ["大消费", "消费股", "消费板块", "消费复苏", "消费升级", "消费品"],
        "利率": ["降息", "加息", "利率决议", "LPR"],
        "保险": ["保险", "险资", "保费"],
    }

    effective_keywords = []
    for kw in keywords:
        if kw in broad_words:
            # 宽泛词：需命中具体短语
            if any(phrase in title for phrase in broad_words[kw]):
                effective_keywords.append(kw)
        else:
            if kw in title:
                effective_keywords.append(kw)

    if len(effective_keywords) >= 2:
        return True
    if len(effective_keywords) == 1:
        # 排除市场播报类内容
        market_reports = ["港股收盘", "A股", "三大指数", "科创50", "涨停", "跌停",
                         "股指高开", "集体收高", "集体收低"]
        if any(kw in title for kw in market_reports):
            return False
        return True
    return False


def _clean_title(title: str) -> str:
    """清理新闻标题"""
    # 去掉前缀标签
    for prefix in ["【本文系数据通用户提前专享】", "【数据通】", "【】"]:
        title = title.replace(prefix, "")
    return title.strip()


# 跨板块已匹配的新闻（避免重复）
_global_seen_news: set = set()


def _fetch_sector_news(sector_name: str, keywords: list, stocks: list) -> list:
    """获取板块相关新闻（多来源，过滤低质量）"""
    global _global_seen_news
    news = []
    seen_titles = set()

    # 来源1：财联社快讯（关键词匹配 + 板块相关性检查）
    try:
        df = ak.stock_news_main_cx()
        if df is not None:
            for _, row in df.iterrows():
                summary = str(row.get("summary", ""))
                title = _clean_title(summary)
                if not _is_valid_news(title):
                    continue
                if title in _global_seen_news:
                    continue
                if not _is_sector_relevant(title, keywords):
                    continue
                seen_titles.add(title)
                _global_seen_news.add(title)
                news.append({"title": title, "source": "财联社"})
    except Exception:
        pass

    # 来源2：东方财富个股新闻（每只股票取最新1条，速度快约0.05s/只）
    for code, stock_name in stocks[:3]:  # 每板块取前3只
        try:
            df = ak.stock_news_em(symbol=code)
            if df is not None and len(df) > 0:
                row = df.iloc[0]
                title = _clean_title(str(row.get("新闻标题", "")))
                source = str(row.get("文章来源", "东方财富"))
                if title and title not in seen_titles and title not in _global_seen_news and _is_valid_news(title):
                    seen_titles.add(title)
                    _global_seen_news.add(title)
                    news.append({"title": title, "source": source})
        except Exception:
            pass
        time.sleep(0.1)

    return news[:5]


def _find_stock_news(stock_name: str, code: str, sector_news_list: list) -> str:
    """从板块新闻中找到与特定个股相关的新闻"""
    if not sector_news_list:
        return ""
    # 优先匹配个股名称或代码
    for n in sector_news_list:
        title = n["title"]
        if stock_name in title or code in title:
            return title
    # 没有精确匹配时，返回板块第一条新闻（板块相关新闻也能说明原因）
    return sector_news_list[0]["title"] if sector_news_list else ""


def _describe_sector_trends(sectors: list, sector_news: dict) -> list:
    """描述板块间走势分化（只陈述事实，不做无依据的因果推断）"""
    patterns = []
    sector_map = {s["name"]: s for s in sectors}

    # 找出走势明显强/弱的板块
    strong = [s for s in sectors if s["avg_5d"] > 5]
    weak = [s for s in sectors if s["avg_5d"] < -3]

    # 强势板块：结合新闻说明为什么强
    for s in strong:
        best = s["best"]
        news_match = _find_stock_news(best["name"], best["code"],
                                       sector_news.get(s["name"], []))
        if news_match:
            short_news = news_match[:40] + ("..." if len(news_match) > 40 else "")
            patterns.append(
                f"{s['name']}近期偏强，近5日累计{s['avg_5d']:+.2f}%，"
                f"{best['name']}领涨，关联消息：{short_news}"
            )
        else:
            patterns.append(
                f"{s['name']}近期偏强，近5日累计{s['avg_5d']:+.2f}%"
            )

    # 弱势板块：结合新闻说明为什么弱
    for s in weak:
        worst = s["worst"]
        news_match = _find_stock_news(worst["name"], worst["code"],
                                       sector_news.get(s["name"], []))
        if news_match:
            short_news = news_match[:40] + ("..." if len(news_match) > 40 else "")
            patterns.append(
                f"{s['name']}近期偏弱，近5日累计{s['avg_5d']:+.2f}%，"
                f"{worst['name']}领跌，关联消息：{short_news}"
            )
        else:
            patterns.append(
                f"{s['name']}近期偏弱，近5日累计{s['avg_5d']:+.2f}%"
            )

    return patterns


def _generate_commentary(sectors: list, indices: list, sector_news: dict) -> str:
    """生成市场深度评论"""
    parts = []

    # 1. 指数概览
    for idx in indices:
        if idx["code"] == "HSI":
            d = "涨" if idx["change_pct"] > 0 else "跌"
            parts.append(f"恒指{d}{abs(idx['change_pct']):.2f}%至{idx['close']:.0f}点")
        elif idx["code"] == "HSTECH":
            d = "涨" if idx["change_pct"] > 0 else "跌"
            parts.append(f"恒生科技{d}{abs(idx['change_pct']):.2f}%")

    if not sectors:
        return "。".join(parts) + "。" if parts else ""

    sectors_sorted = sorted(sectors, key=lambda x: x["avg_today"], reverse=True)

    # 2. 领涨板块分析
    top = sectors_sorted[0]
    if top["avg_today"] > 0:
        best = top["best"]
        news_match = _find_stock_news(best["name"], best["code"],
                                       sector_news.get(top["name"], []))
        if news_match:
            # 截取关键信息（不超过50字）
            short_news = news_match[:50] + ("..." if len(news_match) > 50 else "")
            parts.append(
                f"{top['name']}领涨（{top['avg_today']:+.2f}%），"
                f"{best['name']}涨{best['today_chg']:+.2f}%带动板块，"
                f"消息面上：{short_news}"
            )
        else:
            parts.append(
                f"{top['name']}领涨（{top['avg_today']:+.2f}%），"
                f"其中{best['name']}涨{best['today_chg']:+.2f}%"
            )

    # 3. 领跌板块分析
    bottom = sectors_sorted[-1]
    if bottom["avg_today"] < 0:
        worst = bottom["worst"]
        news_match = _find_stock_news(worst["name"], worst["code"],
                                       sector_news.get(bottom["name"], []))
        if news_match:
            short_news = news_match[:50] + ("..." if len(news_match) > 50 else "")
            parts.append(
                f"{bottom['name']}领跌（{bottom['avg_today']:+.2f}%），"
                f"{worst['name']}跌{worst['today_chg']:+.2f}%拖累板块，"
                f"消息面上：{short_news}"
            )
        else:
            parts.append(
                f"{bottom['name']}领跌（{bottom['avg_today']:+.2f}%），"
                f"其中{worst['name']}跌{worst['today_chg']:+.2f}%"
            )

    # 4. 趋势反转检测（连续下跌后反弹 / 连续上涨后回调）
    for s in sectors:
        # 近5日大跌+今日反弹
        if s["avg_5d"] < -3 and s["avg_today"] > 1.5:
            parts.append(
                f"{s['name']}出现反弹信号：此前5日累计跌{s['avg_5d']:.2f}%，今日反弹{s['avg_today']:+.2f}%"
            )
        # 近5日大涨+今日回调
        elif s["avg_5d"] > 3 and s["avg_today"] < -1.5:
            parts.append(
                f"{s['name']}出现回调信号：此前5日累计涨{s['avg_5d']:.2f}%，今日回落{s['avg_today']:+.2f}%"
            )

    # 5. 板块走势分化（强势/弱势板块，结合新闻说明原因）
    trends = _describe_sector_trends(sectors, sector_news)
    parts.extend(trends)

    # 6. 全面下跌/上涨
    up_count = sum(1 for s in sectors if s["avg_today"] > 0)
    down_count = sum(1 for s in sectors if s["avg_today"] < 0)
    if up_count == len(sectors):
        parts.append("各板块全线飘红，市场整体偏强")
    elif down_count == len(sectors):
        parts.append("各板块全线走弱，市场情绪低迷")

    return "。".join(parts) + "。" if parts else ""


def generate_hk_market_summary() -> dict:
    """生成港股板块分析"""
    global _global_seen_news
    _global_seen_news = set()  # 每次运行重置

    # 1. 主要指数
    log.info("    获取港股指数...")
    indices = fetch_hk_indices()

    # 2. 板块分析（约20秒）
    log.info("    分析各板块（约20秒）...")
    sectors = []
    for name, cfg in HK_SECTORS.items():
        log.info(f"      {name}...")
        result = _analyze_sector(name, cfg)
        if result:
            sectors.append(result)

    # 3. 板块新闻
    log.info("    获取板块相关新闻（多来源）...")
    sector_news = {}
    for name, cfg in HK_SECTORS.items():
        news = _fetch_sector_news(name, cfg["keywords"], cfg["stocks"])
        if news:
            sector_news[name] = news

    # 4. 深度评论（结合新闻和趋势数据）
    commentary = _generate_commentary(sectors, indices, sector_news)

    return {
        "indices": indices,
        "sectors": sectors,
        "sector_news": sector_news,
        "commentary": commentary,
    }
