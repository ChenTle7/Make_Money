"""项目配置 - 自选股、路径、参数"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data" / "cache"
REPORT_DIR = PROJECT_ROOT / "reports" / "output"
TEMPLATE_DIR = PROJECT_ROOT / "reports"

# 11只港股T+0 ETF自选股
WATCHLIST = [
    {"code": "513010", "name": "恒生科技ETF", "market": "SH"},
    {"code": "513330", "name": "恒生互联网ETF", "market": "SH"},
    {"code": "159792", "name": "港股通互联网ETF", "market": "SZ"},
    {"code": "513770", "name": "港股互联网ETF", "market": "SH"},
    {"code": "513130", "name": "恒生科技ETF", "market": "SH"},
    {"code": "513980", "name": "港股科技ETF", "market": "SH"},
    {"code": "513120", "name": "港股创新药ETF", "market": "SH"},
    {"code": "520500", "name": "恒生创新药ETF", "market": "SH"},
    {"code": "513090", "name": "香港证券ETF", "market": "SH"},
    {"code": "159131", "name": "港股通信息技术ETF", "market": "SZ"},
    {"code": "520600", "name": "港股通汽车ETF", "market": "SH"},
]

# 资金参数
CAPITAL_PER_ETF = 18000     # 每只ETF网格资金上限
MIN_CAPITAL_PER_ETF = 6000  # 单只ETF最小资金（观望时）
GRID_COUNT = 6              # 默认网格档数
COMMISSION_RATE = 0.0000768 # 万0.768

# 大盘指数代码
A_SHARE_INDICES = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "创业板指": "sz399006",
}
HK_INDICES = {
    "恒生指数": "HSI",
    "恒生科技指数": "HSTECH",
}
US_INDICES = {
    "纳斯达克": ".IXIC",
    "标普500": ".INX",
}

# 确保目录存在
for d in [DATA_DIR, REPORT_DIR]:
    d.mkdir(parents=True, exist_ok=True)
