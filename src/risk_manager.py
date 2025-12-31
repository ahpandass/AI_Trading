import os
import sys
import io
import json
import logging
from pathlib import Path
from datetime import datetime
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# 强制 UTF-8 输出，防止 Windows 控制台乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 导入你现有的 Trader
from main import AlpacaTrader  

class RiskManager:
    def __init__(self, trailing_pct=0.05, initial_stop_loss_pct=0.08, data_filename="risk_data.json", log_filename="risk_management.log"):
        self.trader = AlpacaTrader()
        self.trailing_pct = trailing_pct
        self.initial_stop_loss_pct = initial_stop_loss_pct
        
        # --- 路径处理 ---
        base_dir = Path(__file__).resolve().parent
        self.db_dir = base_dir / "database"
        self.db_dir.mkdir(parents=True, exist_ok=True) # 确保 database 文件夹存在
        
        self.data_file = self.db_dir / data_filename
        self.log_file = self.db_dir / log_filename
        
        # --- 配置日志系统 ---
        self._setup_logging()
        
        self.risk_data = self._load_data()

    def _setup_logging(self):
        """设置日志记录：同时输出到控制台和 database 文件夹下的文件"""
        self.logger = logging.getLogger("RiskManager")
        self.logger.setLevel(logging.INFO)
        
        # 防止重复添加 handler
        if not self.logger.handlers:
            # 文件处理器 (强制 utf-8)
            file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
            file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            
            # 控制台处理器
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_formatter = logging.Formatter('%(message)s') # 控制台简短点
            stream_handler.setFormatter(stream_formatter)
            
            self.logger.addHandler(file_handler)
            self.logger.addHandler(stream_handler)

    def _load_data(self):
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"⚠️ 加载数据库失败: {e}")
                return {}
        return {}

    def _save_data(self):
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.risk_data, f, indent=4)
        except Exception as e:
            self.logger.error(f"❌ 无法保存数据库文件: {e}")

    def monitor_and_execute(self):
        self.logger.info(f"--- 风控巡检开始 (支持多/空) ---")
        
        try:
            positions = self.trader.client.get_all_positions()
        except Exception as e:
            self.logger.error(f"❌ 无法获取持仓: {e}")
            return

        if not positions:
            self.logger.info("目前无持仓。")
            self.risk_data = {}
            self._save_data()
            return

        current_symbols = []
        for position in positions:
            symbol = position.symbol
            current_symbols.append(symbol)
            qty = abs(float(position.qty))
            avg_entry_price = float(position.avg_entry_price)
            current_price = float(position.current_price)
            is_long = float(position.qty) > 0
            
            # 记录或更新极值价格
            if symbol not in self.risk_data:
                self.risk_data[symbol] = {
                    "extreme_price": current_price,
                    "side": "LONG" if is_long else "SHORT"
                }
            
            extreme_price = self.risk_data[symbol]["extreme_price"]

            if is_long:
                if current_price > extreme_price:
                    self.risk_data[symbol]["extreme_price"] = current_price
                    extreme_price = current_price
                    self.logger.info(f"📈 [{symbol}] 创出新高: {current_price:.2f}")
                
                hard_stop = avg_entry_price * (1 - self.initial_stop_loss_pct)
                trail_stop = extreme_price * (1 - self.trailing_pct)
                final_stop = max(hard_stop, trail_stop)
                triggered = current_price <= final_stop
                sell_side = OrderSide.SELL
            else:
                if current_price < extreme_price:
                    self.risk_data[symbol]["extreme_price"] = current_price
                    extreme_price = current_price
                    self.logger.info(f"📉 [{symbol}] 创出新低: {current_price:.2f}")
                
                hard_stop = avg_entry_price * (1 + self.initial_stop_loss_pct)
                trail_stop = extreme_price * (1 + self.trailing_pct)
                final_stop = min(hard_stop, trail_stop)
                triggered = current_price >= final_stop
                sell_side = OrderSide.BUY

            self.logger.info(f"[{symbol}] {'LONG' if is_long else 'SHORT'} | 当前:{current_price:.2f} | 极值:{extreme_price:.2f} | 止损线:{final_stop:.2f}")

            if triggered:
                reason = "移动止损触发" if final_stop == trail_stop else "硬止损触发"
                self.execute_close(symbol, qty, sell_side, reason, current_price)
                del self.risk_data[symbol]

        self.risk_data = {s: d for s, d in self.risk_data.items() if s in current_symbols}
        self._save_data()

    def execute_close(self, symbol, qty, side, reason, price):
        self.logger.warning(f"🚨 {symbol} {reason}！当前价 {price:.2f}。执行平仓...")
        try:
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.GTC
            )
            self.trader.client.submit_order(order_data)
            self.logger.info(f"✅ {symbol} 平仓订单已提交。")
        except Exception as e:
            self.logger.error(f"❌ {symbol} 平仓失败: {e}")

if __name__ == "__main__":
    manager = RiskManager()
    manager.monitor_and_execute()