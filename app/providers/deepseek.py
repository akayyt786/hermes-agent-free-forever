import httpx
import json
import asyncio
from typing import List, AsyncGenerator, Optional, Dict, Any
import structlog

from app.providers.base import BaseProvider
from app.schemas.internal import InternalRequest, InternalResponse, InternalChunk
from app.stealth.pow import pow_solver
from app.services.tools import tool_translator
from app.core.config import settings
from app.core.exceptions import ProviderError

log = structlog.get_logger(__name__)

class DeepSeekProvider(BaseProvider):
    """Provider for unofficial DeepSeek Web-Chat access."""
    
    BASE_URL = "https://chat.deepseek.com/api/v0"
    
    def __init__(self, auth_token: str):
        self.auth_token = auth_token
        self.client = httpx.AsyncClient(timeout=60.0)
        self.cookies: Dict[str, str] = {}
        # We will load cookies from browser_mgr in a real flow
        
    def _get_headers(self, pow_response: Optional[str] = None) -> Dict[str, str]:
        headers = {
            'authorization': f'Bearer {self.auth_token}',
            'content-type': 'application/json',
            'origin': 'https://chat.deepseek.com',
            'referer': 'https://chat.deepseek.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'x-app-version': '20241129.1',
            'x-client-platform': 'web',
        }
        if pow_response:
            headers['x-ds-pow-response'] = pow_response
        return headers

    async def _get_pow_challenge(self) -> Dict[str, Any]:
        resp = await self.client.post(
            f"{self.BASE_URL}/chat/create_pow_challenge",
            headers=self._get_headers(),
            json={'target_path': '/api/v0/chat/completion'}
        )
        if resp.status_code != 200:
            raise ProviderError(f"Failed to get PoW challenge: {resp.text}", "deepseek", resp.status_code)
        return resp.json()['data']['biz_data']['challenge']

    async def create_chat_session(self) -> str:
        resp = await self.client.post(
            f"{self.BASE_URL}/chat_session/create",
            headers=self._get_headers(),
            json={'character_id': None}
        )
        return resp.json()['data']['biz_data']['id']

    async def stream(self, request: InternalRequest) -> AsyncGenerator[InternalChunk, None]:
        # Implementation of the JSON patch stream parsing
        # For now, we consolidate the existing dsk/api.py logic here
        
        session_id = await self.create_chat_session()
        challenge = await self._get_pow_challenge()
        pow_resp = await pow_solver.solve(challenge)
        
        # Build the prompt with tool instructions if tools are present
        system_instructions = tool_translator.inject_tool_instructions(request.tools or [])
        prompt = system_instructions + "\n\n" + "\n\n".join([f"{m.role}: {m.content}" for m in request.messages])
        
        json_data = {
            'chat_session_id': session_id,
            'parent_message_id': None,
            'prompt': prompt,
            'ref_file_ids': [],
            'thinking_enabled': True,
            'search_enabled': False,
        }

        async with self.client.stream(
            "POST",
            f"{self.BASE_URL}/chat/completion",
            headers=self._get_headers(pow_resp),
            json=json_data
        ) as response:
            if response.status_code != 200:
                raise ProviderError(f"DeepSeek stream failed: {await response.aread()}", "deepseek", response.status_code)
                
            current_path = None
            full_text = ""
            has_tool_call = False
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                
                try:
                    data = json.loads(line[6:])
                    
                    # Check for DeepSeek internal errors in the stream
                    if data.get('code') != 0 and 'msg' in data:
                        log.error("deepseek_stream_error", data=data)
                        raise ProviderError(f"DeepSeek Error: {data.get('msg')}", "deepseek", 500)
                        
                    path = data.get('p', current_path)
                    value = data.get('v')
                    
                    if not isinstance(value, str):
                        log.debug("deepseek_unhandled_stream_data", data=data)
                        continue
                        
                    if path == 'response/content':
                        full_text += value
                        
                        # Suppress tool XML construction from streaming out to the user
                        if "<tool_call>" in full_text and "</tool_call>" not in full_text:
                            current_path = path
                            continue
                            
                        # Check for completed tool calls
                        clean_text, tool_calls = tool_translator.parse_tool_calls(full_text)
                        
                        if tool_calls:
                            # Update full_text so we don't parse the same tool call twice
                            full_text = clean_text
                            has_tool_call = True
                            # Yield the tool call without any content
                            yield InternalChunk(content="", tool_calls=tool_calls)
                            # CRITICAL: Stop generating text immediately! Do not let DeepSeek hallucinate the output!
                            break
                        else:
                            # Regular text, yield it
                            yield InternalChunk(content=value, tool_calls=None)
                            
                        current_path = path
                    elif path == 'response/thinking_content':
                        yield InternalChunk(content=value, role="thinking")
                        current_path = path
                except Exception:
                    continue

            # Stream has finished naturally. Yield the final finish_reason
            if has_tool_call:
                yield InternalChunk(content="", finish_reason="tool_calls")
            else:
                yield InternalChunk(content="", finish_reason="stop")

    async def complete(self, request: InternalRequest) -> InternalResponse:
        full_content = ""
        async for chunk in self.stream(request):
            if chunk.content:
                full_content += chunk.content
        return InternalResponse(content=full_content)

    async def list_models(self) -> List[str]:
        return ["deepseek-chat", "deepseek-reasoner"]

    async def health_check(self) -> bool:
        return True
