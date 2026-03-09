"""
DeepSeek4Free Bridge v5.0
=========================
Professional-grade bridge with full Anthropic API compatibility for Claude Code.
Routes all Claude Code requests through DeepSeek with enhanced capabilities.

Features:
  - Full Anthropic Messages API (/v1/messages) with ALL tool support
  - OpenAI API  : /v1/chat/completions (streaming + non-streaming)
  - Professional system prompt for coding agent behavior
  - Smart context management (bypass token limits)
  - Forced deep-think + web-search on every request
  - Session caching / pooling for instant responses
  - Request logging for debugging
  - Auto port-kill on startup
  - Retry with backoff on transient errors
  - Request serialization (anti-ban, no artificial delay)
"""

import os
import sys
import json
import time
import uuid
import asyncio
import random
import signal
import socket
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

import re

# ─── Bootstrap ────────────────────────────────────────────────────────────────

_base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_base_dir, '.env'))

sys.path.insert(0, _base_dir)
from dsk.api import (
    DeepSeekAPI, AuthenticationError, RateLimitError,
    NetworkError, APIError, CloudflareError
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("bridge")

# ─── Config ───────────────────────────────────────────────────────────────────

AUTH_TOKEN         = os.getenv("DEEPSEEK_AUTH_TOKEN", "")
BRIDGE_PORT        = int(os.getenv("BRIDGE_PORT", 8000))
BRIDGE_HOST        = os.getenv("BRIDGE_HOST", "0.0.0.0")
MAX_RETRIES        = int(os.getenv("MAX_RETRIES", "3"))
SESSION_POOL_SIZE  = int(os.getenv("SESSION_POOL_SIZE", "3"))
MAX_CONTEXT_CHARS  = int(os.getenv("MAX_CONTEXT_CHARS", "30000"))
LOG_REQUESTS       = os.getenv("LOG_REQUESTS", "true").lower() == "true"

# ─── Personas & Profiles ──────────────────────────────────────────────────────

_profiles = {}
_profiles_path = os.path.join(_base_dir, "profiles.json")

def load_profiles():
    global _profiles
    if os.path.exists(_profiles_path):
        try:
            with open(_profiles_path, "r", encoding="utf-8") as f:
                _profiles = json.load(f)
            log.info(f"[Profiles] Loaded {len(_profiles)} personas from profiles.json")
        except Exception as e:
            log.error(f"[Profiles] Failed to load profiles.json: {e}")
            _profiles = {"default": "You are a helpful coding assistant."}
    else:
        _profiles = {"default": "You are a helpful coding assistant."}

load_profiles()

def get_system_prompt(persona: str = "default") -> str:
    return _profiles.get(persona, _profiles.get("default", "You are an expert software engineer."))

# ─── Stats Tracker ────────────────────────────────────────────────────────────

class BridgeStats:
    def __init__(self):
        self.start_time = time.time()
        self.request_count = 0
        self.error_count = 0
        self.tool_calls_parsed = 0
        self.total_response_time = 0.0
        self.context_truncations = 0

    @property
    def uptime(self) -> str:
        s = int(time.time() - self.start_time)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{h}h {m}m {s}s"

    @property
    def avg_response_time(self) -> float:
        if self.request_count == 0:
            return 0.0
        return round(self.total_response_time / self.request_count, 2)

stats = BridgeStats()

# ─── Request Logger ───────────────────────────────────────────────────────────

_log_dir = os.path.join(_base_dir, "logs")

def log_request(endpoint: str, prompt: str, response_summary: str = ""):
    """Log request details for debugging."""
    if not LOG_REQUESTS:
        return
    try:
        os.makedirs(_log_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(_log_dir, f"req_{ts}_{uuid.uuid4().hex[:6]}.json")
        with open(fname, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": ts,
                "endpoint": endpoint,
                "prompt_length": len(prompt),
                "prompt_preview": prompt[:500] + "..." if len(prompt) > 500 else prompt,
                "response_summary": response_summary[:300] if response_summary else ""
            }, f, indent=2)
    except Exception as e:
        log.warning(f"[Log] Failed to write request log: {e}")

# ─── Session Cache ────────────────────────────────────────────────────────────

class SessionManager:
    """
    Caches DeepSeekAPI instances and chat session IDs.
    - Reuses the API object (avoids re-init overhead)
    - Pre-creates a pool of sessions for instant use
    """
    def __init__(self, token: str, pool_size: int = SESSION_POOL_SIZE):
        self._token = token
        self._api: Optional[DeepSeekAPI] = None
        self._session_pool: list = []
        self._pool_size = pool_size
        self._lock = asyncio.Lock()

    def _get_api(self) -> DeepSeekAPI:
        if self._api is None:
            if not self._token:
                raise HTTPException(status_code=500, detail="DEEPSEEK_AUTH_TOKEN not set.")
            self._api = DeepSeekAPI(self._token)
            log.info("[Session] API client initialized")
        return self._api

    async def get_session(self) -> tuple:
        """Returns (api, chat_session_id). Uses a cached session if available."""
        async with self._lock:
            api = self._get_api()
            if self._session_pool:
                sid = self._session_pool.pop(0)
                log.info(f"[Session] Reusing cached session {sid[:12]}...")
            else:
                sid = api.create_chat_session()
                log.info(f"[Session] Created new session {sid[:12]}...")
            return api, sid

    async def refill_pool(self):
        """Background task to keep sessions pre-created."""
        try:
            async with self._lock:
                api = self._get_api()
                while len(self._session_pool) < self._pool_size:
                    sid = api.create_chat_session()
                    self._session_pool.append(sid)
                    log.info(f"[Pool] Pre-created session {sid[:12]}...")
        except Exception as e:
            log.warning(f"[Pool] Failed to pre-create session: {e}")

    def reset(self):
        """Reset API client (e.g. after auth failure)."""
        self._api = None
        self._session_pool.clear()
        log.info("[Session] Client reset")


session_mgr = SessionManager(AUTH_TOKEN)

# ─── Request Serializer (anti-ban) & Memory Cache ─────────────────────────

_req_lock = asyncio.Lock()
_session_history_map = {}  # prompt_hash -> (chat_session_id, parent_message_id)

async def serialize_request():
    """Acquire lock so only one request runs at a time."""
    await _req_lock.acquire()

# ─── Model Config — Always Deep Think + Search ───────────────────────────────

# All models now force thinking=True, search=True for maximum quality
MODELS = {
    # DeepSeek aliases
    "deepseek-chat":            (True, True),
    "deepseek-chat-search":     (True, True),
    "deepseek-reasoner":        (True, True),
    "deepseek-reasoner-search": (True, True),
    "deepseek":                 (True, True),
    "deepseek-v3":              (True, True),
    "deepseek-r1":              (True, True),
    "deepseek-r1-search":       (True, True),
    # Claude aliases (so Claude Code's model names work seamlessly)
    "claude-3-5-sonnet-20241022": (True, True),
    "claude-3-5-haiku-20241022":  (True, True),
    "claude-3-opus-20240229":     (True, True),
    "claude-sonnet-4-20250514":   (True, True),
    "claude-sonnet-4-0":          (True, True),
}

# ─── Smart Context Management ─────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token estimation (~3 chars per token for English/code)."""
    return len(text) // 3

def truncate_message(text: str, max_chars: int = 10000) -> str:
    """Truncate a single message, preserving start and end."""
    if len(text) <= max_chars:
        return text
    keep = max_chars // 2
    return (
        text[:keep]
        + f"\n\n[... {len(text) - max_chars} characters truncated for context management ...]\n\n"
        + text[-keep:]
    )

def smart_context_compress(prompt: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """
    Compress a prompt to fit within token limits while preserving critical info.

    Strategy:
    1. Never truncate system prompt or tool instructions
    2. Preserve the most recent 3 message turns intact
    3. Compress older messages to summaries
    4. Truncate extremely long individual messages
    """
    if len(prompt) <= max_chars:
        return prompt

    stats.context_truncations += 1
    log.info(f"[Context] Prompt too long ({len(prompt)} chars > {max_chars}). Compressing...")

    # Split the prompt into sections by role markers
    sections = re.split(r'(\[(?:System|User|Assistant|TOOL INSTRUCTIONS|END TOOL INSTRUCTIONS)\])', prompt)

    # Rebuild: find system/tool sections vs conversation sections
    system_parts = []
    conversation_parts = []
    current_section = None

    i = 0
    while i < len(sections):
        part = sections[i]
        if part in ("[System]", "[TOOL INSTRUCTIONS]"):
            # System or tool instructions — always keep fully
            system_parts.append(part)
            if i + 1 < len(sections):
                system_parts.append(sections[i + 1])
                i += 2
            else:
                i += 1
        elif part in ("[User]", "[Assistant]"):
            conversation_parts.append(part)
            if i + 1 < len(sections):
                conversation_parts.append(sections[i + 1])
                i += 2
            else:
                i += 1
        elif part == "[END TOOL INSTRUCTIONS]":
            system_parts.append(part)
            if i + 1 < len(sections):
                system_parts.append(sections[i + 1])
                i += 2
            else:
                i += 1
        else:
            # Content without a header — probably a continuation
            if system_parts and not conversation_parts:
                system_parts.append(part)
            else:
                conversation_parts.append(part)
            i += 1

    system_text = "".join(system_parts)

    # Group conversation into message turns
    turns = []
    current_turn = []
    for part in conversation_parts:
        if part in ("[User]", "[Assistant]") and current_turn:
            turns.append("".join(current_turn))
            current_turn = [part]
        else:
            current_turn.append(part)
    if current_turn:
        turns.append("".join(current_turn))

    # Calculate budget
    remaining = max_chars - len(system_text)

    if len(turns) <= 10:
        # Few enough turns — just truncate each if needed
        compressed_turns = [truncate_message(t, remaining // max(len(turns), 1)) for t in turns]
    else:
        # Keep last 10 turns intact (or truncated), compress older ones
        recent_turns = turns[-10:]
        older_turns = turns[:-10]

        recent_budget = int(remaining * 0.8)  # 80% budget for recent context
        older_budget = remaining - recent_budget

        # Compress older turns
        compressed_older = []
        per_old = max(older_budget // max(len(older_turns), 1), 500)
        for t in older_turns:
            if len(t) > per_old:
                compressed_older.append(t[:per_old] + "\n[... truncated ...] ")
            else:
                compressed_older.append(t)

        # Keep recent turns
        compressed_recent = [truncate_message(t, recent_budget // 10) for t in recent_turns]

        compressed_turns = compressed_older + compressed_recent

    result = system_text + "\n\n" + "\n\n".join(compressed_turns)
    log.info(f"[Context] Compressed: {len(prompt)} → {len(result)} chars")
    return result

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="DeepSeek4Free Bridge", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    """Pre-warm session pool on startup."""
    if AUTH_TOKEN:
        asyncio.create_task(session_mgr.refill_pool())

# ─── Request / Response Models ────────────────────────────────────────────────

# (Models removed in favor of direct Request parsing for flexibility)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def openai_build_tool_instructions(tools: list) -> str:
    if not tools:
        return ""

    tool_defs = []
    for t in tools:
        if t.get("type") == "function":
            func = t.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            schema = func.get("parameters", {})
            props = schema.get("properties", {})
            required = schema.get("required", [])
            params = []
            for pname, pinfo in props.items():
                req = "(required)" if pname in required else "(optional)"
                pdesc = pinfo.get("description", pinfo.get("type", "string"))
                if len(str(pdesc)) > 60: pdesc = str(pdesc)[:60] + "..."
                params.append(f"    - {pname}: {pdesc} {req}")
            tool_desc = desc[:80] + "..." if len(desc) > 80 else desc
            tool_defs.append(f"  {name}: {tool_desc}\n" + "\n".join(params))

    return """
[TOOL INSTRUCTIONS]
You have access to tools. When you need to perform an action, output a tool call using EXACTLY this format:

<tool_call>
{"name": "TOOL_NAME", "id": "call_UNIQUE_ID", "input": {PARAMETERS}}
</tool_call>

CRITICAL RULES:
- Each tool call MUST be wrapped in <tool_call> tags
- The "id" must start with "call_" followed by a unique string (e.g., call_abc123)
- Output your reasoning/explanation as normal text BEFORE the tool call
- You can make MULTIPLE tool calls in one response
- NEVER output raw file contents — always use the Write tool to create files
- NEVER output code blocks as your final answer — wrap them in tool calls

Available tools:
""" + "\n".join(tool_defs) + "\n[END TOOL INSTRUCTIONS]\n"


def build_prompt(msgs: list, tools: list = None, persona: str = "default") -> str:
    parts = []
    
    parts.append(f"[System]\n{get_system_prompt(persona)}")
    
    tool_instructions = openai_build_tool_instructions(tools) if tools else ""
    if tool_instructions:
        parts.append(tool_instructions)

    for m in msgs:
        role = m.get("role", "user")
        content = m.get("content", "")
        
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            content_str = "\n".join(text_parts)
        else:
            content_str = str(content) if content else ""
            
        if role == "user":
            parts.append(f"[User]\n{content_str}")
        elif role == "assistant":
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    content_str += f'\n<tool_call>\n{{"name": "{fn.get("name", "")}", "id": "{tc.get("id", "")}", "input": {fn.get("arguments", "{}")}}}\n</tool_call>'
            parts.append(f"[Assistant]\n{content_str}")
        elif role == "tool":
            parts.append(f"[Tool Result ({m.get('name', 'tool')}) for {m.get('tool_call_id', '')}]\n{content_str}")
        elif role == "system":
            parts.append(f"[System]\n{content_str}")
        else:
            parts.append(f"[{role}]\n{content_str}")

    if tools:
        parts.append("\n\nCRITICAL: Use the tools above (via <tool_call> XML) to perform the requested changes. Do not just describe them. Perform modifications immediately.")

    prompt = "\n\n".join(parts)
    return smart_context_compress(prompt)


def chunk_sse(content: str, model: str, role: str = "assistant", finish: str = None) -> str:
    d = {"role": role, "content": content}
    if not content and not finish:
        d = {"role": role}
    return "data: " + json.dumps({
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": d, "finish_reason": finish}]
    }) + "\n\n"


def make_response(text: str, thinking: str, tool_calls: list, model: str) -> dict:
    content = text
    if thinking:
        content = f"<think>\n{thinking}\n</think>\n\n{text}"
    
    msg = {"role": "assistant", "content": content}
    finish_reason = "stop"
    
    if tool_calls:
        formatted_calls = []
        for tc in tool_calls:
            formatted_calls.append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc["input"])
                }
            })
        msg["tool_calls"] = formatted_calls
        finish_reason = "tool_calls"
        
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }

# ─── Core: Run with Retries ──────────────────────────────────────────────────

def _stream_chunks(api, chat_id, prompt, thinking, search, parent_message_id=None):
    """Generator that yields parsed chunks from DeepSeek."""
    return api.chat_completion(
        chat_id, prompt,
        parent_message_id=parent_message_id,
        thinking_enabled=thinking,
        search_enabled=search
    )

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "status": "ok",
        "version": "5.0",
        "features": [
            "full-tool-support",
            "forced-deep-think",
            "forced-web-search",
            "smart-context-management",
            "professional-system-prompt",
            "request-logging"
        ],
        "docs": f"http://localhost:{BRIDGE_PORT}/docs"
    }

@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [
        {"id": m, "object": "model", "created": 1700000000, "owned_by": "deepseek"}
        for m in MODELS
    ]}

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "version": "5.0",
        "uptime": stats.uptime,
        "token_set": bool(AUTH_TOKEN),
        "mode": "professional (deep-think + search always on)",
        "retries": MAX_RETRIES,
        "pool_size": len(session_mgr._session_pool),
        "max_pool_size": SESSION_POOL_SIZE,
        "max_context_chars": MAX_CONTEXT_CHARS,
        "stats": {
            "requests": stats.request_count,
            "errors": stats.error_count,
            "tool_calls_parsed": stats.tool_calls_parsed,
            "avg_response_time_s": stats.avg_response_time,
            "context_truncations": stats.context_truncations
        }
    }

# ─── Anthropic Messages API (/v1/messages) ────────────────────────────────────
# Claude Code speaks Anthropic's Messages API natively.
# This section provides FULL tool use translation so DeepSeek can handle
# ALL of Claude Code's tools: Write, Edit, MultiEdit, Bash, Read, ListDir,
# Grep, WebSearch, TodoWrite, Task, NotifyUser, and any future tools.

# ─── Tool Use Translation ─────────────────────────────────────────────────────

def _build_tool_instructions(tools: list) -> str:
    """
    Generate tool-use instructions for ALL tools Claude Code sends.
    No whitelist — every tool is passed through so future tools work automatically.
    """
    if not tools:
        return ""

    tool_defs = []
    for t in tools:
        name = t.get("name", "")
        desc = t.get("description", "")
        schema = t.get("input_schema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])
        params = []
        for pname, pinfo in props.items():
            req = "(required)" if pname in required else "(optional)"
            pdesc = pinfo.get('description', pinfo.get('type', 'string'))
            # Truncate overly long param descriptions
            if len(str(pdesc)) > 60:
                pdesc = str(pdesc)[:60] + "..."
            params.append(f"    - {pname}: {pdesc} {req}")
        # Truncate overly long tool descriptions
        tool_desc = desc[:80] + "..." if len(desc) > 80 else desc
        tool_defs.append(f"  {name}: {tool_desc}\n" + "\n".join(params))

    return """
[TOOL INSTRUCTIONS]
You have access to tools. When you need to perform an action (create files, edit files, run commands, read files), output a tool call using EXACTLY this format:

<tool_call>
{"name": "TOOL_NAME", "id": "toolu_UNIQUE_ID", "input": {PARAMETERS}}
</tool_call>

CRITICAL RULES:
- Each tool call MUST be wrapped in <tool_call> tags
- The "id" must start with "toolu_" followed by a unique string (e.g., toolu_abc123)
- Output your reasoning/explanation as normal text BEFORE the tool call
- You can make MULTIPLE tool calls in one response
- NEVER output raw file contents — always use the Write tool to create files
- NEVER output code blocks as your final answer — wrap them in tool calls
- When editing files, use the Edit tool with exact old_string matches
- For commands, use the Bash tool
- To read files before editing, use the Bash tool with 'cat' or the Read tool

Available tools:
""" + "\n".join(tool_defs) + "\n[END TOOL INSTRUCTIONS]\n"


def _extract_text(content) -> str:
    """Extract plain text from Anthropic content (string or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "text":
                    parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    tool_id = block.get("tool_use_id", "")
                    is_error = block.get("is_error", False)
                    sub = block.get("content", "")
                    if isinstance(sub, list):
                        result_text = _extract_text(sub)
                    elif isinstance(sub, str):
                        result_text = sub
                    else:
                        result_text = str(sub) if sub else "(empty)"
                    status = "ERROR" if is_error else "SUCCESS"
                    parts.append(f"[Tool Result ({status}) for {tool_id}]\n{result_text}")
                elif btype == "tool_use":
                    parts.append(f'<tool_call>\n{json.dumps({"name": block.get("name",""), "id": block.get("id",""), "input": block.get("input",{})})}\n</tool_call>')
                elif btype == "image":
                    parts.append("[image provided]")
                elif btype == "thinking":
                    parts.append(block.get("thinking", ""))
        return "\n".join(parts)
    return str(content)


def _extract_system(system) -> str:
    """Extract system prompt from string or list format."""
    if not system:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for block in system:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("text"):
                    parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(system)


def anthropic_build_prompt(system, messages: list, tools: list = None, persona: str = "default") -> str:
    """Build the full prompt for DeepSeek from Anthropic-format request.
    
    DeepSeek's free chat API silently fails on prompts > ~30k chars.
    We must intelligently compress while preserving the user's actual intent.
    
    Budget allocation (Full Potential Mode):
    - Bridge system prompt: Always full
    - Claude's system prompt: Priority (up to 100k)
    - Tool definitions: Priority (up to 100k)
    - User's latest message: NEVER truncate
    - Conversation history: Uses all remaining budget (up to MAX_CONTEXT_CHARS)
    """
    PROMPT_BUDGET = MAX_CONTEXT_CHARS
    
    parts = []

    # 1. Bridge's own system prompt (~2k) — always full
    bridge_sys = get_system_prompt(persona)
    parts.append(f"[System]\n{bridge_sys}")
    used = len(bridge_sys) + 20

    # 2. Claude Code's system prompt — Priority focus (up to 100k)
    CLAUDE_SYS_BUDGET = 100000
    sys_text = _extract_system(system)
    if sys_text:
        if len(sys_text) > CLAUDE_SYS_BUDGET:
            sys_text = sys_text[:CLAUDE_SYS_BUDGET] + "\n[... Claude system prompt truncated for DeepSeek API limits ...]"
        parts.append(f"[System]\n{sys_text}")
        used += len(sys_text) + 20

    # 3. Tool instructions — Priority focus (up to 100k)
    TOOL_BUDGET = 100000
    if tools:
        tool_instructions = _build_tool_instructions(tools)
        if len(tool_instructions) > TOOL_BUDGET:
            tool_instructions = tool_instructions[:TOOL_BUDGET] + "\n[... Tool instructions truncated ...]"
        parts.append(tool_instructions)
        used += len(tool_instructions) + 20

    # 4. User's LATEST message — HIGHEST priority, never truncate
    latest_user_msg = ""
    remaining_messages = messages
    if messages:
        last_msg = messages[-1]
        if last_msg.get("role") == "user":
            latest_user_msg = _extract_text(last_msg.get("content", ""))
            remaining_messages = messages[:-1]
            used += len(latest_user_msg) + 20

    # 5. Conversation history — fill remaining budget
    history_budget = max(PROMPT_BUDGET - used - 500, 2000)  # At least 2k for history
    history_parts = []
    history_used = 0
    
    # Process messages in REVERSE order (newest first) to prioritize recent context
    for m in reversed(remaining_messages):
        role = m.get("role", "user")
        content = _extract_text(m.get("content", ""))
        
        # Skip empty messages
        if not content.strip():
            continue
            
        entry = f"[{role.capitalize()}]\n{content}"
        
        if history_used + len(entry) > history_budget:
            # Truncate this message to fit remaining budget
            remaining = history_budget - history_used - 100
            if remaining > 200:
                entry = f"[{role.capitalize()}]\n{content[:remaining]}\n[... truncated ...]"
                history_parts.insert(0, entry)
            break
        
        history_parts.insert(0, entry)  # Insert at front to maintain order
        history_used += len(entry)

    # Assemble final prompt
    for hp in history_parts:
        parts.append(hp)
    
    if latest_user_msg:
        parts.append(f"[User]\n{latest_user_msg}")

    # 6. STICKY REMINDER - Repeat tool instructions at the absolute end to force use
    if tools:
        reminder = "\n\nCRITICAL: Use the tools above (via <tool_call> XML) to perform the requested changes. Do not just describe them. If the user asks for a file modification, use Write or Edit tools immediately."
        parts.append(reminder)

    prompt = "\n\n".join(parts)
    
    log.info(f"[Prompt] Built: {len(prompt)} chars (budget: {PROMPT_BUDGET}, "
             f"sys: {len(bridge_sys)}, claude_sys: {len(sys_text) if sys_text else 0}, "
             f"tools: {len(tools) if tools else 0}, history: {len(history_parts)} msgs, "
             f"user_msg: {len(latest_user_msg)} + REMINDER)")

    return prompt


def anthropic_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ─── Tool Call Parser ─────────────────────────────────────────────────────────

def _parse_tool_calls_from_text(full_text: str) -> list:
    """
    Parse completed text to find <tool_call>...</tool_call> blocks.
    Returns list of content blocks (text and tool_use interleaved).
    """
    blocks = []
    pattern = re.compile(r'<tool_call>\s*(.*?)\s*</tool_call>', re.DOTALL)
    last_end = 0

    for match in pattern.finditer(full_text):
        # Text before this tool call
        before = full_text[last_end:match.start()].strip()
        if before:
            blocks.append({"type": "text", "text": before})

        # Parse the tool call JSON
        raw = match.group(1).strip()
        try:
            tc = json.loads(raw)
            tool_id = tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}")
            blocks.append({
                "type": "tool_use",
                "id": tool_id,
                "name": tc.get("name", "unknown"),
                "input": tc.get("input", {})
            })
            stats.tool_calls_parsed += 1
            log.info(f"[Tool] Parsed tool call: {tc.get('name')} (id={tool_id[:20]}...)")
        except json.JSONDecodeError as e:
            log.warning(f"[Tool] Failed to parse tool call JSON: {e}")
            # Try to salvage — sometimes DeepSeek outputs slightly malformed JSON
            try:
                # Attempt to fix common issues: trailing commas, single quotes
                fixed = raw.replace("'", '"')
                fixed = re.sub(r',\s*}', '}', fixed)
                fixed = re.sub(r',\s*]', ']', fixed)
                tc = json.loads(fixed)
                tool_id = tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}")
                blocks.append({
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tc.get("name", "unknown"),
                    "input": tc.get("input", {})
                })
                stats.tool_calls_parsed += 1
                log.info(f"[Tool] Salvaged tool call after JSON fix: {tc.get('name')}")
            except Exception:
                blocks.append({"type": "text", "text": match.group(0)})

        last_end = match.end()

    # Remaining text after last tool call
    after = full_text[last_end:].strip()
    if after:
        blocks.append({"type": "text", "text": after})

    return blocks


# ─── OpenAI API (/v1/chat/completions) ────────────────────────────────────────

@app.post("/v1/chat/completions")
async def completions(req: Request):
    body = await req.json()
    model = body.get("model", "deepseek-chat")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    tools = body.get("tools", None)
    
    if not messages:
        raise HTTPException(400, "messages is empty")

    thinking, search = True, True # forced on
    
    persona = "default"
    if messages:
        last_msg = messages[-1]
        if last_msg.get("role") == "user":
            txt = str(last_msg.get("content", ""))
            match = re.search(r'/persona\s+([a-zA-Z0-9_-]+)', txt)
            if match:
                persona = match.group(1).lower()

    prompt = build_prompt(messages, tools, persona)
    has_tools = bool(tools and len(tools) > 0)
    
    log.info(f"[Request] model={model} think={thinking} search={search} stream={stream} msgs={len(messages)} tools={has_tools}")

    stats.request_count += 1
    start_t = time.time()
    await serialize_request()

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            api, chat_id = await session_mgr.get_session()

            if stream and not has_tools:
                async def gen():
                    yield chunk_sse("", model)  # role header
                    think_buf = []
                    try:
                        for c in _stream_chunks(api, chat_id, prompt, thinking, search):
                            ct = c.get("type", "text")
                            cv = c.get("content", "")
                            if not cv: continue
                            if ct == "thinking":
                                if not think_buf:
                                    yield chunk_sse("<think>\n", model)
                                think_buf.append(cv)
                                yield chunk_sse(cv, model)
                            elif ct == "text":
                                if think_buf:
                                    yield chunk_sse("\n</think>\n\n", model)
                                    think_buf.clear()
                                yield chunk_sse(cv, model)
                    except (RateLimitError, AuthenticationError, NetworkError, APIError) as e:
                        log.error(f"[Stream] {e}")
                        stats.error_count += 1
                        yield chunk_sse(f"\n\n[Bridge Error: {e}]\n", model, finish="stop")
                    yield chunk_sse("", model, finish="stop")
                    yield "data: [DONE]\n\n"
                    _req_lock.release()
                    stats.total_response_time += time.time() - start_t
                    asyncio.create_task(session_mgr.refill_pool())

                return StreamingResponse(gen(), media_type="text/event-stream")

            else:
                # Buffer full response for tool parsing, or non-stream
                all_text, all_think = [], []
                for c in _stream_chunks(api, chat_id, prompt, thinking, search):
                    ct = c.get("type", "text")
                    cv = c.get("content", "")
                    if not cv: continue
                    if ct == "thinking": all_think.append(cv)
                    elif ct == "text": all_text.append(cv)
                
                full_text = "".join(all_text)
                full_think = "".join(all_think)
                
                tool_calls = []
                final_text = full_text
                
                if has_tools and "<tool_call>" in full_text:
                    blocks = _parse_tool_calls_from_text(full_text)
                    text_parts = []
                    for b in blocks:
                        if b["type"] == "text":
                            text_parts.append(b["text"])
                        elif b["type"] == "tool_use":
                            tool_calls.append(b)
                    final_text = "\n\n".join(text_parts)
                
                asyncio.create_task(session_mgr.refill_pool())
                _req_lock.release()
                stats.total_response_time += time.time() - start_t
                
                if stream:
                    async def tool_gen():
                        yield chunk_sse("", model)
                        if full_think:
                            yield chunk_sse("<think>\n" + full_think + "\n</think>\n\n", model)
                        if final_text:
                            yield chunk_sse(final_text, model)
                        
                        if tool_calls:
                            delta_tool_calls = []
                            for idx, tc in enumerate(tool_calls):
                                delta_tool_calls.append({
                                    "index": idx,
                                    "id": tc["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tc["name"],
                                        "arguments": json.dumps(tc["input"])
                                    }
                                })
                            yield "data: " + json.dumps({
                                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{"index": 0, "delta": {"tool_calls": delta_tool_calls}, "finish_reason": "tool_calls"}]
                            }) + "\n\n"
                        else:
                            yield chunk_sse("", model, finish="stop")
                            
                        yield "data: [DONE]\n\n"
                    return StreamingResponse(tool_gen(), media_type="text/event-stream")
                else:
                    return JSONResponse(content=make_response(final_text, full_think, tool_calls, model))

        except AuthenticationError:
            _req_lock.release()
            session_mgr.reset()
            stats.error_count += 1
            raise HTTPException(401, "Invalid DEEPSEEK_AUTH_TOKEN.")
        except RateLimitError as e:
            last_error = e
            wait = 3 * attempt
            log.warning(f"[Retry] Rate limited, waiting {wait}s ({attempt}/{MAX_RETRIES})")
            await asyncio.sleep(wait)
        except (NetworkError, APIError, CloudflareError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = 2 * attempt
                log.warning(f"[Retry] {e}, retrying in {wait}s ({attempt}/{MAX_RETRIES})")
                await asyncio.sleep(wait)

    _req_lock.release()
    stats.error_count += 1
    raise HTTPException(500, f"Failed after {MAX_RETRIES} retries: {last_error}")

# ─── Anthropic /v1/messages Endpoint ──────────────────────────────────────────

@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    """
    Full Anthropic Messages API endpoint for Claude Code.
    Supports ALL tools, professional system prompt injection,
    smart context management, and forced deep-think + search.
    """
    try:
        body = await request.json()
    except Exception as e:
        log.error(f"[Anthropic] Failed to parse request body: {e}")
        raise HTTPException(400, f"Invalid request body: {e}")

    # Log request size — Claude Code v2.1.71 sends huge payloads
    raw_size = len(json.dumps(body))
    log.info(f"[Anthropic] Raw request size: {raw_size} chars")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(400, "messages is empty")

    model = body.get("model", "claude-3-5-sonnet-20241022")
    stream = body.get("stream", False)
    system = body.get("system", None)
    tools = body.get("tools", None)
    max_tokens = body.get("max_tokens", 8192)

    # Unlimited Mode: Pass full tool definitions without slimming
    if tools:
        log.info(f"[Anthropic] Processing {len(tools)} full tools")

    # Parse persona and behavior commands from the last message
    persona = "default"
    auto_review = False
    
    if messages:
        last_msg = messages[-1]
        if last_msg.get("role") == "user":
            txt = _extract_text(last_msg.get("content", ""))
            
            match = re.search(r'/persona\s+([a-zA-Z0-9_-]+)', txt)
            if match:
                persona = match.group(1).lower()
                log.info(f"[Persona] User requested persona: {persona}")
                
            if '/review' in txt:
                auto_review = True
                log.info("[Review] Auto-review loop ENABLED for this turn.")

    thinking, search = (True, True)  # Always forced on

    tool_names = [t.get("name") for t in (tools or [])]
    has_tools = bool(tools and len(tools) > 0)
    
    # Session Persistence Logic
    # 1. Hash the history ONLY (everything except the last user message)
    # 2. Hash the FULL prompt (to save for the next turn)
    history_prompt = anthropic_build_prompt(system, messages[:-1] if len(messages) > 1 else [], tools, persona)
    history_hash = hashlib.md5(history_prompt.encode('utf-8')).hexdigest()
    
    prompt = anthropic_build_prompt(system, messages, tools, persona)
    full_prompt_hash = hashlib.md5(prompt.encode('utf-8')).hexdigest()
    
    # Default to new session
    parent_msg_id = None
    chat_id = None
    is_continuation = False
    
    if history_hash in _session_history_map:
        chat_id, parent_msg_id = _session_history_map[history_hash]
        is_continuation = True
        
    # Get just the newest user query to send to DeepSeek if this is a continuation
    # If not a continuation, we send the whole built prompt.
    if is_continuation and messages:
        # Just send the latest message content
        query_parts = []
        last_msg = messages[-1]
        role = last_msg.get("role", "user")
        content = _extract_text(last_msg.get("content", ""))
        query_parts.append(f"[{role.capitalize()}]\n{content}")
        ds_prompt = "\n\n".join(query_parts)
    else:
        ds_prompt = prompt

    log.info(f"[Anthropic] model={model} think={thinking} search={search} stream={stream} "
             f"msgs={len(messages)} tools={len(tool_names)} pt_chars={len(prompt)} "
             f"cont={is_continuation} p_msg={parent_msg_id}")

    # Log the request
    log_request("/v1/messages", prompt)

    stats.request_count += 1
    start_t = time.time()
    await serialize_request()
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # FIX: Ensure api/chat_id are ALWAYs fresh or correctly assigned for each attempt
            if is_continuation:
                # Even for continuations, we need to ensure the api object is initialized
                api = session_mgr._get_api()
            else:
                api, chat_id = await session_mgr.get_session()

            # Collect full response (needed for tool call parsing)
            all_text = []
            all_think = []
            ds_msg_id = None
            
            for c in _stream_chunks(api, chat_id, ds_prompt, thinking, search, parent_msg_id):
                ct = c.get("type", "text")
                cv = c.get("content", "")
                
                if ct == "message_id":
                    ds_msg_id = c.get("message_id")
                    continue
                    
                if not cv:
                    continue
                if ct == "thinking":
                    all_think.append(cv)
                elif ct == "text":
                    all_text.append(cv)

            if ds_msg_id and chat_id:
                _session_history_map[full_prompt_hash] = (chat_id, ds_msg_id)
                log.info(f"[Session] Cached session {chat_id[:8]} with parent {ds_msg_id} "
                         f"under hash {full_prompt_hash[:8]}")

            full_text = "".join(all_text)
            full_think = "".join(all_think)

            # FALLBACK LOGIC: If a continuation session returned NOTHING, it's likely stale.
            # We force it to retry as a FRESH session on the next attempt.
            if is_continuation and not full_text and not full_think:
                log.warning(f"[Fallback] Continuation {chat_id[:8]} returned empty! Forcing fresh session for retry...")
                is_continuation = False
                ds_prompt = prompt # Send the full prompt this time
                parent_msg_id = None
                if history_hash in _session_history_map:
                    del _session_history_map[history_hash]
                raise APIError("Empty continuation response, triggering fallback.")
            
            # --- MULTI-AGENT REVIEW LOOP ---
            if auto_review and "<tool_call>" in full_text:
                log.info("[Review] Passing generated code to Reviewer Agent...")
                review_api = session_mgr._get_api()
                review_sid = review_api.create_chat_session()
                rev_prompt = anthropic_build_prompt(None, [{"role": "user", "content": f"Review this code change for critical bugs or terrible logic:\n{full_text}\nIf it is perfectly fine, reply only with 'LGTM'. Otherwise, concisely list the bugs."}], persona="reviewer")
                
                rev_text_parts = []
                for rc in _stream_chunks(review_api, review_sid, rev_prompt, False, False):
                    if rc.get("type") == "text" and rc.get("content"):
                        rev_text_parts.append(rc.get("content"))
                
                reviewer_feedback = "".join(rev_text_parts).strip()
                log.info(f"[Review] Reviewer Output: {reviewer_feedback[:100]}...")
                
                if "LGTM" not in reviewer_feedback.upper() and len(reviewer_feedback) > 10:
                    log.warning("[Review] Reviewer found issues! Forcing regeneration of response.")
                    # Inject feedback into prompt and regenerate
                    correction_prompt = ds_prompt + f"\n\n[Assistant]\n{full_text}\n\n[User]\nWait, a senior reviewer reviewed your proposed changes and found issues:\n{reviewer_feedback}\n\nPlease output a corrected tool call to fix this."
                    
                    all_text.clear()
                    all_think.clear()
                    ds_msg_id = None
                    
                    for c in _stream_chunks(api, chat_id, correction_prompt, thinking, search, parent_msg_id):
                        ct = c.get("type", "text")
                        cv = c.get("content", "")
                        if ct == "message_id":
                            ds_msg_id = c.get("message_id")
                            continue
                        if not cv: continue
                        if ct == "thinking": all_think.append(cv)
                        elif ct == "text": all_text.append(cv)
                        
                    full_text = "".join(all_text)
                    full_think = "".join(all_think)
                    
                    if ds_msg_id and chat_id:
                        _session_history_map[full_prompt_hash] = (chat_id, ds_msg_id)
            # --- END REVIEW LOOP ---

            asyncio.create_task(session_mgr.refill_pool())

            # Log response summary
            log_request("/v1/messages:response", "", full_text[:300])

            # Estimate token usage
            input_tokens = estimate_tokens(prompt)
            output_tokens = estimate_tokens(full_text + full_think)

            # Parse tool calls from the full text
            if has_tools and "<tool_call>" in full_text:
                content_blocks = _parse_tool_calls_from_text(full_text)
                has_tool_use = any(b["type"] == "tool_use" for b in content_blocks)
            else:
                content_blocks = []
                if full_text:
                    content_blocks.append({"type": "text", "text": full_text})
                has_tool_use = False

            # Ensure there's always at least one text block
            if not content_blocks:
                log.warning(f"[Anthropic] Empty response from DeepSeek API! Full Text Length: {len(full_text)}")
                content_blocks.append({
                    "type": "text", 
                    "text": f"(No response generated by DeepSeek API for this request. Prompt Length: {len(prompt)} chars. Please try a smaller query or restart the bridge.)"
                })

            # Add thinking block if present
            if full_think:
                content_blocks.insert(0, {"type": "thinking", "thinking": full_think})

            stop_reason = "tool_use" if has_tool_use else "end_turn"

            elapsed = time.time() - start_t
            stats.total_response_time += elapsed
            log.info(f"[Anthropic] Response complete: {len(full_text)} chars, "
                     f"{len(content_blocks)} blocks, stop={stop_reason}, {elapsed:.1f}s")

            if stream:
                async def anthropic_gen():
                    yield anthropic_sse("message_start", {
                        "type": "message_start",
                        "message": {
                            "id": msg_id, "type": "message", "role": "assistant",
                            "content": [], "model": model,
                            "stop_reason": None, "stop_sequence": None,
                            "usage": {"input_tokens": input_tokens, "output_tokens": 0}
                        }
                    })

                    for idx, block in enumerate(content_blocks):
                        if block["type"] == "text":
                            yield anthropic_sse("content_block_start", {
                                "type": "content_block_start",
                                "index": idx,
                                "content_block": {"type": "text", "text": ""}
                            })
                            text = block["text"]
                            chunk_size = 60
                            for i in range(0, len(text), chunk_size):
                                yield anthropic_sse("content_block_delta", {
                                    "type": "content_block_delta",
                                    "index": idx,
                                    "delta": {"type": "text_delta", "text": text[i:i+chunk_size]}
                                })
                            yield anthropic_sse("content_block_stop", {
                                "type": "content_block_stop", "index": idx
                            })

                        elif block["type"] == "tool_use":
                            yield anthropic_sse("content_block_start", {
                                "type": "content_block_start",
                                "index": idx,
                                "content_block": {
                                    "type": "tool_use",
                                    "id": block["id"],
                                    "name": block["name"],
                                    "input": {}
                                }
                            })
                            yield anthropic_sse("content_block_delta", {
                                "type": "content_block_delta",
                                "index": idx,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": json.dumps(block["input"])
                                }
                            })
                            yield anthropic_sse("content_block_stop", {
                                "type": "content_block_stop", "index": idx
                            })

                        elif block["type"] == "thinking":
                            yield anthropic_sse("content_block_start", {
                                "type": "content_block_start",
                                "index": idx,
                                "content_block": {"type": "thinking", "thinking": ""}
                            })
                            yield anthropic_sse("content_block_delta", {
                                "type": "content_block_delta",
                                "index": idx,
                                "delta": {"type": "thinking_delta", "thinking": block["thinking"]}
                            })
                            yield anthropic_sse("content_block_stop", {
                                "type": "content_block_stop", "index": idx
                            })

                    yield anthropic_sse("message_delta", {
                        "type": "message_delta",
                        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                        "usage": {"output_tokens": output_tokens}
                    })
                    yield anthropic_sse("message_stop", {"type": "message_stop"})

                    _req_lock.release()

                return StreamingResponse(anthropic_gen(), media_type="text/event-stream")

            else:
                _req_lock.release()
                return JSONResponse(content={
                    "id": msg_id, "type": "message", "role": "assistant",
                    "content": content_blocks, "model": model,
                    "stop_reason": stop_reason, "stop_sequence": None,
                    "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}
                })

        except AuthenticationError:
            _req_lock.release()
            session_mgr.reset()
            stats.error_count += 1
            raise HTTPException(401, "Invalid DEEPSEEK_AUTH_TOKEN.")
        except RateLimitError as e:
            last_error = e
            wait = 3 * attempt
            log.warning(f"[Retry] Rate limited ({attempt}/{MAX_RETRIES})")
            await asyncio.sleep(wait)
        except (NetworkError, APIError, CloudflareError) as e:
            last_error = e
            stats.error_count += 1
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 * attempt)

    _req_lock.release()
    stats.error_count += 1
    # Return a graceful error in Anthropic format
    return JSONResponse(
        status_code=500,
        content={
            "id": msg_id, "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": f"[Bridge Error] Failed after {MAX_RETRIES} retries: {last_error}\n\nPlease try again. The DeepSeek API may be temporarily unavailable."}],
            "model": model,
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}
        }
    )

# ─── Auto Port Kill ──────────────────────────────────────────────────────────

def kill_port(port: int):
    """Kill any process holding the given port (Mac/Linux/Windows)."""
    try:
        import subprocess
        import platform
        
        system = platform.system()
        log.info(f"[Startup] Checking port {port} on {system}...")
        
        if system == "Darwin" or system == "Linux":
            # Use lsof to find and kill
            try:
                result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
                pids = result.stdout.strip().split()
                for pid in pids:
                    if pid:
                        log.info(f"[Startup] Killing PID {pid} on port {port}")
                        subprocess.run(["kill", "-9", pid])
                time.sleep(0.5)
            except Exception as e:
                log.warning(f"[Startup] Failed to kill port via lsof: {e}")
                
        elif system == "Windows":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    if pid > 0:
                        log.info(f"[Startup] Killing PID {pid} on port {port}")
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                       capture_output=True, timeout=5)
                        time.sleep(0.5)
    except Exception as e:
        log.warning(f"[Startup] Could not auto-kill port {port}: {e}")

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    # Fix Windows console encoding for Unicode output
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    # Auto-kill anything holding our port
    kill_port(BRIDGE_PORT)

    print()
    print("=" * 64)
    print("  DeepSeek4Free Bridge v5.0 (Professional Mode)")
    print("=" * 64)
    print(f"  Host          : http://{BRIDGE_HOST}:{BRIDGE_PORT}")
    print(f"  Swagger       : http://localhost:{BRIDGE_PORT}/docs")
    print()
    print("  Features:")
    print(f"    [+] Deep Think    : ALWAYS ON")
    print(f"    [+] Web Search    : ALWAYS ON")
    print(f"    [+] All Tools     : ENABLED (no whitelist)")
    print(f"    [+] System Prompt : Professional coding agent")
    print(f"    [+] Context Mgmt  : Smart compression ({MAX_CONTEXT_CHARS} char limit)")
    print(f"    [+] Session Pool  : {SESSION_POOL_SIZE} pre-warmed sessions")
    print(f"    [+] Request Log   : {'ON' if LOG_REQUESTS else 'OFF'}")
    print(f"    [+] Max Retries   : {MAX_RETRIES}")
    print()
    print("  Endpoints:")
    print(f"    Anthropic  : POST /v1/messages        (Claude Code)")
    print(f"    OpenAI     : POST /v1/chat/completions")
    print(f"    Models     : GET  /v1/models")
    print(f"    Health     : GET  /health")
    print()
    print("  Claude Code setup:")
    print(f"    $env:ANTHROPIC_BASE_URL='http://localhost:{BRIDGE_PORT}'")
    print(f"    $env:ANTHROPIC_API_KEY='sk-fake'")
    print(f"    claude")
    print("=" * 64)
    print()

    uvicorn.run(app, host=BRIDGE_HOST, port=BRIDGE_PORT, log_level="info")