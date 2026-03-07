"""
DeepSeek Proof of Work Challenge Implementation
Author: @xtekky
Modified for stability on macOS by utilizing Node.js for the WASM execution.
"""

import json
import base64
import subprocess
import os
import sys
from typing import Dict, Any

class DeepSeekPOW:
    def __init__(self):
        # Check if node is available
        try:
            subprocess.run(["node", "-v"], capture_output=True, check=True)
            self.node_available = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.node_available = False
            print("\033[91mError: Node.js is required for PoW solving on this platform but was not found.\033[0m", file=sys.stderr)

    def solve_challenge(self, config: Dict[str, Any]) -> str:
        """Solves a proof-of-work challenge and returns the encoded response"""
        if not self.node_available:
            raise RuntimeError("Node.js not found. Cannot solve PoW challenge.")

        # Path to the node solver bridge
        script_path = os.path.join(os.path.dirname(__file__), 'pow_solver.js')
        
        # Format the parameters for the node script
        params = {
            'algorithm': config['algorithm'],
            'challenge': config['challenge'],
            'salt': config['salt'],
            'difficulty': config.get('difficulty') or config.get('target') or 0,
            'expire_at': config['expire_at'],
            'target_path': config.get('target_path', '/api/v0/chat/completion')
        }

        try:
            # Call the node solver
            result = subprocess.run(
                ["node", script_path, json.dumps(params)],
                capture_output=True,
                text=True,
                check=True
            )
            
            output = json.loads(result.stdout)
            answer = output.get('answer')
            
            if answer is None:
                print("\033[93mWarning: PoW solver returned no answer.\033[0m", file=sys.stderr)

            # Build the result dict for encoding
            res_dict = {
                'algorithm': config['algorithm'],
                'challenge': config['challenge'],
                'salt': config['salt'],
                'answer': answer,
                'signature': config['signature'],
                'target_path': params['target_path']
            }
            
            return base64.b64encode(json.dumps(res_dict).encode()).decode()

        except Exception as e:
            print(f"\033[91mError: Node.js PoW solver failed: {e}\033[0m", file=sys.stderr)
            if hasattr(e, 'stderr') and e.stderr:
                print(f"Stderr: {e.stderr}", file=sys.stderr)
            raise RuntimeError(f"PoW solving failed: {e}")