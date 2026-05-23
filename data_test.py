"""
数据源测试 - AKShare(日线,优先) + 腾讯/新浪(分钟线+fallback)
基金: 513090 香港证券ETF
"""
import requests
import pandas as pd
import json
from datetime import datetime, timedelta


def get_daily_data(code="513090", days=20):
    """获取日线数据: 优先AKShare, 失败则用腾讯接口"""
    try:
        import akshare as ak
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        df = ak.fund_etf_hist_em(symbol=code, period="daily",
                                 start_date=start, end_date=end, adjust="qfq")
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume"
        })
        print("  [数据源: AKShare]")
    except Exception as e:
        print(f"  [AKShare失败: {e.__class__.__name__}, 使用腾讯接口]")
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        params = {"param": f"sh{code},day,,,{days},qfq"}
        r = requests.get(url, params=params, timeout=10)
        raw = r.json()["data"][f"sh{code}"]["day"]
        df = pd.DataFrame(raw, columns=["date", "open", "close", "high", "low", "volume"])

    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "close", "high", "low"]:
        df[col] = df[col].astype(float)
    df["amplitude"] = ((df["high"] - df["low"]) / df["low"] * 100).round(2)
    return df.tail(days)


def get_minute_data(code="513090", scale=5):
    """获取分钟K线: 新浪接口 (scale: 5/15/30/60)"""
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": f"sh{code}", "scale": str(scale), "ma": "no", "datalen": "240"}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    df = pd.DataFrame(data)
    df["day"] = pd.to_datetime(df["day"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(float)
    print(f"  [数据源: 新浪, {scale}分钟K线]")
    return df


def calc_grid_params(daily_df, capital=18000, grid_count=6):
    """根据日线数据计算网格参数"""
    avg_amp = daily_df["amplitude"].mean()
    current_price = daily_df["close"].iloc[-1]
    min_price = daily_df["low"].min()
    max_price = daily_df["high"].max()

    per_grid = capital / grid_count
    spacing_pct = round(avg_amp * 0.8, 2)  # 间距取平均振幅的80%
    spacing_price = round(current_price * spacing_pct / 100, 3)

    print(f"\n{'='*55}")
    print(f"  网格参数计算 (基于近{len(daily_df)}日数据)")
    print(f"{'='*55}")
    print(f"  当前价格: {current_price}")
    print(f"  近期区间: {min_price} ~ {max_price}")
    print(f"  平均日振幅: {avg_amp:.2f}%")
    print(f"  网格数量: {grid_count}")
    print(f"  网格间距: {spacing_pct}% (≈{spacing_price}元)")
    print(f"  每格资金: {per_grid:.0f}元")
    print(f"  总投入: {capital}元 (90%仓位)")
    print(f"{'='*55}")

    print(f"\n  格数  买入价    卖出价    份额     预计利润")
    print(f"  {'─'*48}")
    buy_levels = []
    for i in range(grid_count):
        buy_price = round(current_price - spacing_price * (i + 1), 3)
        sell_price = round(buy_price + spacing_price, 3)
        shares = int(per_grid / buy_price / 100) * 100
        if shares < 100:
            shares = 100
        profit = round(shares * spacing_price, 1)
        fee = round(shares * (buy_price + sell_price) * 0.0000768, 2)
        buy_levels.append({
            "grid": i+1, "buy": buy_price, "sell": sell_price,
            "shares": shares, "profit": profit, "fee": fee
        })
        print(f"  第{i+1}格  {buy_price:<8}  {sell_price:<8}  {shares:<7}  ≈{profit}元 (手续费≈{fee}元)")

    return buy_levels


if __name__ == "__main__":
    code = "513090"

    # 1. 日线数据
    print("=" * 60)
    print(f"  日线数据 - {code} 香港证券ETF")
    print("=" * 60)
    daily = get_daily_data(code, days=20)
    print(daily[["date", "close", "high", "low", "amplitude"]].to_string(index=False))

    # 2. 分钟线数据
    print(f"\n{'='*60}")
    print(f"  分钟K线 - {code}")
    print("=" * 60)
    minute = get_minute_data(code, scale=5)
    today_min = minute[minute["day"].dt.date == minute["day"].dt.date.max()]
    print(f"  今日获取到 {len(today_min)} 条5分钟K线")
    print(today_min[["day", "open", "high", "low", "close"]].tail(10).to_string(index=False))

    # 3. 网格参数
    levels = calc_grid_params(daily)
