import json
import base64
import subprocess
import os
import sys
import asyncio
from typing import Dict, Any
import structlog

log = structlog.get_logger(__name__)

class PoWSolver:
    """Solves DeepSeek's Proof-of-Work challenges using the Node.js WASM bridge."""
    
    def __init__(self):
        # We reuse the existing solver JS from the old dsk folder
        # but we point to it correctly in the new structure
        self.script_path = "dsk/pow_solver.js" 
        
    async def solve(self, config: Dict[str, Any]) -> str:
        """Solves a challenge and returns the base64 encoded response."""
        
        # Format params for the node script
        params = {
            'algorithm': config['algorithm'],
            'challenge': config['challenge'],
            'salt': config['salt'],
            'difficulty': config.get('difficulty') or config.get('target') or 0,
            'expire_at': config['expire_at'],
            'target_path': config.get('target_path', '/api/v0/chat/completion')
        }

        try:
            # Run the existing Node.js solver
            # We use asyncio.create_subprocess_exec for non-blocking execution
            proc = await asyncio.create_subprocess_exec(
                "node", self.script_path, json.dumps(params),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                log.error("pow_solver_failed", error=stderr.decode())
                raise RuntimeError(f"PoW solving failed: {stderr.decode()}")
                
            output = json.loads(stdout.decode())
            answer = output.get('answer')
            
            if answer is None:
                raise RuntimeError("PoW solver returned no answer")

            # Encode for DeepSeek header
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
            log.error("pow_solve_error", error=str(e))
            raise

pow_solver = PoWSolver()
