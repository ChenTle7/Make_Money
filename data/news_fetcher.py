"""新闻数据获取 - 三部分：要闻TOP10 + 国际市场动态 + 研报观点"""
import akshare as ak
import requests
import pandas as pd
import logging
import time
import re
from datetime import datetime

log = logging.getLogger(__name__)

# ============================================================
# Part 1: 今日要闻TOP10
# ============================================================

def _fetch_daily_briefs() -> list:
    """获取每日财经早知道/晚报（东方财富），含摘要和链接"""
    try:
        df = ak.stock_info_cjzc_em()
        items = []
        for _, row in df.iterrows():
            title = str(row.iloc[0]).strip()
            summary = str(row.iloc[1]).strip()
            time_str = str(row.iloc[2]).strip()
            url = str(row.iloc[3]).strip()
            # 只取今天和昨天的内容
            items.append({
                "title": title,
                "content": summary,
                "time": time_str,
                "source": "财经早知道",
                "url": url,
            })
        return items
    except Exception as e:
        log.warning(f"获取每日简报失败: {e}")
        return []


def _fetch_keyword_news(keywords: list, max_per_kw: int = 8) -> list:
    """按关键词获取东方财富新闻"""
    all_items = []
    for kw in keywords:
        try:
            df = ak.stock_news_em(symbol=kw)
            if df is None or len(df) == 0:
                continue
            cols = ["keyword", "title", "content", "time", "source", "url"]
            if len(df.columns) >= len(cols):
                df.columns = cols[:len(df.columns)]
            for _, row in df.head(max_per_kw).iterrows():
                all_items.append({
                    "title": str(row.get("title", "")).strip(),
                    "content": str(row.get("content", ""))[:300],
                    "time": str(row.get("time", "")),
                    "source": str(row.get("source", "东方财富")),
                    "url": str(row.get("url", "")),
                    "category": kw,
                })
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"获取关键词新闻({kw})失败: {e}")
    return all_items


def _fetch_hot_stock_news() -> list:
    """获取热门个股公告和重要新闻"""
    keywords = ["A股", "美股", "央行", "降息", "加息", "关税", "贸易",
                 "恒生", "港股通", "ETF", "北向资金", "融资融券"]
    return _fetch_keyword_news(keywords, max_per_kw=5)


def _deduplicate_news(items: list, max_items: int = 15) -> list:
    """去重并按相关性筛选"""
    seen = set()
    unique = []
    for item in items:
        title = item.get("title", "")
        if not title or len(title) < 5:
            continue
        # 简单去重：去掉完全相同或高度相似的标题
        key = re.sub(r'[^\w]', '', title[:15])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    # 优先保留有链接的、有详细内容的
    unique.sort(key=lambda x: (bool(x.get("url")), len(x.get("content", ""))), reverse=True)
    return unique[:max_items]


def fetch_top_news() -> list:
    """Part 1: 获取今日最重要的10条财经新闻"""
    log.info("  [Part1] 获取每日简报...")
    briefs = _fetch_daily_briefs()
    time.sleep(1)

    log.info("  [Part1] 获取热点新闻...")
    hot_news = _fetch_hot_stock_news()
    time.sleep(1)

    # 合并去重
    all_news = briefs + hot_news
    top10 = _deduplicate_news(all_news, max_items=12)

    log.info(f"  [Part1] 获取 {len(top10)} 条要闻")
    return top10


# ============================================================
# Part 2: 国际大盘经济动态
# ============================================================

def _fetch_sina_quote(symbol: str) -> dict:
    """获取新浪实时行情（通用）"""
    url = f"https://hq.sinajs.cn/list={symbol}"
    try:
        r = requests.get(url, timeout=10, headers={"Referer": "https://finance.sina.com.cn"})
        r.encoding = "gbk"
        line = r.text.strip()
        data_str = line.split('"')[1]
        parts = data_str.split(",")
        return {"raw": parts, "ok": True}
    except Exception:
        return {"ok": False}


def fetch_global_indices() -> list:
    """获取全球主要股指"""
    indices = [
        ("道琼斯", "int_dji", 1),
        ("标普500", "int_sp500", 1),
        ("纳斯达克", "int_nasdaq", 1),
        ("英国富时100", "b_FSSTI", 1),
        ("德国DAX", "int_dax", 1),
        ("法国CAC40", "int_fchi", 1),
        ("日经225", "int_nikkei", 1),
        ("韩国综合", "b_KOSPI", 1),
        ("恒生指数", "b_HSI", 1),
    ]
    results = []
    for name, symbol, _ in indices:
        data = _fetch_sina_quote(symbol)
        if data["ok"] and len(data["raw"]) >= 4:
            try:
                parts = data["raw"]
                price = float(parts[1])
                change = float(parts[2])
                change_pct = float(parts[3])
                results.append({
                    "name": name,
                    "price": f"{price:,.2f}",
                    "change": f"{change:+,.2f}",
                    "change_pct": f"{change_pct:+.2f}%",
                    "up": change_pct >= 0,
                })
            except (ValueError, IndexError):
                pass
        time.sleep(0.2)
    return results


def fetch_commodities() -> list:
    """获取商品期货价格"""
    items = [
        ("COMEX黄金", "hf_GC"),
        ("NYMEX原油", "hf_CL"),
        ("COMEX白银", "hf_SI"),
        ("LME铜", "hf_sCOPPER"),
    ]
    results = []
    for name, symbol in items:
        data = _fetch_sina_quote(symbol)
        if data["ok"] and len(data["raw"]) >= 5:
            try:
                parts = data["raw"]
                price = float(parts[0])
                prev = float(parts[7]) if len(parts) > 7 and parts[7] else price
                change_pct = round((price - prev) / prev * 100, 2) if prev else 0
                results.append({
                    "name": name,
                    "price": f"{price:,.2f}",
                    "change_pct": f"{change_pct:+.2f}%",
                    "up": change_pct >= 0,
                })
            except (ValueError, IndexError):
                pass
        time.sleep(0.2)
    return results


def fetch_forex() -> list:
    """获取外汇数据"""
    items = [
        ("美元/人民币", "fx_susdcny"),
        ("欧元/美元", "fx_seurusd"),
        ("美元/日元", "fx_susdjpy"),
    ]
    results = []
    for name, symbol in items:
        data = _fetch_sina_quote(symbol)
        if data["ok"] and len(data["raw"]) >= 3:
            try:
                parts = data["raw"]
                price = float(parts[1])
                results.append({
                    "name": name,
                    "price": f"{price:.4f}",
                })
            except (ValueError, IndexError):
                pass
        time.sleep(0.2)
    return results


def fetch_global_indicators() -> dict:
    """Part 2: 获取国际市场经济动态指标"""
    log.info("  [Part2] 获取全球股指...")
    indices = fetch_global_indices()
    time.sleep(1)

    log.info("  [Part2] 获取商品期货...")
    commodities = fetch_commodities()
    time.sleep(1)

    log.info("  [Part2] 获取外汇...")
    forex = fetch_forex()

    total = len(indices) + len(commodities) + len(forex)
    log.info(f"  [Part2] 获取 {total} 项指标")

    return {
        "indices": indices,
        "commodities": commodities,
        "forex": forex,
    }


# ============================================================
# Part 3: 知名投行研报与观点
# ============================================================

def fetch_research_reports(max_items: int = 12) -> list:
    """Part 3: 获取知名券商/投行研报"""
    log.info("  [Part3] 获取研报数据...")
    try:
        df = ak.stock_research_report_em(symbol="000001")
        # 只保留最近的研报
        cols = df.columns.tolist()
        items = []
        for _, row in df.head(max_items).iterrows():
            try:
                item = {
                    "title": str(row.iloc[3]).strip() if len(row) > 3 else "",
                    "stock_name": str(row.iloc[2]).strip() if len(row) > 2 else "",
                    "stock_code": str(row.iloc[1]).strip() if len(row) > 1 else "",
                    "broker": str(row.iloc[5]).strip() if len(row) > 5 else "",
                    "rating": str(row.iloc[4]).strip() if len(row) > 4 else "",
                    "date": str(row.iloc[-3]).strip() if len(row) > 3 else "",
                    "url": str(row.iloc[-1]).strip() if len(row) > 0 else "",
                }
                # 提取盈利预测
                if len(row) > 8:
                    item["eps_2026"] = str(row.iloc[8])
                if len(row) > 9:
                    item["pe_2026"] = str(row.iloc[9])
                items.append(item)
            except Exception:
                continue

        log.info(f"  [Part3] 获取 {len(items)} 份研报")
        return items
    except Exception as e:
        log.error(f"获取研报失败: {e}")
        return []


# ============================================================
# 汇总
# ============================================================

def fetch_all_news() -> dict:
    """获取全部三部分新闻"""
    top_news = fetch_top_news()
    time.sleep(1)

    global_indicators = fetch_global_indicators()
    time.sleep(1)

    reports = fetch_research_reports()

    return {
        "top_news": top_news,
        "global_indicators": global_indicators,
        "research_reports": reports,
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
