cd /d %~dp0
echo [%date% %time%] Start risk manager... 
:: 使用 poetry 运行脚本
set PYTHONUTF8=1
poetry run python src/risk_manager.py
echo [%date% %time%] Mission completed