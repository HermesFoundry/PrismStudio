#!/usr/bin/env python3
"""The entry point. Keeps sys.path tidy, then hands over to the application."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import PrismApp  # noqa: E402

if __name__ == "__main__":
    sys.exit(PrismApp().run(sys.argv))
