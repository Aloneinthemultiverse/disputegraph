@echo off
REM DisputeGraph demo: no credentials needed (replays cached sandbox data)
pip install -q -r requirements.txt
set DEMO_MODE=1
echo Open http://localhost:8000
python -m uvicorn backend.app:app --port 8000
