import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient

# 1. 加载环境变量
load_dotenv()

# 2. 从环境变量读取 KEY
# 确保你的 .env 文件中有这些字段
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

# 3. 初始化交易客户端 (paper=True 代表连接模拟盘)
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)

def show_account_details():
    try:
        # 获取账户信息
        account = trading_client.get_account()

        print("=" * 30)
        print("   Alpaca 模拟盘账户状态")
        print("=" * 30)
        print(f"账户 ID:    {account.id}")
        print(f"账户状态:   {account.status}")
        print("-" * 30)
        print(f"当前总权益: ${account.equity}")
        print(f"可用现金:   ${account.cash}")
        print(f"购买力:     ${account.buying_power}")
        print("-" * 30)
        
        # 计算今日盈亏
        balance_change = float(account.equity) - float(account.last_equity)
        print(f"今日盈亏:   ${balance_change:,.2f}")
        
        if account.trading_blocked:
            print("[警告] 你的账户目前被禁止交易！")
        else:
            print("[正常] 账户已就绪，可以进行 AI 下单测试。")
            
    except Exception as e:
        print(f"连接失败: {e}")
        print("提示: 请检查 .env 中的 Key 是否正确，以及是否处于 Paper 模式。")

def fetch_live_portfolio(trading_client):
    # 1. 获取账户余额
    account = trading_client.get_account()
    
    # 2. 获取当前持仓
    positions = trading_client.get_all_positions()
    
    portfolio_positions = {}
    for pos in positions:
        # 将 "NVDA" 这样的 Ticker 映射为 Agent 格式
        portfolio_positions[pos.symbol] = {
            "long": float(pos.qty) if pos.side.value == 'long' else 0,
            "short": float(pos.qty) if pos.side.value == 'short' else 0
        }
    
    return {
        "cash": float(account.cash),
        "positions": portfolio_positions
    }

if __name__ == "__main__":
    show_account_details()
    portfolio=fetch_live_portfolio(trading_client)
    print(f"Portfolio is: {portfolio}")