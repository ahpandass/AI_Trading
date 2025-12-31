@echo off
:: 1. 强制当前命令行窗口使用 UTF-8 编码 (65001)
chcp 65001 >nul

cd /d %~dp0
echo [%date% %time%] Start trading system... >> trading_log.txt
:: 使用 poetry 运行脚本并记录日志
set PYTHONUTF8=1
poetry run python src/main.py --ticker AAPL,MSFT,NVDA,TSLA >> trading_log.txt 2>&1
echo [%date% %time%] Mission completed >> trading_log.txt