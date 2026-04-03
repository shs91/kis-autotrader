#!/bin/bash
# KIS 자동매매 — 대시보드 실행
cd "$(dirname "$0")/.."
.venv/bin/streamlit run dashboard/app.py \
    --server.port 8501 \
    --server.headless true \
    --browser.gatherUsageStats false
