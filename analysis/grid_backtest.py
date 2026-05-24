"""网格参数优化 - 遍历间距/格数/金额，找最优组合"""
import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent.parent / "data" / "grid_spacing_cache.json"

# 参数搜索范围
MULTIPLIERS = [round(0.6 + i * 0.05, 2) for i in range(13)]  # 0.60 ~ 1.20
GRID_COUNTS = [2, 3, 4, 5, 6]
PER_GRID_OPTIONS = [500, 1000, 1500, 2000]
MAX_TOTAL_CAPITAL = 18000
MAX_DRAWDOWN_LIMIT = 6.0  # 最大回撤上限 %


def optimize_grid_params(
    df: pd.DataFrame,
    commission_rate: float = 0.0000768,
    max_dd_limit: float = MAX_DRAWDOWN_LIMIT,
) -> dict:
    """遍历参数组合，获取鲁棒性最好的间距乘数

    策略：对每个乘数，收集所有满足回撤约束的(格数,金额)组合的收益率，
    选择"平均收益高 且 收益稳定"的乘数（鲁棒性评分 = mean - 0.5*std）。
    这样避免选择只在特定格数/金额下表现好、换个参数就垮掉的过拟合乘数。

    遍历范围：
    - 间距乘数: 0.60 ~ 1.20 (步长0.05, 13个值)
    - 网格档数: 2 ~ 6 (步长1, 5个值)
    - 每格金额: 500 ~ 2000 (步长500, 4个值)
    - 约束: 总金额 = 档数 × 每格金额 ≤ 18000
    """
    from analysis.strategy_backtest import _simulate_grid
    from analysis.grid_params import GridParams

    avg_amp = df["amplitude"].mean()
    if avg_amp <= 0:
        return _default_params()

    start_price = float(df["close"].iloc[0])
    total_combos = 0
    valid_combos = 0

    # 按乘数分组收集有效组合的收益率
    mult_returns = {}  # {mult: [{"return_pct": ..., "grid_count": ..., "per_grid": ..., ...}]}
    all_combos_best = None  # 所有组合中回撤最小的（兜底）

    for mult in MULTIPLIERS:
        spacing_pct = round(avg_amp * mult, 2)
        spacing_price = round(start_price * spacing_pct / 100, 4)

        if spacing_price <= 0:
            continue

        for grid_count in GRID_COUNTS:
            for per_grid in PER_GRID_OPTIONS:
                total_capital = grid_count * per_grid
                if total_capital > MAX_TOTAL_CAPITAL:
                    continue

                total_combos += 1

                # 构建网格档位
                levels = []
                for i in range(grid_count):
                    buy_price = round(start_price - spacing_price * (i + 1), 4)
                    sell_price = round(buy_price + spacing_price, 4)
                    shares = max(100, int(per_grid / buy_price / 100) * 100)
                    levels.append({
                        "grid_num": i + 1,
                        "buy_price": round(buy_price, 3),
                        "sell_price": round(sell_price, 3),
                        "shares": shares,
                        "profit_per_trade": round(shares * spacing_price, 2),
                        "fee_per_trade": round(
                            shares * (buy_price + sell_price) * commission_rate, 2
                        ),
                    })

                # 构造 GridParams 模拟对象
                fake_params = type("GridParams", (), {
                    "levels": levels,
                    "spacing_price": spacing_price,
                    "capital": total_capital,
                    "grid_count": grid_count,
                    "spacing_pct": spacing_pct,
                })()

                # 执行回测
                try:
                    result = _simulate_grid(df, fake_params)
                except Exception:
                    continue

                total_pnl = result.get("total_pnl", result["total_profit"])
                max_dd = result["max_drawdown_pct"]
                return_pct = round(total_pnl / total_capital * 100, 2) if total_capital > 0 else 0

                # 兜底：全局回撤最小
                if all_combos_best is None or max_dd < all_combos_best["max_drawdown_pct"]:
                    all_combos_best = {
                        "optimal_multiplier": mult,
                        "grid_count": grid_count,
                        "per_grid": per_grid,
                        "total_capital": total_capital,
                        "spacing_pct": spacing_pct,
                        "total_pnl": round(total_pnl, 2),
                        "total_profit": result["total_profit"],
                        "unrealized_pnl": result.get("unrealized_pnl", 0),
                        "max_drawdown_pct": round(max_dd, 2),
                        "return_pct": return_pct,
                        "total_trades": result["total_trades"],
                        "win_rate": result["win_rate"],
                    }

                if max_dd > max_dd_limit:
                    continue

                valid_combos += 1
                if mult not in mult_returns:
                    mult_returns[mult] = []
                mult_returns[mult].append({
                    "optimal_multiplier": mult,
                    "grid_count": grid_count,
                    "per_grid": per_grid,
                    "total_capital": total_capital,
                    "spacing_pct": spacing_pct,
                    "total_pnl": round(total_pnl, 2),
                    "total_profit": result["total_profit"],
                    "unrealized_pnl": result.get("unrealized_pnl", 0),
                    "max_drawdown_pct": round(max_dd, 2),
                    "return_pct": return_pct,
                    "total_trades": result["total_trades"],
                    "win_rate": result["win_rate"],
                })

    # === 鲁棒性选择：平均收益最高 且 标准差最小 ===
    best_mult = None
    best_robust_score = -999

    for mult, combos in mult_returns.items():
        returns = [c["return_pct"] for c in combos]
        if len(returns) < 2:
            # 只有1个有效组合，无法评估稳定性，给较低鲁棒分
            mean_ret = returns[0]
            std_ret = 0
            robust_score = mean_ret - 2.0  # 惩罚：无法验证稳定性
        else:
            mean_ret = np.mean(returns)
            std_ret = np.std(returns)
            robust_score = mean_ret - 0.5 * std_ret  # 鲁棒性评分

        if robust_score > best_robust_score:
            best_robust_score = robust_score
            # 选该乘数下回撤最小、收益最高的组合
            best_combo = min(combos, key=lambda c: (-c["return_pct"], -c["max_drawdown_pct"]))
            best_mult = mult
            best = best_combo

        log.debug(f"  乘数{mult}: {len(returns)}组合, "
                  f"均值={mean_ret:+.2f}%, 标准差={std_ret:.2f}%, "
                  f"鲁棒分={robust_score:+.2f}")

    if best_mult is not None:
        log.info(f"  鲁棒选择: 乘数{best_mult}, 鲁棒分={best_robust_score:+.2f}, "
                 f"收益={best['return_pct']:+.2f}%, 回撤={best['max_drawdown_pct']}%")
        valid_combos_total = sum(len(v) for v in mult_returns.values())
        log.info(f"  参数搜索: {total_combos}组合, {valid_combos}个满足回撤<{max_dd_limit}%, "
                 f"{len(mult_returns)}个乘数有有效数据")
        return best

    # 没有任何满足回撤约束的组合，使用全局回撤最小的
    if all_combos_best is not None:
        log.info(f"  无满足回撤约束的组合，使用全局回撤最小: "
                 f"乘数{all_combos_best['optimal_multiplier']}, 回撤{all_combos_best['max_drawdown_pct']}%")
        return all_combos_best

    return _default_params()


def _find_min_drawdown_params(df, avg_amp, start_price, commission_rate):
    """找不到满足回撤约束的组合时，选回撤最小的"""
    from analysis.strategy_backtest import _simulate_grid

    best = None
    best_dd = 999

    for mult in MULTIPLIERS:
        spacing_pct = round(avg_amp * mult, 2)
        spacing_price = round(start_price * spacing_pct / 100, 4)
        if spacing_price <= 0:
            continue

        for grid_count in GRID_COUNTS:
            for per_grid in PER_GRID_OPTIONS:
                total_capital = grid_count * per_grid
                if total_capital > MAX_TOTAL_CAPITAL:
                    continue

                levels = []
                for i in range(grid_count):
                    buy_price = round(start_price - spacing_price * (i + 1), 4)
                    sell_price = round(buy_price + spacing_price, 4)
                    shares = max(100, int(per_grid / buy_price / 100) * 100)
                    levels.append({
                        "grid_num": i + 1,
                        "buy_price": round(buy_price, 3),
                        "sell_price": round(sell_price, 3),
                        "shares": shares,
                        "profit_per_trade": round(shares * spacing_price, 2),
                        "fee_per_trade": round(
                            shares * (buy_price + sell_price) * commission_rate, 2
                        ),
                    })

                fake_params = type("GridParams", (), {
                    "levels": levels,
                    "spacing_price": spacing_price,
                    "capital": total_capital,
                    "grid_count": grid_count,
                    "spacing_pct": spacing_pct,
                })()

                try:
                    result = _simulate_grid(df, fake_params)
                except Exception:
                    continue

                dd = result["max_drawdown_pct"]
                if dd < best_dd:
                    best_dd = dd
                    total_pnl = result.get("total_pnl", result["total_profit"])
                    best = {
                        "optimal_multiplier": mult,
                        "grid_count": grid_count,
                        "per_grid": per_grid,
                        "total_capital": total_capital,
                        "spacing_pct": spacing_pct,
                        "total_pnl": round(total_pnl, 2),
                        "total_profit": result["total_profit"],
                        "unrealized_pnl": result.get("unrealized_pnl", 0),
                        "max_drawdown_pct": round(dd, 2),
                        "return_pct": round(total_pnl / total_capital * 100, 2) if total_capital > 0 else 0,
                        "total_trades": result["total_trades"],
                        "win_rate": result["win_rate"],
                    }

    return best or _default_params()


def _default_params():
    """默认参数"""
    return {
        "optimal_multiplier": 0.8,
        "grid_count": 6,
        "per_grid": 1000,
        "total_capital": 6000,
        "spacing_pct": 0,
        "total_pnl": 0,
        "max_drawdown_pct": 0,
        "return_pct": 0,
        "total_trades": 0,
        "win_rate": 0,
    }


# === 缓存管理 ===

def load_spacing_cache() -> dict:
    """加载缓存"""
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"updated_date": "", "etfs": {}}


def save_spacing_cache(cache: dict):
    """保存缓存"""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def get_optimal_params(code: str, df: pd.DataFrame) -> dict:
    """获取最优网格参数（优先走缓存，周一自动刷新）

    返回: {"optimal_multiplier": float, "grid_count": int, "per_grid": int}
    """
    cache = load_spacing_cache()
    today = datetime.now().strftime("%Y-%m-%d")
    is_monday = datetime.now().weekday() == 0

    # 缓存有效：非周一且有数据
    if not is_monday and code in cache.get("etfs", {}):
        entry = cache["etfs"][code]
        # 兼容旧格式（只有 optimal_multiplier）
        if "grid_count" in entry:
            return entry

    # 需要重新优化
    log.info(f"  优化 {code} 网格参数...")
    result = optimize_grid_params(df)

    # 更新缓存
    cache["updated_date"] = today
    if "etfs" not in cache:
        cache["etfs"] = {}
    cache["etfs"][code] = result
    save_spacing_cache(cache)

    log.info(
        f"  {code} 最优: 乘数={result['optimal_multiplier']}, "
        f"{result['grid_count']}格×{result['per_grid']}元, "
        f"收益率={result['return_pct']:+.2f}%, 回撤={result['max_drawdown_pct']}%"
    )
    return result


# === 兼容旧接口 ===

def get_optimal_multiplier(code: str, df: pd.DataFrame) -> float:
    """兼容旧接口，返回最优间距乘数"""
    params = get_optimal_params(code, df)
    return params.get("optimal_multiplier", 0.8)


def backtest_grid_spacing(df, multipliers=None, grid_count=6, capital_per_grid=1000):
    """兼容旧接口 - 间距回测"""
    if multipliers is None:
        multipliers = MULTIPLIERS
    result = optimize_grid_params(df)
    return {"optimal_multiplier": result["optimal_multiplier"], "results": {}}
