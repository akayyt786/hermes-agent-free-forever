# Prompt to Generate a Step-by-Step CLAUDE.md

Copy-paste the prompt below into Claude Code (or any AI). Replace the parts in [BRACKETS] with your project details.

---

## THE PROMPT:

```
Create a CLAUDE.md file for my project with step-by-step task execution.

PROJECT: [describe what you want to build/convert]
SOURCE FILES: [list your source files, e.g. "14 HTML files in the root folder"]
TARGET: [what you want to convert them into, e.g. "Flutter Android app" or "React Native app" or "Next.js website"]
OUTPUT FOLDER: [e.g. "driver_app/" or "my_app/"]

RULES FOR THE CLAUDE.md:
1. Break the ENTIRE project into small numbered tasks (Task 1, Task 2, Task 3...)
2. Each task must be ONE small action (setup project, convert 1 file, add dependencies, etc.)
3. After each task, Claude must STOP and say "✅ Task X done. Say 'next' to continue."
4. Claude must NOT jump ahead or do multiple tasks at once
5. Include validation after each conversion (lint, analyze, build check)
6. The last line must say "## CURRENT TASK: 1"
7. Keep the ENTIRE file under 100 lines (short and compact)
8. List source→target file mappings in a simple table
9. Include a progress checklist that gets updated as tasks complete

The workflow is: I say "start" → Claude does Task 1 → stops → I say "next" → Claude does Task 2 → stops → repeat until done.

Here are my source files:
[LIST YOUR FILES HERE, e.g:]
- splash-screen.html → splash_screen.dart
- login.html → login_screen.dart
- dashboard.html → dashboard_screen.dart
```

---

## EXAMPLE USAGE:

### For HTML → Flutter conversion:
```
Create a CLAUDE.md file for my project with step-by-step task execution.

PROJECT: Convert HTML mockups to Flutter Android app
SOURCE FILES: 14 HTML files in root folder  
TARGET: Flutter Android app
OUTPUT FOLDER: driver_app/

[paste the rules above]

Source files: splash-screen.html, login.html, driver-dashboard-1.html...
```

### For React → Next.js migration:
```
Create a CLAUDE.md file for my project with step-by-step task execution.

PROJECT: Migrate React CRA app to Next.js 14
SOURCE FILES: 8 React components in src/components/
TARGET: Next.js 14 app with App Router
OUTPUT FOLDER: ./

[paste the rules above]

Source files: Header.jsx, Footer.jsx, Dashboard.jsx...
```

### For building a new API:
```
Create a CLAUDE.md file for my project with step-by-step task execution.

PROJECT: Build a REST API with Node.js + Express + MongoDB
SOURCE FILES: None (building from scratch)
TARGET: Express API with 6 endpoints
OUTPUT FOLDER: api/

[paste the rules above]

Endpoints: /auth/login, /auth/register, /users, /posts, /comments, /upload
```
