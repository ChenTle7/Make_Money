"""图表生成 - 网格交易专属可视化"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import pandas as pd
import numpy as np
import base64
from io import BytesIO

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun']
plt.rcParams['axes.unicode_minus'] = False

# 颜色 - 高对比度暗色主题
RED = '#FF5555'
GREEN = '#34D399'
GOLD = '#FFD700'
BLUE = '#60A5FA'
BG_COLOR = '#0F1B2D'
CARD_COLOR = '#1A2A40'
TEXT_COLOR = '#F0F4F8'
GRID_COLOR = '#2A3A4E'
MUTED = '#B0C4DE'


def _fig_to_base64(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                facecolor=BG_COLOR, edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def _setup_ax(ax):
    ax.set_facecolor(BG_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(GRID_COLOR)
    ax.spines['left'].set_color(GRID_COLOR)
    ax.grid(True, alpha=0.2, color=GRID_COLOR)


def _label_bg(ax, x, y, text, fontsize=10, color=TEXT_COLOR, bg=BG_COLOR,
              bold=False, edgecolor=None, ha='center', va='center', transform=None, **kwargs):
    """带背景的文字标签，确保在任何背景上可读"""
    kw = dict(fontsize=fontsize, color=color, ha=ha, va=va,
              bbox=dict(boxstyle='round,pad=0.25', facecolor=bg, edgecolor=edgecolor or 'none',
                        alpha=0.88, linewidth=0.8))
    if bold:
        kw['fontweight'] = 'bold'
    if transform:
        kw['transform'] = transform
    kw.update(kwargs)
    ax.text(x, y, text, **kw)


def generate_etf_chart(
    code: str,
    name: str,
    df_daily: pd.DataFrame,
    df_minute: pd.DataFrame,
    grid_params: dict,
) -> str:
    """网格交易专属图表：网格地图 + 振幅趋势 + 周期走势"""
    fig = plt.figure(figsize=(14, 10), facecolor=BG_COLOR)
    gs = GridSpec(2, 2, height_ratios=[1.2, 1], width_ratios=[1, 1],
                  hspace=0.3, wspace=0.25, figure=fig)

    latest = df_daily.iloc[-1]
    prev = df_daily.iloc[-2] if len(df_daily) > 1 else latest
    chg = round((latest["close"] - prev["close"]) / prev["close"] * 100, 2)
    sign = "+" if chg >= 0 else ""

    # === 左上: 网格地图 ===
    ax_grid = fig.add_subplot(gs[0, :])
    _setup_ax(ax_grid)
    _draw_grid_map(ax_grid, grid_params, latest["close"], name, code, chg, sign)

    # === 左下: 振幅趋势 ===
    ax_amp = fig.add_subplot(gs[1, 0])
    _setup_ax(ax_amp)
    _draw_amplitude(ax_amp, df_daily)

    # === 右下: 周期走势 ===
    ax_trend = fig.add_subplot(gs[1, 1])
    _setup_ax(ax_trend)
    _draw_sparklines(ax_trend, df_daily)

    return _fig_to_base64(fig)


def _draw_grid_map(ax, grid_params, current_price, name, code, chg, sign):
    """绘制网格地图 - 价格阶梯 + 档位线"""
    levels = grid_params.get("levels", []) if isinstance(grid_params, dict) else []
    spacing_pct = grid_params.get("spacing_pct", 0) if isinstance(grid_params, dict) else 0

    # 标题
    title_color = RED if chg >= 0 else GREEN
    ax.set_title(f"{name} ({code})  {current_price:.3f}  {sign}{chg}%  |  网格间距 {spacing_pct}%",
                 fontsize=13, color=title_color, loc='left', pad=10, fontweight='bold')

    if not levels:
        ax.text(0.5, 0.5, "暂无网格数据", transform=ax.transAxes,
                ha='center', va='center', fontsize=14, color=MUTED)
        ax.set_xticks([])
        ax.set_yticks([])
        return

    # 收集所有价格确定Y轴范围（加大padding防止遮挡）
    all_prices = [current_price]
    for lv in levels:
        all_prices.append(lv["buy_price"])
        all_prices.append(lv["sell_price"])
    price_range = max(all_prices) - min(all_prices)
    padding = max(price_range * 0.12, current_price * 0.008)
    y_min = min(all_prices) - padding
    y_max = max(all_prices) + padding
    ax.set_ylim(y_min, y_max)
    ax.set_xlim(0, 1)

    ax.set_xticks([])
    ax.spines['bottom'].set_visible(False)

    for lv in levels:
        buy = lv["buy_price"]
        sell = lv["sell_price"]
        ax.axhspan(buy, sell, alpha=0.08, color=BLUE)
        ax.axhline(y=buy, color=GREEN, linewidth=1.5, linestyle='-', alpha=0.85)
        ax.axhline(y=sell, color=RED, linewidth=1.5, linestyle='-', alpha=0.85)

        y_mid = (buy + sell) / 2
        profit = lv.get("profit_per_trade", 0)
        shares = lv.get("shares", 0)

        _label_bg(ax, 0.01, buy, f"B{lv['grid_num']} {buy:.3f}",
                  fontsize=10, color=GREEN, bold=True, ha='left', va='center')

        _label_bg(ax, 0.99, sell, f"S{lv['grid_num']} {sell:.3f}",
                  fontsize=10, color=RED, bold=True, ha='right', va='center')

        _label_bg(ax, 0.5, y_mid, f"{shares}股 +{profit:.0f}元",
                  fontsize=9, color=MUTED, ha='center', va='center')

    if levels:
        lowest_buy = min(lv["buy_price"] for lv in levels)
        highest_sell = max(lv["sell_price"] for lv in levels)
        if current_price < lowest_buy:
            _label_bg(ax, 0.98, 0.05, "低于最低买入档",
                      fontsize=10, color=GREEN, ha='right', transform=ax.transAxes)
        elif current_price > highest_sell:
            _label_bg(ax, 0.98, 0.05, "高于最高卖出档",
                      fontsize=10, color=RED, ha='right', transform=ax.transAxes)


def _draw_amplitude(ax, df_daily):
    """绘制近30天振幅趋势"""
    ax.set_title("近期振幅 (日高-低)/低", fontsize=11, color=TEXT_COLOR, loc='left', pad=8)

    n = min(len(df_daily), 30)
    df = df_daily.tail(n).copy().reset_index(drop=True)

    if len(df) < 3:
        ax.text(0.5, 0.5, "数据不足", transform=ax.transAxes, ha='center', va='center',
                fontsize=12, color=MUTED)
        ax.set_xticks([])
        return

    amp = ((df["high"] - df["low"]) / df["low"] * 100).values
    mean_amp = np.mean(amp)

    colors = [RED if amp[i] >= mean_amp else GREEN for i in range(len(amp))]
    ax.bar(range(len(amp)), amp, color=colors, width=0.7, alpha=0.75)
    ax.axhline(y=mean_amp, color=GOLD, linewidth=1.2, linestyle='--', alpha=0.8)

    # 均值标注 - 带背景
    _label_bg(ax, len(amp) - 0.5, mean_amp, f"均值 {mean_amp:.2f}%",
              fontsize=9, color=GOLD, ha='right', va='bottom')

    # 日期标签
    tick_step = max(1, len(amp) // 6)
    tick_pos = list(range(0, len(amp), tick_step))
    tick_labels = [df["date"].iloc[i].strftime("%m/%d") for i in tick_pos]
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_labels, fontsize=8)
    ax.set_ylabel("振幅%", fontsize=9, color=MUTED)


def _draw_sparklines(ax, df_daily):
    """绘制多周期迷你走势图"""
    ax.set_title("多周期走势", fontsize=11, color=TEXT_COLOR, loc='left', pad=8)

    periods = [("半年", 120), ("季度", 60), ("月度", 20), ("周度", 5)]

    for i, (label, days) in enumerate(periods):
        sub = df_daily.tail(days)
        if len(sub) < 2:
            continue
        first_c = sub["close"].iloc[0]
        last_c = sub["close"].iloc[-1]
        pct = round((last_c - first_c) / first_c * 100, 2)
        color = RED if pct >= 0 else GREEN

        prices = sub["close"].values
        p_min, p_max = prices.min(), prices.max()
        if p_max - p_min < 0.0001:
            normalized = np.full(len(prices), i + 0.5)
        else:
            normalized = (prices - p_min) / (p_max - p_min) * 0.7 + i + 0.15

        x = np.linspace(0, 1, len(prices))
        ax.plot(x, normalized, color=color, linewidth=2)
        ax.fill_between(x, i + 0.1, normalized, alpha=0.1, color=color)

        # 标签 - 带背景，字号加大
        sign = "+" if pct >= 0 else ""
        _label_bg(ax, 0.02, i + 0.85, label,
                  fontsize=10, color=TEXT_COLOR, bold=True, ha='left', va='top')
        _label_bg(ax, 0.98, i + 0.85, f"{sign}{pct:.1f}%",
                  fontsize=10, color=color, bold=True, ha='right', va='top')

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.1, len(periods))
    ax.set_xticks([])
    ax.set_yticks([])

    for i in range(1, len(periods)):
        ax.axhline(y=i, color=GRID_COLOR, linewidth=0.8, alpha=0.6)
