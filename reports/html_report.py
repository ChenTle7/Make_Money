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


def build_grid_doc(date_str: str, etf_analysis: list, tomorrow_watch: dict = None) -> str:
    """生成简易网格推荐文档（纯HTML片段，用于邮件内嵌和独立文件）"""
    # 按建议排序: 买入 > 持有 > 减仓 > 观望
    action_order = {"买入": 0, "持有": 1, "减仓": 2, "观望": 3}
    sorted_etfs = sorted(etf_analysis, key=lambda e: action_order.get(e.get("action", "观望"), 9))

    detail_cards = []

    for etf in sorted_etfs:
        levels = etf.get("levels", [])
        action = etf.get("action", "观望")
        action_color = {"买入": "#22C55E", "持有": "#3B82F6", "减仓": "#EF4444"}.get(action, "#94A3B8")
        change_pct = etf.get("change_pct", 0)
        change_color = "#EF4444" if change_pct >= 0 else "#22C55E"
        change_sign = "+" if change_pct >= 0 else ""

        # 网格档位行（差价模式）
        current = etf['current_price']
        grid_rows = ""
        for lv in levels:
            buy_diff = round(current - lv['buy_price'], 3)
            sell_diff = round(lv['sell_price'] - current, 3)
            grid_rows += f"""
        <tr style="color:#E2E8F0; font-size:13px;">
          <td style="padding:5px 10px; border-bottom:1px solid rgba(255,255,255,0.06); color:#94A3B8;">第{lv['grid_num']}格</td>
          <td style="padding:5px 10px; border-bottom:1px solid rgba(255,255,255,0.06); color:#22C55E; text-align:right;">-{buy_diff:.3f}</td>
          <td style="padding:5px 10px; border-bottom:1px solid rgba(255,255,255,0.06); color:#EF4444; text-align:right;">+{sell_diff:.3f}</td>
          <td style="padding:5px 10px; border-bottom:1px solid rgba(255,255,255,0.06); color:#CBD5E1; text-align:right;">{lv['shares']}</td>
          <td style="padding:5px 10px; border-bottom:1px solid rgba(255,255,255,0.06); color:#CBD5E1; text-align:right;">{lv['profit_per_trade']:.1f}</td>
        </tr>"""

        # 趋势数据
        def _pct_cell(label, pct):
            c = "#EF4444" if pct >= 0 else "#22C55E"
            s = "+" if pct >= 0 else ""
            return f'<td style="padding:4px 8px; color:{c}; font-size:13px;">{label}: {s}{pct:.1f}%</td>'

        trend_row = (
            _pct_cell("半年", etf.get("trend_6m_pct", 0))
            + _pct_cell("季度", etf.get("trend_3m_pct", 0))
            + _pct_cell("月度", etf.get("trend_1m_pct", 0))
            + _pct_cell("周度", etf.get("trend_1w_pct", 0))
        )

        reasoning = etf.get("reasoning", "")

        detail_cards.append(f"""
  <div style="background:rgba(255,255,255,0.04); border-radius:8px; padding:16px; margin-bottom:12px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
      <span style="font-weight:600; color:#F0F4F8; font-size:15px;">{etf['code']} {etf['name']}</span>
      <span style="background:{action_color}; color:#fff; padding:3px 12px; border-radius:4px; font-size:12px; font-weight:600;">{action}</span>
    </div>
    <table style="width:100%; border-collapse:collapse; margin-bottom:8px;">
      <tr style="color:#94A3B8; font-size:12px;">
        <td style="padding:4px 8px;">现价 {etf['current_price']:.3f} <span style="color:{change_color};">{change_sign}{change_pct:.2f}%</span></td>
        <td style="padding:4px 8px;">超卖 {etf.get('oversold_score', 0)}/10</td>
        <td style="padding:4px 8px;">信号 {etf.get('signal_strength', '中性')}</td>
      </tr>
      <tr>{trend_row}</tr>
    </table>
    <table style="width:100%; border-collapse:collapse; margin-bottom:10px;">
      <tr style="color:#94A3B8; font-size:12px; border-bottom:1px solid rgba(255,255,255,0.1);">
        <th style="padding:5px 10px; text-align:left;">网格</th>
        <th style="padding:5px 10px; text-align:right; color:#22C55E;">下跌-买入</th>
        <th style="padding:5px 10px; text-align:right; color:#EF4444;">上涨-卖出</th>
        <th style="padding:5px 10px; text-align:right;">股数</th>
        <th style="padding:5px 10px; text-align:right;">利润</th>
      </tr>{grid_rows}
    </table>
    <p style="color:#CBD5E1; font-size:13px; line-height:1.6; margin:0;">{reasoning}</p>
  </div>""")

    # 明日关注部分
    tomorrow_html = ""
    if tomorrow_watch:
        tw = tomorrow_watch
        # 宏观事件
        cal_items = ""
        for evt in tw.get("macro_calendar", [])[:5]:
            type_color = "#EF4444" if evt.get("type") == "确定" else "#EAB308"
            cal_items += f"""
        <tr style="color:#E2E8F0; font-size:13px;">
          <td style="padding:4px 8px; border-bottom:1px solid rgba(255,255,255,0.06); color:#94A3B8;">{evt.get('time','')}</td>
          <td style="padding:4px 8px; border-bottom:1px solid rgba(255,255,255,0.06);">{evt.get('event','')}</td>
          <td style="padding:4px 8px; border-bottom:1px solid rgba(255,255,255,0.06); color:{type_color};">{evt.get('type','')}</td>
          <td style="padding:4px 8px; border-bottom:1px solid rgba(255,255,255,0.06);">{evt.get('importance','')}</td>
        </tr>"""

        # 资金动向
        capital_items = ""
        for analysis in tw.get("capital_flow", {}).get("analysis", [])[:3]:
            capital_items += f'<p style="color:#CBD5E1; font-size:13px; line-height:1.6; margin:4px 0;">{analysis}</p>'

        # 技术面
        tech_items = ""
        for item in tw.get("technical_analysis", [])[:3]:
            tech_items += f'<p style="color:#CBD5E1; font-size:13px; line-height:1.6; margin:4px 0;">{item}</p>'

        # 操作策略
        strategy = tw.get("strategy", {})
        mood = strategy.get("mood", "")
        mood_color = {"偏多": "#EF4444", "偏空": "#22C55E"}.get(mood, "#EAB308")
        strategy_rows = ""
        for style_name, style_key, color in [("激进型", "aggressive", "#EF4444"), ("稳健型", "moderate", "#EAB308"), ("保守型", "conservative", "#22C55E")]:
            s = strategy.get(style_key, {})
            strategy_rows += f"""
        <tr style="color:#E2E8F0; font-size:13px;">
          <td style="padding:5px 8px; border-bottom:1px solid rgba(255,255,255,0.06); color:{color};">{style_name}</td>
          <td style="padding:5px 8px; border-bottom:1px solid rgba(255,255,255,0.06);">{s.get('position','')}</td>
          <td style="padding:5px 8px; border-bottom:1px solid rgba(255,255,255,0.06); color:#CBD5E1; font-size:12px;">{s.get('advice','')}</td>
        </tr>"""

        tomorrow_html = f"""
  <div style="background: linear-gradient(135deg, #0F172A, #1E293B); border-radius: 12px; padding: 24px; color: #F0F4F8; margin-bottom: 16px;">
    <h2 style="margin: 0 0 4px; color: #F0F4F8;">明日关注</h2>
    <p style="margin: 0 0 16px; color: #64748B; font-size: 13px;">{tw.get('date','')} ({tw.get('weekday','')})</p>

    <h3 style="margin: 0 0 8px; color: #F0F4F8; font-size: 14px;">宏观事件</h3>
    <table style="width:100%; border-collapse:collapse; margin-bottom:14px;">
      <tr style="color:#94A3B8; font-size:12px; border-bottom:1px solid rgba(255,255,255,0.1);">
        <th style="padding:4px 8px; text-align:left;">时间</th>
        <th style="padding:4px 8px; text-align:left;">事件</th>
        <th style="padding:4px 8px; text-align:left;">类型</th>
        <th style="padding:4px 8px; text-align:left;">重要性</th>
      </tr>{cal_items}
    </table>

    <h3 style="margin: 0 0 8px; color: #F0F4F8; font-size: 14px;">资金动向</h3>
    {capital_items}

    <h3 style="margin: 14px 0 8px; color: #F0F4F8; font-size: 14px;">技术面</h3>
    {tech_items}

    <h3 style="margin: 14px 0 8px; color: #F0F4F8; font-size: 14px;">操作策略</h3>
    <p style="margin: 0 0 8px; color:#94A3B8; font-size:13px;">市场情绪：<span style="color:{mood_color}; font-weight:600;">{mood}</span></p>
    <table style="width:100%; border-collapse:collapse;">
      <tr style="color:#94A3B8; font-size:12px; border-bottom:1px solid rgba(255,255,255,0.1);">
        <th style="padding:5px 8px; text-align:left;">类型</th>
        <th style="padding:5px 8px; text-align:left;">仓位</th>
        <th style="padding:5px 8px; text-align:left;">建议</th>
      </tr>{strategy_rows}
    </table>
  </div>"""

    html = f"""<div style="font-family: -apple-system, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto;">
  {tomorrow_html}
  <div style="background: linear-gradient(135deg, #0F172A, #1E293B); border-radius: 12px; padding: 24px; color: #F0F4F8;">
    <h2 style="margin: 0 0 4px; color: #F0F4F8;">网格交易推荐</h2>
    <p style="margin: 0 0 16px; color: #64748B; font-size: 13px;">{date_str}</p>
    {''.join(detail_cards)}
  </div>
  <p style="color: #64748B; font-size: 12px; text-align: center; margin-top: 12px;">数据仅供参考，不构成投资建议</p>
</div>"""

    # 保存独立文件
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    grid_path = REPORT_DIR / f"grid-{date_str}.html"
    grid_path.write_text(html, encoding="utf-8")
    return html
