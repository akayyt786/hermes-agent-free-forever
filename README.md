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

## Setup

1. **Copy files** into your bridge directory (next to `dsk/`):
   ```
   bridge.py
   profiles.json
   .env.example  →  rename to  .env
   ```

2. **Fill in `.env`:**
   ```
   DEEPSEEK_AUTH_TOKEN=your_token_here
   ```

3. **Run the bridge:**
   ```bash
   python bridge.py
   ```

4. **Open a new terminal, cd to your project, start Claude Code:**
   ```powershell
   # Windows PowerShell
   $env:ANTHROPIC_BASE_URL='http://localhost:8000'
   $env:ANTHROPIC_API_KEY='sk-fake'
   claude

   # Linux / Mac
   export ANTHROPIC_BASE_URL='http://localhost:8000'
   export ANTHROPIC_API_KEY='sk-fake'
   claude
   ```

---

## How the Review Workflow Works

Every time the LLM tries to **write a file, edit a file, or run a bash command**, the bridge **pauses** and shows you exactly what it wants to do in your terminal:

```
══════════════════════════════════════════════════════════════
  🔍  REVIEW REQUIRED — 2 proposed change(s)
══════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────
│  PROPOSED CHANGE  [1/2]   Tool: Write
└─────────────────────────────────────────────────────────────
  Action  : CREATE
  File    : src/routes/auth.js
  Size    : 1,240 chars

  NEW FILE CONTENT (first 80 lines):
     1  const express = require('express');
     2  const router = express.Router();
  ...

  What would you like to do?
    [y] Accept       — execute this change
    [n] Reject       — skip this change
    [m] Modify       — edit the input before executing
    [a] Accept All   — accept this and all future changes this session
    [s] Skip All     — reject this and all future changes this session

  Choice [y/n/m/a/s] >
```

For **edit operations**, you see a full **colored diff** (red = removed, green = added).

For **bash commands**, you see the exact command before it runs.

---

## Project Analysis

On startup, the bridge scans your project and prints:

```
╔══════════════════════════════════════════════════════════╗
║              PROJECT ANALYSIS COMPLETE                   ║
╚══════════════════════════════════════════════════════════╝
  Root      : /home/user/myproject
  Files     : 47 files (312.4 KB)
  Stack     :
              ✓ Node.js / JavaScript (package.json)
              ✓ TypeScript (detected by .ts files: 23)
  Dep Files : package.json
  Entrypts  : src/index.ts
  Missing   :
              ⚠  .env file
              ⚠  .env.example template
```

This full file tree and stack info is **automatically injected into every LLM prompt**, so the model knows your whole project before making any change.

---

## Commands (type in Claude Code chat)

| Command | What it does |
|---|---|
| `/review` | Also runs an LLM self-review pass before showing you the diff |
| `/rescan` | Re-scans the project directory (useful after adding files manually) |
| `/persona architect` | Switches to architect mode (plans before coding) |
| `/persona debugger` | Switches to debugger mode (surgical bug fixes) |
| `/persona tester` | Switches to test-writer mode |
| `/persona reviewer` | Switches to code review mode |

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Bridge status + review stats |
| `GET /project` | Full project analysis report (JSON) |
| `POST /project/rescan` | Re-trigger project scan |
| `GET /review/log` | All accepted changes (for rollback reference) |
| `GET /review/status` | Current review session flags |
| `POST /review/reset` | Reset accept-all / skip-all flags |

---

## Configuration (`.env`)

```env
REVIEW_MODE=always          # always | on_complex | off
AUTO_ACCEPT_READS=true      # auto-pass Read/ListDir/Grep without prompting
PROJECT_SCAN_ON_START=true  # scan project on bridge startup
MAX_CONTEXT_CHARS=60000     # context window limit
```