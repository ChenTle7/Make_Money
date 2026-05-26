"""图表生成 - 网格交易专属可视化（移动端优化）"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import pandas as pd
import numpy as np
import base64
from io import BytesIO

# 自动查找可用中文字体
_CJK_KEYWORDS = ['CJK', 'Hei', 'Song', 'Fang', 'Kai', 'WenQuanYi', 'SimHei',
                  'SimSun', 'Microsoft YaHei', 'Noto Sans', 'Source Han', 'PingFang']
_available = set()
for f in fm.fontManager.ttflist:
    _available.add(f.name)
_chosen_font = None
for kw in _CJK_KEYWORDS:
    for name in _available:
        if kw.lower() in name.lower():
            _chosen_font = name
            break
    if _chosen_font:
        break

plt.rcParams['font.sans-serif'] = [_chosen_font] if _chosen_font else ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 颜色
RED = '#FF5555'
GREEN = '#34D399'
GOLD = '#FFD700'
BLUE = '#60A5FA'
BG_COLOR = '#0F1B2D'
TEXT_COLOR = '#F0F4F8'
GRID_COLOR = '#2A3A4E'
MUTED = '#B0C4DE'


def _fig_to_base64(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight',
                facecolor=BG_COLOR, edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def _setup_ax(ax):
    ax.set_facecolor(BG_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=11)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(GRID_COLOR)
    ax.spines['left'].set_color(GRID_COLOR)
    ax.grid(True, alpha=0.2, color=GRID_COLOR)


def _label_bg(ax, x, y, text, fontsize=12, color=TEXT_COLOR, bg=BG_COLOR,
              bold=False, edgecolor=None, ha='center', va='center', transform=None, **kwargs):
    kw = dict(fontsize=fontsize, color=color, ha=ha, va=va,
              bbox=dict(boxstyle='round,pad=0.3', facecolor=bg, edgecolor=edgecolor or 'none',
                        alpha=0.9, linewidth=0.8))
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
) -> str:
    """竖排两面板：振幅趋势 | 周期走势"""
    fig = plt.figure(figsize=(8, 8), facecolor=BG_COLOR)
    gs = GridSpec(2, 1, height_ratios=[1, 1], hspace=0.4, figure=fig)

    # 上：振幅趋势
    ax_amp = fig.add_subplot(gs[0])
    _setup_ax(ax_amp)
    _draw_amplitude(ax_amp, df_daily)

    # 下：周期走势
    ax_trend = fig.add_subplot(gs[1])
    _setup_ax(ax_trend)
    _draw_sparklines(ax_trend, df_daily)

    return _fig_to_base64(fig)



def _draw_amplitude(ax, df_daily):
    ax.set_title("近期振幅趋势", fontsize=15, color=TEXT_COLOR, loc='left', pad=10)

    n = min(len(df_daily), 30)
    df = df_daily.tail(n).copy().reset_index(drop=True)

    if len(df) < 3:
        ax.text(0.5, 0.5, "数据不足", transform=ax.transAxes, ha='center', va='center',
                fontsize=14, color=MUTED)
        ax.set_xticks([])
        return

    amp = ((df["high"] - df["low"]) / df["low"] * 100).values
    mean_amp = np.mean(amp)

    colors = [RED if amp[i] >= mean_amp else GREEN for i in range(len(amp))]
    ax.bar(range(len(amp)), amp, color=colors, width=0.7, alpha=0.75)
    ax.axhline(y=mean_amp, color=GOLD, linewidth=1.5, linestyle='--', alpha=0.8)

    _label_bg(ax, len(amp) - 0.5, mean_amp, f"均值 {mean_amp:.2f}%",
              fontsize=12, color=GOLD, ha='right', va='bottom')

    tick_step = max(1, len(amp) // 6)
    tick_pos = list(range(0, len(amp), tick_step))
    tick_labels = [df["date"].iloc[i].strftime("%m/%d") for i in tick_pos]
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_labels, fontsize=10)
    ax.set_ylabel("振幅%", fontsize=12, color=MUTED)


def _draw_sparklines(ax, df_daily):
    ax.set_title("多周期走势", fontsize=15, color=TEXT_COLOR, loc='left', pad=10)

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
        ax.plot(x, normalized, color=color, linewidth=2.5)
        ax.fill_between(x, i + 0.1, normalized, alpha=0.1, color=color)

        sign_str = "+" if pct >= 0 else ""
        _label_bg(ax, 0.02, i + 0.85, label,
                  fontsize=14, color=TEXT_COLOR, bold=True, ha='left', va='top')
        _label_bg(ax, 0.98, i + 0.85, f"{sign_str}{pct:.1f}%",
                  fontsize=14, color=color, bold=True, ha='right', va='top')

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.1, len(periods))
    ax.set_xticks([])
    ax.set_yticks([])

    for i in range(1, len(periods)):
        ax.axhline(y=i, color=GRID_COLOR, linewidth=0.8, alpha=0.6)
