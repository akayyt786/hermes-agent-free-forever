# DeepSeek4Free Bridge — Setup Guide

## Step 1: Install Dependencies

```bash
cd deepseek4free
pip install -r requirements.txt
pip install uvicorn fastapi python-dotenv
```

## Step 2: Get Your DeepSeek Token

1. Go to [chat.deepseek.com](https://chat.deepseek.com) → log in
2. Open DevTools (`F12`) → Console → paste:
   ```js
   JSON.parse(localStorage.getItem("userToken")).value
   ```
3. Copy the token

## Step 3: Configure `.env`

```env
DEEPSEEK_AUTH_TOKEN="your_token_here"

# Optional tuning
BRIDGE_PORT=8000
MIN_DELAY_SECONDS=1.0     # Anti-ban: min wait between requests
MAX_JITTER_SECONDS=1.0    # Anti-ban: random extra delay
MAX_RETRIES=2              # Auto-retry on transient errors
```

## Step 4: Start the Bridge

```bash
python bridge.py
```

It auto-kills anything on port 8000 before starting. No more `Errno 10048`.

## Step 5: Connect Claude Code

```bash
claude config set --global apiBaseUrl http://localhost:8000/v1
```

Or in Claude Code settings:
- **Base URL**: `http://localhost:8000/v1`
- **API Key**: `any-string-works`
- **Model**: `deepseek-chat`

## Available Models

| Model | Thinking | Web Search |
|---|---|---|
| `deepseek-chat` | No | No |
| `deepseek-chat-search` | No | Yes |
| `deepseek-reasoner` / `deepseek-r1` | Yes | No |
| `deepseek-r1-search` | Yes | Yes |

## Anti-Ban Tips

- Keep `MIN_DELAY_SECONDS >= 1.0`
- If rate-limited, increase to `3.0`
- Don't exceed ~30 requests/hour
- Run `python -m dsk.bypass` if Cloudflare blocks you

## Using with Python

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="x")

# Standard
r = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True
)
for chunk in r:
    print(chunk.choices[0].delta.content or "", end="")

# With thinking
r = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Solve 17*23"}],
    stream=True
)

# With web search
r = client.chat.completions.create(
    model="deepseek-chat-search",
    messages=[{"role": "user", "content": "Latest AI news?"}],
    stream=True
)
```
