"""
NOVA — Entry Point (v2.0 Enterprise)
=====================================
Delegates to apps.nova_server.main for the full enterprise server.
This file exists for backward compatibility: python main.py
"""
from apps.nova_server.main import main

if __name__ == "__main__":
    main()
