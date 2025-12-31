import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from colorama import Fore, Style, init
import questionary
from src.agents.portfolio_manager import portfolio_management_agent
from src.agents.risk_manager import risk_management_agent
from src.graph.state import AgentState
from src.utils.display import print_trading_output
from src.utils.analysts import ANALYST_ORDER, get_analyst_nodes
from src.utils.progress import progress
from src.utils.visualize import save_graph_as_png
from src.cli.input import (
    parse_cli_inputs,
)
from src.execution.alpaca_trader import AlpacaTrader
from src.utils.trading_logger import TradingLogger

import argparse
from datetime import datetime
from dateutil.relativedelta import relativedelta
import json

# Load environment variables from .env file
load_dotenv()

init(autoreset=True)


def parse_hedge_fund_response(response):
    """Parses a JSON string and returns a dictionary."""
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        print(f"JSON decoding error: {e}\nResponse: {repr(response)}")
        return None
    except TypeError as e:
        print(f"Invalid response type (expected string, got {type(response).__name__}): {e}")
        return None
    except Exception as e:
        print(f"Unexpected error while parsing response: {e}\nResponse: {repr(response)}")
        return None

def align_portfolio(live_data, tickers, margin_requirement=0.0):
    """将 Alpaca 的数据对齐为 Agent 期望的完整格式"""
    #
    # 基础结构
    full_portfolio = {
        "cash": live_data["cash"],
        "margin_requirement": margin_requirement,
        "margin_used": 0.0, # 模拟盘初期通常设为0
        "positions": {},
        "realized_gains": {ticker: {"long": 0.0, "short": 0.0} for ticker in tickers}
    }
#
    # 填充 positions
    for ticker in tickers:
        # 如果 Alpaca 真实持仓里有这只票
        if ticker in live_data["positions"]:
            pos = live_data["positions"][ticker]
            full_portfolio["positions"][ticker] = {
                "long": pos["long"],
                "short": pos["short"],
                "long_cost_basis": 0.0, # 实时交易中通常由交易所跟踪，初次对接可设为0
                "short_cost_basis": 0.0,
                "short_margin_used": 0.0,
            }
        else:
            # 如果没持仓，填充默认空值
            full_portfolio["positions"][ticker] = {
                "long": 0,
                "short": 0,
                "long_cost_basis": 0.0,
                "short_cost_basis": 0.0,
                "short_margin_used": 0.0,
            }
    #
    # 3. 填充 realized_gains (启动时设为 0.0)
            full_portfolio["realized_gains"][ticker] = {
                "long": 0.0,
                "short": 0.0
            }
       #     
    return full_portfolio

##### Run the Hedge Fund #####
def run_hedge_fund(
    tickers: list[str],
    start_date: str,
    end_date: str,
    portfolio: dict,
    show_reasoning: bool = False,
    selected_analysts: list[str] = [],
    model_name: str = "gpt-4.1",
    model_provider: str = "OpenAI",
):
    # Start progress tracking
    progress.start()

    try:
        # Build workflow (default to all analysts when none provided)
        workflow = create_workflow(selected_analysts if selected_analysts else None)
        agent = workflow.compile()

        final_state = agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        content="Make trading decisions based on the provided data.",
                    )
                ],
                "data": {
                    "tickers": tickers,
                    "portfolio": portfolio,
                    "start_date": start_date,
                    "end_date": end_date,
                    "analyst_signals": {},
                },
                "metadata": {
                    "show_reasoning": show_reasoning,
                    "model_name": model_name,
                    "model_provider": model_provider,
                },
            },
        )

        output_result = {
            "decisions": parse_hedge_fund_response(final_state["messages"][-1].content),
            "analyst_signals": final_state["data"]["analyst_signals"],
        }

        # === 改进：将保存逻辑移至此处，确保必然触发 ===
        try:
            with open("decision_results.txt", "a", encoding="utf-8") as f:
                import datetime
                f.write(f"\n{'='*50}\n")
                f.write(f"Run at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Tickers: {tickers} | {start_date} to {end_date}\n")
                f.write(f"{'='*50}\n")
                # 使用 json.dumps 替代 str()，这样保存的内容是可读的 JSON 格式
                f.write(json.dumps(output_result, indent=2, ensure_ascii=False))
                f.write("\n\n")
            # 注意：在 Agent 运行期间，print 可能被 progress bar 覆盖
            # 建议使用 print 或 logging 记录成功
        except Exception as file_err:
            print(f"Failed to save results to file: {file_err}")

        return output_result
    finally:
        # Stop progress tracking
        progress.stop()


def start(state: AgentState):
    """Initialize the workflow with the input message."""
    return state


def create_workflow(selected_analysts=None):
    """Create the workflow with selected analysts."""
    workflow = StateGraph(AgentState)
    workflow.add_node("start_node", start)

    # Get analyst nodes from the configuration
    analyst_nodes = get_analyst_nodes()

    # Default to all analysts if none selected
    if selected_analysts is None:
        selected_analysts = list(analyst_nodes.keys())
    # Add selected analyst nodes
    for analyst_key in selected_analysts:
        node_name, node_func = analyst_nodes[analyst_key]
        workflow.add_node(node_name, node_func)
        workflow.add_edge("start_node", node_name)

    # Always add risk and portfolio management
    workflow.add_node("risk_management_agent", risk_management_agent)
    workflow.add_node("portfolio_manager", portfolio_management_agent)

    # Connect selected analysts to risk management
    for analyst_key in selected_analysts:
        node_name = analyst_nodes[analyst_key][0]
        workflow.add_edge(node_name, "risk_management_agent")

    workflow.add_edge("risk_management_agent", "portfolio_manager")
    workflow.add_edge("portfolio_manager", END)

    workflow.set_entry_point("start_node")
    return workflow


def main():
    inputs = parse_cli_inputs(
        description="Run the hedge fund trading system",
        require_tickers=True,
        default_months_back=None,
        include_graph_flag=True,
        include_reasoning_flag=True,
    )

    tickers = inputs.tickers
    selected_analysts = inputs.selected_analysts

    # 1. 初始化你封装的 Trader
    trader = AlpacaTrader()
    clock = trader.client.get_clock()
    if not clock.is_open:
        print(f"休市中。下次开盘时间: {clock.next_open}")
        return  
    
    # 2. 获取实时持仓覆盖配置
    raw_live_data = trader.get_live_portfolio()

    portfolio = align_portfolio(raw_live_data, tickers, inputs.margin_requirement)

    result = run_hedge_fund(
        tickers=tickers,
        start_date=inputs.start_date,
        end_date=inputs.end_date,
        portfolio=portfolio,
        show_reasoning=inputs.show_reasoning,
        selected_analysts=inputs.selected_analysts,
        model_name=inputs.model_name,
        model_provider=inputs.model_provider,
    )
    
    print_trading_output(result)
    #print(result)

    # 实例化 logger
    t_logger = TradingLogger()
    t_logger.log_trade_table(result)

    decisions = result.get('decisions', {})
    if not decisions:
        print(f"{Fore.YELLOW}No decisions generated by the AI.{Style.RESET_ALL}")
        return 
    # 最后的确认步骤：如果是生产环境定时跑，建议加上 try-except 保护
    try:
        print(f"\n{Fore.CYAN}--- 准备进入执行阶段 ---{Style.RESET_ALL}")
        trader.execute_decisions(decisions)
        print(f"{Fore.GREEN}✅ 定时交易任务执行完毕。{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}❌ 执行阶段发生严重错误: {e}{Style.RESET_ALL}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"🔥 程序发生未捕获异常: {e}")
        sys.exit(1)