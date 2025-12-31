import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

class Cache:
    """
    持久化 JSON 缓存系统。
    - 价格 (Prices): 5 分钟失效，确保交易决策使用最新数据。
    - 财务数据 (Financials): 12 小时失效，确保单次运行内 0 成本共享。
    - 其他数据 (News/Insider): 24 小时失效。
    """

    def __init__(self, cache_filename="api_cache.json"):
        # 路径设置：自动定位到 src/database
        base_dir = Path(__file__).resolve().parent.parent # 指向 src/
        self.db_dir = base_dir / "database"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.db_dir / cache_filename

        # 初始化数据结构
        self._data = {
            "prices": {},
            "financial_metrics": {},
            "line_items": {},
            "insider_trades": {},
            "company_news": {},
            "timestamps": {}  # 格式: {"category_ticker": "iso_timestamp"}
        }

        self._load_from_disk()

    def _load_from_disk(self):
        """启动时从硬盘加载"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    disk_data = json.load(f)
                    self._data.update(disk_data)
                print(f"✅ 缓存加载成功：已读取 {len(self._data['timestamps'])} 条历史记录")
            except Exception as e:
                print(f"⚠️ 缓存文件读取失败，将重新创建: {e}")

    def _save_to_disk(self):
        """数据更新时同步写入硬盘"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"❌ 缓存保存失败: {e}")

    def _is_expired(self, ticker: str, category: str, hours: int = 0, minutes: int = 0) -> bool:
        """检查数据是否过期"""
        key = f"{category}_{ticker}"
        last_saved = self._data["timestamps"].get(key)
        
        if not last_saved:
            return True
        
        saved_time = datetime.fromisoformat(last_saved)
        # 如果当前时间超过了 存储时间 + 有效时长，则返回 True (已过期)
        return datetime.now() > saved_time + timedelta(hours=hours, minutes=minutes)

    # --- 对外接口 (与 api.py 对接) ---

    def get_prices(self, ticker: str):
        # 价格设置为 5 分钟有效，满足 main.py 运行周期内各 Agent 共享
        if self._is_expired(ticker, "prices", minutes=5):
            return None
        return self._data["prices"].get(ticker)

    def set_prices(self, ticker: str, data: list):
        self._data["prices"][ticker] = data
        self._data["timestamps"][f"prices_{ticker}"] = datetime.now().isoformat()
        self._save_to_disk()

    def get_financial_metrics(self, ticker: str):
        # 财务指标 12 小时有效，跨日自动刷新
        if self._is_expired(ticker, "financial_metrics", hours=12):
            return None
        return self._data["financial_metrics"].get(ticker)

    def set_financial_metrics(self, ticker: str, data: list):
        self._data["financial_metrics"][ticker] = data
        self._data["timestamps"][f"financial_metrics_{ticker}"] = datetime.now().isoformat()
        self._save_to_disk()

    def get_line_items(self, ticker: str):
        if self._is_expired(ticker, "line_items", hours=12):
            return None
        return self._data["line_items"].get(ticker)

    def set_line_items(self, ticker: str, data: list):
        self._data["line_items"][ticker] = data
        self._data["timestamps"][f"line_items_{ticker}"] = datetime.now().isoformat()
        self._save_to_disk()

    def get_insider_trades(self, ticker: str):
        # 内部交易和新闻 24 小时更新即可
        if self._is_expired(ticker, "insider_trades", hours=24):
            return None
        return self._data["insider_trades"].get(ticker)

    def set_insider_trades(self, ticker: str, data: list):
        self._data["insider_trades"][ticker] = data
        self._data["timestamps"][f"insider_trades_{ticker}"] = datetime.now().isoformat()
        self._save_to_disk()

    def get_company_news(self, ticker: str):
        if self._is_expired(ticker, "company_news", hours=24):
            return None
        return self._data["company_news"].get(ticker)

    def set_company_news(self, ticker: str, data: list):
        self._data["company_news"][ticker] = data
        self._data["timestamps"][f"company_news_{ticker}"] = datetime.now().isoformat()
        self._save_to_disk()

# 全局单例
_cache = Cache()

def get_cache() -> Cache:
    """获取全局唯一的缓存实例"""
    return _cache