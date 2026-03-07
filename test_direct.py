import os
import json
import sys
from dotenv import load_dotenv
from dsk.api import DeepSeekAPI

def test_minimal():
    load_dotenv()
    token = os.getenv("DEEPSEEK_AUTH_TOKEN")
    
    print("Initializing API...")
    api = DeepSeekAPI(token)
    
    print("Creating session...")
    sid = api.create_chat_session()
    print(f"Session created: {sid[:12]}...")

    print("Sending request (thinking=False, search=False)...")
    gen = api.chat_completion(sid, "say hello world", thinking_enabled=False, search_enabled=False)
    has_content = False
    for chunk in gen:
        if chunk.get('type') == 'text':
            print(chunk.get('content'), end='', flush=True)
            has_content = True
    
    if not has_content:
        print("\nWARNING: No text content received in response.")
    else:
        print("\nRequest finished successfully.")

if __name__ == "__main__":
    test_minimal()
