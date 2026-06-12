# DeepSeek4Free Bridge v6.0 — Claude Code + Review Workflow

Use Claude Code as a full autonomous coding agent (like Cursor) backed by your cloud-hosted DeepSeek LLM, with a **human-in-the-loop review system** for every file change.

---

## What's new in v6.0

| Feature | v5 | v6 |
|---|---|---|
| File write/edit review prompt | ❌ | ✅ |
| Bash command review prompt | ❌ | ✅ |
| Colored diff before every change | ❌ | ✅ |
| Accept / Reject / Modify / Accept-All | ❌ | ✅ |
| Project analysis on startup | ❌ | ✅ |
| Full file tree injected into LLM context | ❌ | ✅ |
| Tech stack auto-detection | ❌ | ✅ |
| Missing files detection (.env, README…) | ❌ | ✅ |
| Change log / rollback tracking | ❌ | ✅ |
| `/rescan` command mid-session | ❌ | ✅ |

---

## Prerequisites

- **Python 3.9+**
- **Node.js** (Required for the stable Proof-of-Work solver on macOS/Linux)

---

## Setup

### 🚀 Quick Start (Automated)

Simply run the launcher script for your platform. It will automatically:
1. Kill any stale processes on port 8000.
2. Create and activate a Python virtual environment (`venv`).
3. Install/update all required dependencies.
4. Set up your `.env` configuration and prompt you for your DeepSeek token if missing.
5. Start the DeepSeek Bridge in the background.
6. Connect and launch Claude Code in your terminal.

#### macOS & Linux:
```bash
./start_claude.sh
```

#### Windows:
```cmd
start_claude.bat
```

---

### 🛠️ Manual Setup
   ```
   bridge.py
   profiles.json
   .env.example  →  rename to  .env
   ```

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Get your Auth Token:**
   - Go to [chat.deepseek.com](https://chat.deepseek.com/) and log in.
   - Open your browser's **Developer Tools** (Right-click -> Inspect -> Console).
   - Paste the following command and press Enter:
     ```javascript
     console.log(JSON.parse(localStorage.getItem('user_token')).value)
     ```
   - Copy the long string that appears (it starts with `eyJ...`).

4. **Fill in `.env`:**
   - Paste your token into the `.env` file:
     ```env
     DEEPSEEK_AUTH_TOKEN="your_token_pasted_here"
     MAX_CONTEXT_CHARS=100000
     ```

4. **Run the bridge:**
   ```bash
   python bridge.py
   ```

5. **Pair with Claude Code:**
   Open a **new terminal**, navigate to your project directory, and run:

   **Linux / Mac / WSL:**
   ```bash
   export ANTHROPIC_BASE_URL='http://localhost:8000'
   export ANTHROPIC_API_KEY='sk-fake'
   claude
   ```

   **Windows PowerShell:**
   ```powershell
   $env:ANTHROPIC_BASE_URL='http://localhost:8000'
   $env:ANTHROPIC_API_KEY='sk-fake'
   claude
   ```

---

## Features

- **Stable PoW**: Uses a Node.js-based solver bridge to prevent memory crashes on macOS.
- **Large Context**: Supports up to **100,000 characters** for full project analysis.
- **Deep Think**: Every response automatically includes the model's reasoning process.
- **Tool Translation**: Seamlessly translates Claude Code's Anthropic tool calls (Write, Edit, Bash) to DeepSeek.

---

## Configuration (`.env`)

```env
REVIEW_MODE=always           # always | on_complex | off
AUTO_ACCEPT_READS=true       # auto-pass Read/ListDir/Grep without prompting
PROJECT_SCAN_ON_START=true   # scan project on bridge startup
MAX_CONTEXT_CHARS=100000     # increased for complex project analysis
```