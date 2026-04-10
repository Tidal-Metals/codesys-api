"""API key persistence and validation."""

import json
import os
import time

class ApiKeyManager:
    """Manages API keys for authentication."""
    
    def __init__(self, key_file_path):
        self.key_file_path = key_file_path
        self.keys = self._load_keys()
        
    def _load_keys(self):
        """Load API keys from file."""
        if not os.path.exists(self.key_file_path):
            # Create default admin key
            keys = {"admin": {"name": "Admin", "created": time.time()}}
            self._save_keys(keys)
            return keys
            
        try:
            with open(self.key_file_path, 'r') as f:
                return json.loads(f.read())
        except:
            return {}
            
    def _save_keys(self, keys):
        """Save API keys to file."""
        with open(self.key_file_path, 'w') as f:
            f.write(json.dumps(keys))
            
    def validate_key(self, key):
        """Validate an API key."""
        return key in self.keys
