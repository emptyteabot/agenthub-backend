@echo off
echo ==================================================
echo  AgentHub Multi-Agent Platform - Launching Engine
echo ==================================================
set MOCK_MODE=true
set LLM_DRIVER=mock
python -m pip install -e .
python -m uvicorn app.main:app --reload --port 8000
pause
