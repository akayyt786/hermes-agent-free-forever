import json
import re
import uuid
from typing import List, Dict, Any, Optional, Tuple
import structlog

log = structlog.get_logger(__name__)

class ToolTranslationService:
    """Translates between XML tool calls (DeepSeek Web) and JSON tool calls (OpenAI)."""
    
    # Pattern to find <tool_call>{"name": "...", "id": "...", "input": {...}}</tool_call>
    TOOL_CALL_PATTERN = re.compile(r'<tool_call>\s*(.*?)\s*</tool_call>', re.DOTALL)

    def inject_tool_instructions(self, tools: List[Dict[str, Any]]) -> str:
        """Generates the system prompt instructions to force tool usage and prevent conversational filler."""
        if not tools:
            return ""

        tool_defs = []
        for t in tools:
            # Handle both OpenAI function format and Anthropic tool format
            name = t.get("name") or t.get("function", {}).get("name")
            desc = t.get("description") or t.get("function", {}).get("description", "")
            
            # Simple summary for the prompt
            tool_defs.append(f"- {name}: {desc[:150]}...")

        return f"""
# TOOL CALLING SYSTEM
You are currently in an automated agent loop. You MUST use tools to fulfill the user's requests.

## CRITICAL RULES:
1. YOU MUST NOT describe your plan or what you are about to do.
2. YOU MUST NOT use conversational filler like "I will create a folder" or "Let me write that file".
3. YOU MUST OUTPUT THE TOOL CALL IMMEDIATELY.
4. Use this exact XML format for tool calls:
<tool_call>
{{"name": "TOOL_NAME", "id": "toolu_UNIQUE_ID", "input": {{PARAMETERS}}}}
</tool_call>

Available tools:
{chr(10).join(tool_defs)}

FAILURE TO FOLLOW THESE RULES WILL BREAK THE AGENT LOOP. START ALL RESPONSES WITH A TOOL CALL IF A TOOL IS NEEDED.
"""

    def parse_tool_calls(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Parses text for XML tool calls or Hermes text tool calls. 
        Returns (clean_text, list_of_openai_tool_calls).
        """
        tool_calls = []
        clean_text = text

        # 1. Parse Hermes Text Format: Tool: <name> \n Input: { ... }
        hermes_pattern = re.compile(r'Tool:\s*([a-zA-Z0-9_-]+)\s*\n\s*Input:\s*', re.DOTALL)
        while True:
            match = hermes_pattern.search(clean_text)
            if not match:
                break
                
            name = match.group(1).strip()
            start_search_idx = match.end()
            
            # Find the start of the JSON object
            json_start = clean_text.find('{', start_search_idx)
            if json_start == -1:
                break # No JSON object found after Input:
                
            # Brace counting to find the end of the JSON object
            brace_count = 0
            in_string = False
            escape_next = False
            json_end = -1
            
            for i in range(json_start, len(clean_text)):
                char = clean_text[i]
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                    
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break
                            
            if json_end != -1:
                raw_json = clean_text[json_start:json_end]
                try:
                    # Validate JSON
                    json.loads(raw_json)
                    tool_calls.append({
                        "index": len(tool_calls),
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": raw_json
                        }
                    })
                    # Remove the parsed tool call block from text
                    clean_text = clean_text[:match.start()] + clean_text[json_end:]
                except Exception as e:
                    log.warning("hermes_tool_parse_error", error=str(e))
                    break # Invalid JSON, stop trying to parse this format
            else:
                break # Incomplete JSON, wait for more chunks
                
        # 2. Parse XML Format: <tool_call> { ... } </tool_call>
        def replace_xml_match(match):
            raw_json = match.group(1).strip()
            try:
                tc = json.loads(raw_json)
                tool_calls.append({
                    "index": len(tool_calls),
                    "id": tc.get("id", f"call_{uuid.uuid4().hex[:12]}"),
                    "type": "function",
                    "function": {
                        "name": tc.get("name"),
                        "arguments": json.dumps(tc.get("input", {}))
                    }
                })
                return ""
            except Exception:
                return match.group(0)

        clean_text = self.TOOL_CALL_PATTERN.sub(replace_xml_match, clean_text).strip()
        
        return clean_text, tool_calls

tool_translator = ToolTranslationService()
