#!/bin/bash

# DeepSeek4Free Bridge - macOS/Linux Claude Code Launcher
# Colors for beautiful output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0;0m' # No Color
BOLD='\033[1m'

echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}   Claude Code + DeepSeek Bridge Launcher  ${NC}"
echo -e "${BLUE}==========================================${NC}\n"

# 1. Kill old processes on port 8000
echo -e "${YELLOW}[1/6] Cleaning up old processes on port 8000...${NC}"
PORT_PID=$(lsof -t -i:8000)
if [ ! -z "$PORT_PID" ]; then
    echo -e "      Found process $PORT_PID running on port 8000. Killing it..."
    kill -9 $PORT_PID 2>/dev/null
fi

# 2. Check/Setup virtual environment
echo -e "${YELLOW}[2/6] Setting up Python virtual environment...${NC}"
if [ ! -d "venv" ]; then
    echo -e "      Creating virtual environment 'venv'..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# 3. Install/Update dependencies
echo -e "${YELLOW}[3/6] Installing/verifying dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# 4. Check & configure .env file
echo -e "${YELLOW}[4/6] Configuring environment variables...${NC}"
if [ ! -f ".env" ]; then
    echo -e "      .env not found. Copying from .env.example..."
    cp .env.example .env
fi

# Check for DEEPSEEK_AUTH_TOKEN in .env
TOKEN_VAL=$(grep -E "^DEEPSEEK_AUTH_TOKEN=" .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
if [ -z "$TOKEN_VAL" ] || [ "$TOKEN_VAL" = "your_token_here" ]; then
    echo -e "${RED}      DEEPSEEK_AUTH_TOKEN is not configured in .env!${NC}"
    echo -e "      To get your token:"
    echo -e "      1. Go to chat.deepseek.com and log in."
    echo -e "      2. Open Developer Tools (F12) -> Console, and run:"
    echo -e "         ${BOLD}console.log(JSON.parse(localStorage.getItem('user_token')).value)${NC}"
    echo -e "      3. Copy the token."
    echo -e ""
    read -p "      Please enter your DeepSeek token: " USER_TOKEN
    if [ ! -z "$USER_TOKEN" ]; then
        # Replace line in .env
        python3 -c "
import os
token = '''${USER_TOKEN}'''.strip()
with open('.env', 'r') as f:
    lines = f.readlines()
with open('.env', 'w') as f:
    for line in lines:
        if line.startswith('DEEPSEEK_AUTH_TOKEN='):
            f.write(f'DEEPSEEK_AUTH_TOKEN=\"{token}\"\n')
        else:
            f.write(line)
"
        echo -e "${GREEN}      Token saved to .env!${NC}"
    else
        echo -e "${YELLOW}      Proceeding without updating token...${NC}"
    fi
fi

# 5. Start the bridge in the background
echo -e "${YELLOW}[5/6] Starting the DeepSeek Bridge...${NC}"
python3 bridge.py > /dev/null 2>&1 &
BRIDGE_PID=$!

# Register cleanup function to kill the bridge on exit
cleanup() {
    echo -e "\n${YELLOW}Stopping DeepSeek Bridge (PID: $BRIDGE_PID)...${NC}"
    kill $BRIDGE_PID 2>/dev/null
    exit
}
trap cleanup EXIT INT TERM

# Wait for bridge to start and verify health
echo -e "      Waiting for bridge to spin up..."
for i in {1..10}; do
    if curl -s http://localhost:8000/health > /dev/null; then
        echo -e "${GREEN}      Bridge is HEALTHY and running on PID $BRIDGE_PID.${NC}"
        break
    fi
    if [ $i -eq 10 ]; then
        echo -e "${RED}      WARNING: Bridge may not have started properly. Proceeding anyway...${NC}"
    fi
    sleep 1
done

# 6. Configure environment and launch Claude Code
echo -e "${YELLOW}[6/6] Launching Claude Code...${NC}"
export ANTHROPIC_BASE_URL="http://localhost:8000"
export ANTHROPIC_API_KEY="sk-ant-api03-fakekey-for-bridge-00000000000000000000000000000000000000000000000000000000000000000000"
export DISABLE_AUTOUPDATE=1

echo -e "${GREEN}==========================================${NC}"
echo -e "  Ready! Starting Claude Code.  "
echo -e "  To exit, simply type 'exit' or press Ctrl+C."
echo -e "${GREEN}==========================================${NC}\n"

# Run Claude Code
if command -v claude &> /dev/null; then
    claude
else
    echo -e "${YELLOW}claude command not found globally, launching via npx...${NC}"
    npx @anthropic-ai/claude
fi
