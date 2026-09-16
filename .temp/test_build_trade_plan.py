# -*- coding: utf-8 -*-
"""临时验证：高价股整手预算不足时 build_trade_plan 的降级逻辑。"""
import sys

sys.path.insert(0, r"G:\xu\demo\舆情驱动的股票短线交易策略生成系统")
from backend.app.agents.trading_strategy import TradingStrategyAgent

agent = TradingStrategyAgent.__new__(TradingStrategyAgent)
agent.total_capital = 10000.0

# 模拟真实高价股：中际旭创 921 元、低价股若干，整手 100 股
selections = [
    {"industry": "光模块", "stocks": ["中际旭创"]},
    {"industry": "银行", "stocks": ["工商银行"]},
    {"industry": "传媒", "stocks": ["某低价股"]},
]
quotes = {
    "中际旭创": {"current_price": 921.5, "five_day_volatility": 0.08, "lot_size": 100},
    "工商银行": {"current_price": 6.2, "five_day_volatility": 0.02, "lot_size": 100},
    "某低价股": {"current_price": 8.1, "five_day_volatility": 0.05, "lot_size": 100},
}
plans, cash = agent.build_trade_plan(selections, quotes)
print("PLANS:", len(plans))
for p in plans:
    print(f"  {p.stock}: price={p.current_price} shares={p.shares} amount={p.planned_amount}")
print("CASH RESERVE:", cash)
assert len(plans) == 3, "should produce 3 plans"
assert all(p.shares > 0 for p in plans)
assert sum(p.planned_amount for p in plans) <= 10000.01
print("UNIT TEST PASSED")