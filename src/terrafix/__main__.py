"""
Entry point for running TerraFix as a module.

Allows running TerraFix with:
    python -m terrafix.service
"""

import sys

from terrafix.service import main

if __name__ == "__main__":
    sys.exit(main())
