#!/usr/bin/env python3
import sys
import os

# Add repo root to path
repo_root = os.path.abspath('.')
sys.path.insert(0, repo_root)

# Test imports
print("Testing imports...")
try:
    from mocks import route003_mock_data
    print("SUCCESS: mocks.route003_mock_data imported")
    print("Contents:", dir(route003_mock_data))
except Exception as e:
    print(f"FAILED: {e}")
