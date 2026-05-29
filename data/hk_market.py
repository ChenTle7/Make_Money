"""港股市场数据获取与分析"""
import akshare as ak
import logging
import time

log = logging.getLogger(__name__)

# 港股关键词（用于过滤新闻）
HK_KEYWORDS = ["港股", "恒生", "南向", "港股通", "H股", "港元", "港币",
               "腾讯", "阿里", "美团", "小米", "比亚迪", "中芯"]


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
                    "change": float(row["涨跌额"]),
                    "change_pct": float(row["涨跌幅"]),
                    "open": float(row["今开"]),
                    "high": float(row["最高"]),
                    "low": float(row["最低"]),
                    "prev_close": float(row["昨收"]),
                })
    except Exception as e:
        log.warning(f"港股指数获取失败: {e}")
    return result


def fetch_hk_breadth_and_movers() -> dict:
    """获取全市场涨跌数据，返回市场宽度 + 涨跌前5"""
    result = {
        "total": 0, "up": 0, "down": 0, "flat": 0,
        "up_pct": 0, "limit_up": 0, "limit_down": 0,
        "top_gainers": [], "top_losers": [],
    }
    try:
        df = ak.stock_hk_spot()
        if df is None or len(df) == 0:
            return result

        # 清理数据
        df = df.copy()
        df["涨跌幅"] = df["涨跌幅"].astype(str).str.replace("%", "").str.strip()
        df["涨跌幅"] = df["涨跌幅"].replace(["", "nan", "None", "-"], "0")
        df["涨跌幅"] = df["涨跌幅"].astype(float)
        df["成交额"] = df["成交额"].astype(str).str.replace(",", "").str.strip()
        df["成交额"] = df["成交额"].replace(["", "nan", "None", "-"], "0")
        df["成交额"] = df["成交额"].astype(float)

        # 过滤掉成交额过小的（低于100万港元，可能是仙股或停牌）
        df_active = df[df["成交额"] > 1_000_000].copy()

        # 市场宽度
        result["total"] = len(df_active)
        result["up"] = int((df_active["涨跌幅"] > 0.01).sum())
        result["down"] = int((df_active["涨跌幅"] < -0.01).sum())
        result["flat"] = result["total"] - result["up"] - result["down"]
        if result["total"] > 0:
            result["up_pct"] = round(result["up"] / result["total"] * 100, 1)

        # 涨跌停（港股无涨跌停，但可以标记极端涨跌）
        result["limit_up"] = int((df_active["涨跌幅"] >= 10).sum())
        result["limit_down"] = int((df_active["涨跌幅"] <= -10).sum())

        # 涨幅前5（成交额>500万，排除极端小盘）
        df_liquid = df_active[df_active["成交额"] > 5_000_000].copy()
        df_sorted = df_liquid.sort_values("涨跌幅", ascending=False)

        for _, row in df_sorted.head(5).iterrows():
            result["top_gainers"].append({
                "code": str(row["代码"]),
                "name": str(row["中文名称"]),
                "price": float(row["最新价"]),
                "change_pct": round(float(row["涨跌幅"]), 2),
                "volume": float(row["成交量"]),
                "amount": float(row["成交额"]),
            })

        # 跌幅前5
        for _, row in df_sorted.tail(5).iloc[::-1].iterrows():
            result["top_losers"].append({
                "code": str(row["代码"]),
                "name": str(row["中文名称"]),
                "price": float(row["最新价"]),
                "change_pct": round(float(row["涨跌幅"]), 2),
                "volume": float(row["成交量"]),
                "amount": float(row["成交额"]),
            })

    except Exception as e:
        log.warning(f"港股全市场数据获取失败: {e}")

    return result


def fetch_hk_news() -> list:
    """获取港股相关新闻"""
    news_items = []

    # 财联社快讯
    try:
        df = ak.stock_news_main_cx()
        if df is not None:
            for _, row in df.iterrows():
                summary = str(row.get("summary", ""))
                for kw in HK_KEYWORDS:
                    if kw in summary:
                        news_items.append({
                            "title": summary[:100],
                            "source": "财联社",
                            "tag": str(row.get("tag", "")),
                        })
                        break
    except Exception as e:
        log.warning(f"财联社新闻获取失败: {e}")

    time.sleep(0.5)

    # 热门港股个股新闻（取前3只热门股）
    hot_stocks = [("00700", "腾讯"), ("09988", "阿里"), ("03690", "美团")]
    for code, name in hot_stocks:
        try:
            df = ak.stock_news_em(symbol=code)
            if df is not None and len(df) > 0:
                for _, row in df.head(2).iterrows():
                    title = str(row.get("新闻标题", ""))
                    if title and len(title) > 5:
                        news_items.append({
                            "title": title[:100],
                            "source": str(row.get("文章来源", "")),
                            "tag": name,
                        })
        except Exception:
            pass
        time.sleep(0.3)

    # 去重
    seen = set()
    unique_news = []
    for item in news_items:
        key = item["title"][:30]
        if key not in seen:
            seen.add(key)
            unique_news.append(item)

    return unique_news[:8]


def _generate_commentary(indices: list, breadth: dict, news: list) -> str:
    """基于规则生成市场评论"""
    parts = []

    # 指数表现
    for idx in indices:
        if idx["code"] == "HSI":
            direction = "上涨" if idx["change_pct"] > 0 else "下跌"
            parts.append(f"恒生指数{direction}{abs(idx['change_pct']):.2f}%至{idx['close']:.0f}点")
        elif idx["code"] == "HSTECH":
            direction = "涨" if idx["change_pct"] > 0 else "跌"
            parts.append(f"恒生科技{direction}{abs(idx['change_pct']):.2f}%")

    # 市场宽度
    up_pct = breadth.get("up_pct", 50)
    if up_pct > 60:
        parts.append(f"市场偏强，上涨个股占比{up_pct}%")
    elif up_pct < 40:
        parts.append(f"市场偏弱，仅{up_pct}%个股上涨")
    else:
        parts.append(f"市场分化，上涨占比{up_pct}%")

    # 大涨大跌
    if breadth.get("limit_up", 0) > 3:
        parts.append(f"大涨超10%个股{breadth['limit_up']}只，赚钱效应较好")
    if breadth.get("limit_down", 0) > 3:
        parts.append(f"大跌超10%个股{breadth['limit_down']}只，注意风险")

    # 涨幅前5归因
    gainers = breadth.get("top_gainers", [])
    if gainers:
        names = "、".join([g["name"] for g in gainers[:3]])
        parts.append(f"领涨：{names}")

    losers = breadth.get("top_losers", [])
    if losers:
        names = "、".join([l["name"] for l in losers[:3]])
        parts.append(f"领跌：{names}")

    return "。".join(parts) + "。" if parts else "暂无港股市场数据。"


def generate_hk_market_summary() -> dict:
    """生成港股市场总结数据"""
    log.info("    获取港股指数...")
    indices = fetch_hk_indices()

    log.info("    获取港股全市场数据（可能需要30-60秒）...")
    breadth = fetch_hk_breadth_and_movers()

    log.info("    获取港股新闻...")
    news = fetch_hk_news()

    commentary = _generate_commentary(indices, breadth, news)

    return {
        "indices": indices,
        "breadth": breadth,
        "news": news,
        "commentary": commentary,
    }
