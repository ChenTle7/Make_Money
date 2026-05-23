"""HTML报告构建"""
import shutil
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

from config import TEMPLATE_DIR, REPORT_DIR


def build_report(
    date_str: str,
    indices: dict,
    market_commentary: str,
    top_news: list,
    global_indicators: dict,
    research_reports: list,
    tomorrow_watch: dict,
    etf_analysis: list,
    generate_time: str = None,
    future_timeline: list = None,
) -> Path:
    """构建并保存每日HTML报告"""
    if generate_time is None:
        generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 构建导航和推荐数据
    recommendations = []
    top_picks = []
    for etf in etf_analysis:
        action = etf.get("action", "观望")
        action_class = {"买入": "buy", "持有": "hold", "减仓": "sell"}.get(action, "wait")
        name_short = etf["name"].replace("ETF", "").replace("通", "")
        recommendations.append({
            "code": etf["code"],
            "name_short": name_short,
            "name_full": etf["name"],
            "change_pct": etf.get("change_pct", 0),
            "action_class": action_class,
        })
        if action in ("买入", "持有") and etf.get("confidence", 0) >= 3:
            top_picks.append({
                "code": etf["code"],
                "name": etf["name"],
                "action": action,
                "confidence": etf.get("confidence", 3),
                "reason_short": etf.get("reasoning", "")[:50],
            })

    # 按信心度排序
    top_picks.sort(key=lambda x: x["confidence"], reverse=True)

    # 渲染
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("template.html")
    html = template.render(
        date=date_str,
        indices=indices,
        market_commentary=market_commentary,
        top_news=top_news,
        global_indicators=global_indicators,
        research_reports=research_reports,
        tomorrow_watch=tomorrow_watch,
        recommendations=recommendations,
        top_picks=top_picks,
        etf_analysis=etf_analysis,
        generate_time=generate_time,
        future_timeline=future_timeline or [],
    )

    # 保存
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{date_str}.html"
    report_path.write_text(html, encoding="utf-8")

    # 同时复制为 latest.html
    latest_path = REPORT_DIR / "latest.html"
    shutil.copy2(report_path, latest_path)

    return report_path
