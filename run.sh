#!/usr/bin/env bash
# Intensive Vibe Coding Capstone Project: Relay — launch the backend wired to Google Gemini (OpenAI-compatible endpoint).
#
# 1) Get a key:  https://aistudio.google.com/apikey
# 2) Put it in your shell (NOT in this file):
#       export RELAY_LLM_API_KEY=AIza...
# 3) Run:  ./run.sh
#
# Override the model with:  RELAY_LLM_MODEL=gemini-2.5-pro ./run.sh
set -euo pipefail

export RELAY_LLM_PROVIDER=openai   # Gemini speaks the OpenAI-compatible protocol
export RELAY_LLM_MODEL="${RELAY_LLM_MODEL:-gemini-2.5-flash}"
export RELAY_LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"

if [ -z "${RELAY_LLM_API_KEY:-}" ]; then
  echo "⚠  RELAY_LLM_API_KEY not set — running OFFLINE (fixtures + safe templates)."
  echo "   Set it for the live Reconciler:  export RELAY_LLM_API_KEY=AIza..."
fi

exec uvicorn backend.app.main:app --reload
