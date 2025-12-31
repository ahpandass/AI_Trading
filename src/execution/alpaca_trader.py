import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest
from colorama import Fore, Style, init
from dotenv import load_dotenv

# 初始化 colorama，autoreset=True 会让颜色在每行结束后自动恢复默认
init(autoreset=True)

class AlpacaTrader:
    def __init__(self, buffer_pct=0.05):
        """
        :param buffer_pct: 资金缓冲区百分比（默认5%），防止因市价波动导致余额不足下单失败
        """
        load_dotenv()
        self.api_key = os.getenv("ALPACA_API_KEY")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY")
        self.paper = True # 默认模拟盘
        
        self.client = TradingClient(self.api_key, self.secret_key, paper=self.paper)
        self.data_client = StockHistoricalDataClient(self.api_key, self.secret_key)
        self.buffer_pct = buffer_pct
    def get_live_portfolio(self):
        """获取并格式化当前真实的账户信息和持仓"""
        account = self.client.get_account()
        positions = self.client.get_all_positions()
        # 转换为 Agent 能够理解的字典格式
        formatted_positions = {}
        for pos in positions:
            formatted_positions[pos.symbol] = {
                "long": float(pos.qty) if pos.side.value == 'long' else 0,
                "short": float(pos.qty) if pos.side.value == 'short' else 0
            }
        return {
            "cash": float(account.cash),
            "positions": formatted_positions,
            "equity": float(account.equity)
        }
    
    def get_realtime_price(self, ticker):
        """获取最新实时价格，带有多种备选方案"""
        try:
            # 1. 获取最新报价 (Quote)
            quote = self.data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=ticker))
            ask = quote[ticker].ask_price
            
            # 2. 获取最新成交 (Trade)
            trade_req = StockLatestTradeRequest(symbol_or_symbols=ticker)
            trade = self.data_client.get_stock_latest_trade(trade_req)
            last_price = trade[ticker].price

            # 3. 安全逻辑：如果买一/卖一价和成交价差太多（例如 > 2%），说明 Quote 是虚假的
            if ask > 0 and last_price > 0:
                diff_pct = abs(ask - last_price) / last_price
                if diff_pct > 0.02: # 偏差超过 2%
                    print(f"⚠️ [{ticker}] 报价异常! Ask:{ask}, Last:{last_price}。改用成交价。")
                    return float(last_price)
            
            # 4. 正常返回逻辑
            if ask > 0: return float(ask)
            return float(last_price) if last_price > 0 else 0.0
            
        except Exception as e:
            print(f"❌ 价格获取失败: {e}")
            return 0.0
    
    def execute_decisions(self, decisions):
        """
        带安全检查的执行逻辑
        支持: BUY, SHORT, SELL (平多), COVER (平空)
        """
        print("\n" + "="*40)
        print(f"{Fore.CYAN}🛡️  交易安全检查与执行开始{Style.RESET_ALL}")
        print("="*40)

        # 1. 获取最新实时持仓，用于交叉验证指令合法性
        # 使用你之前的 get_live_portfolio 方法
        current_portfolio = self.get_live_portfolio()
        positions = current_portfolio["positions"]
        cash = current_portfolio["cash"]

        for ticker, decision in decisions.items():
            action = decision.get("action", "").upper()
            quantity = int(decision.get("quantity", 0))
            
            # 基础过滤
            if quantity <= 0 or action == "HOLD":
                print(f"  - [{ticker}] 指令: {Fore.YELLOW}HOLD{Style.RESET_ALL} (跳过)")
                continue

            # 获取当前该股的持仓量
            long_qty = positions.get(ticker, {}).get("long", 0)
            short_qty = positions.get(ticker, {}).get("short", 0)

            side = None
            skip_reason = None

            # 2. 核心安全检查逻辑
            if action == "BUY":
                # 2. 获取实时价格
                rt_price = self.get_realtime_price(ticker)
                if rt_price:
                    # 3. 根据实时价格和缓冲区重新计算最大可买数量
                    max_qty = int((cash * (1 - self.buffer_pct)) / rt_price)
                    if quantity > max_qty:
                        print(f"  ⚠️ {ticker} 价格波动，数量从 {quantity} 修正为 {max_qty}")
                        quantity = max_qty
                # 做多开仓：检查是否已有空头仓位（理想状态应先 COVER）
                if short_qty > 0:
                    skip_reason = f"检测到存在空头持仓 ({short_qty})，不能直接执行 BUY。应先执行 COVER。"
                else:
                    side = OrderSide.BUY
                    # 买入预留缓冲区，防止资金不足
                    quantity = int(quantity * (1 - self.buffer_pct))

            elif action == "SHORT":
                # 做空开仓：检查是否已有多头仓位（理想状态应先 SELL）
                if long_qty > 0:
                    skip_reason = f"检测到存在多头持仓 ({long_qty})，不能直接执行 SHORT。应先执行 SELL。"
                else:
                    side = OrderSide.SELL

            elif action == "SELL":
                # 平多：安全检查 - 如果没持仓，SELL 动作无效
                if long_qty <= 0:
                    skip_reason = "当前无多头持仓，无法执行 SELL 平仓指令。"
                else:
                    side = OrderSide.SELL
                    # 确保平仓数量不超过实际持有量
                    quantity = min(quantity, int(long_qty))

            elif action == "COVER":
                # 平空：安全检查 - 如果没做空，COVER 动作无效
                if short_qty <= 0:
                    skip_reason = "当前无空头持仓，无法执行 COVER 平仓指令。"
                else:
                    side = OrderSide.BUY
                    # 平空买回也需要现金缓冲区
                    quantity = min(quantity, int(short_qty))
                    quantity = int(quantity * (1 - self.buffer_pct))

            # 3. 处理跳过或下单
            if skip_reason:
                print(f"  ⚠️ [{ticker}] {Fore.RED}拒绝执行 {action}{Style.RESET_ALL}: {skip_reason}")
                continue

            if side:
                print(ticker,quantity,side)
                try:
                    action_color = {"BUY": Fore.GREEN, "COVER": Fore.GREEN, "SELL": Fore.RED, "SHORT": Fore.RED}.get(action, Fore.WHITE)
                    order_data = MarketOrderRequest(
                        symbol=ticker,
                        qty=quantity,
                        side=side,
                        time_in_force=TimeInForce.DAY
                    )
                    self.client.submit_order(order_data)
                    print(f"  ✅ [{ticker}] {action_color}{action}{Style.RESET_ALL} 成功 | 数量: {quantity}")
                except Exception as e:
                    print(f"  ❌ [{ticker}] {action} 提交失败: {str(e)}")

    def cancel_all_orders(self):
        """清空所有挂单，确保账户状态干净"""
        self.client.cancel_orders()
        print("所有挂单已撤销")