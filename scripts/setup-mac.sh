#!/bin/bash
# ─────────────────────────────────────────────
# Samantha OS — Mac Setup Script
# Run this once on your Mac Mini M4 Pro
# ─────────────────────────────────────────────

set -e

echo "🌸 Setting up Samantha OS..."
echo ""

# Colors
PEACH='\033[38;2;232;160;135m'
RESET='\033[0m'

step() { echo -e "${PEACH}→${RESET} $1"; }

# ─── Check prerequisites ───
step "Checking prerequisites..."

if ! command -v brew &> /dev/null; then
  echo "❌ Homebrew not found. Install from https://brew.sh"
  exit 1
fi

if ! command -v docker &> /dev/null; then
  step "Installing Docker Desktop..."
  brew install --cask docker
  echo "⚠️  Please start Docker Desktop and run this script again."
  exit 0
fi

# Check Docker is running
if ! docker info &> /dev/null 2>&1; then
  echo "⚠️  Docker Desktop is not running. Please start it and try again."
  exit 1
fi

# ─── Install Ollama ───
if ! command -v ollama &> /dev/null; then
  step "Installing Ollama..."
  brew install ollama
fi

# ─── Pull models ───
step "Pulling LLM models (this may take a while on first run)..."

# Start ollama if not running
if ! pgrep -x "ollama" > /dev/null; then
  ollama serve &
  sleep 3
fi

ollama pull llama3.2:3b 2>/dev/null || true
step "Pulled llama3.2:3b (fast conversational model)"

# Optional: larger model for complex queries
# ollama pull llama3.1:8b

# ─── Install PortAudio (for mic access) ───
step "Installing PortAudio..."
brew install portaudio 2>/dev/null || true

# ─── Build and start services ───
step "Building Docker services..."
docker compose build

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${PEACH}  🌸 Samantha is ready.${RESET}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Start Samantha:"
echo "    1. Make sure Ollama is running:  ollama serve"
echo "    2. Start services:               docker compose up"
echo "    3. Open the shell:               open http://localhost:3333"
echo ""
echo "  Dev mode:"
echo "    • Type in the text box to chat (no mic needed)"
echo "    • Hold SPACE for push-to-talk (needs mic permission)"
echo ""
echo "  Services:"
echo "    • Visual Shell:  http://localhost:3333"
echo "    • Orchestrator:  http://localhost:8000/health"
echo "    • STT:           http://localhost:8001/health"
echo "    • TTS:           http://localhost:8002/health"
echo ""
