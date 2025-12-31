import logging
import sys
import io
import json
from pathlib import Path
from tabulate import tabulate

# 强制 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

class TradingLogger:
    def __init__(self):
        current_file_dir = Path(__file__).resolve().parent
        # 如果 main.py 在根目录，database 就在根目录；如果在 src，就在 src/database
        base_dir = current_file_dir.parent
        self.db_dir = base_dir / "database"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 汇总日志 (Summary Table)
        self.summary_logger = self._setup_logger('summary', self.db_dir / "trading_summary.log")
        # 2. 细节日志 (Raw Reasoning)
        self.details_logger = self._setup_logger('details', self.db_dir / "agent_details.log")

    def _setup_logger(self, name, log_file):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            # 汇总日志不需要每行都打时间戳，表格顶部打一次即可
            file_formatter = logging.Formatter('%(asctime)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(logging.Formatter('%(message)s'))
            
            logger.addHandler(file_handler)
        return logger

    def log_trade_table(self, result_sample):
        """
        解析 result 字典并生成表格，同时记录详细 Agent 日志
        """
        decisions = result_sample.get('decisions', {})
        analyst_signals = result_sample.get('analyst_signals', {})
        
        if not decisions:
            self.summary_logger.info("本次运行无决策结果。")
            return

        tickers = list(decisions.keys())
        agent_names = list(analyst_signals.keys())

        # ==========================================
        # 1. 写入汇总表格 (Summary Logger)
        # ==========================================
        headers = ["Ticker", "Action", "Quantity", "Confidence"]
        for agent in agent_names:
            short_name = agent.replace('_agent', '').replace('_analyst', '')
            headers.append(f"{short_name}_sign")
            headers.append(f"{short_name}_conf")

        table_data = []
        for ticker in tickers:
            dec = decisions[ticker]
            row = [ticker, dec['action'].upper(), dec['quantity'], f"{dec['confidence']}%"]
            for agent in agent_names:
                sig_data = analyst_signals[agent].get(ticker, {})
                row.append(sig_data.get('signal', 'N/A').capitalize())
                row.append(f"{sig_data.get('confidence', 0):.1f}%")
            table_data.append(row)

        table_str = tabulate(table_data, headers=headers, tablefmt="grid", numalign="center", stralign="center")
        self.summary_logger.info("\n" + table_str)

        # ==========================================
        # 2. 写入详细细节 (Details Logger) - 补充这部分
        # ==========================================
        for ticker in tickers:
            # 记录该 Ticker 的总决策
            self.details_logger.info(f"\n{'='*20} {ticker} 详细决策分析 {'='*20}")
            self.details_logger.info(f"最终动作: {decisions[ticker]['action'].upper()}")
            self.details_logger.info(f"下单数量: {decisions[ticker]['quantity']}")
            self.details_logger.info(f"置信度: {decisions[ticker]['confidence']}%")
            self.details_logger.info(f"综合结论逻辑: {decisions[ticker]['reasoning']}")
            
            self.details_logger.info(f"\n--- 各 Agent 分析细节 ---")
            
            # 遍历所有参与的 Agent，记录它们的原始输出
            for agent in agent_names:
                agent_res = analyst_signals[agent].get(ticker, {})
                sig = agent_res.get('signal', 'N/A').upper()
                conf = agent_res.get('confidence', 0)
                reason = agent_res.get('reasoning', "无详细理由")

                # 如果 reasoning 是字典（比如你提供的样本中 sentiment_analyst_agent 的结构）
                # 我们将其转为格式化的 JSON 字符串存入，方便查看数据指标
                if isinstance(reason, dict):
                    reason_str = json.dumps(reason, indent=4, ensure_ascii=False)
                else:
                    reason_str = str(reason)

                log_entry = (
                    f"[{agent}]\n"
                    f"  方向: {sig}\n"
                    f"  强度: {conf}%\n"
                    f"  详细推理: {reason_str}\n"
                )
                self.details_logger.info(log_entry)
            
            self.details_logger.info(f"{'='*60}\n")