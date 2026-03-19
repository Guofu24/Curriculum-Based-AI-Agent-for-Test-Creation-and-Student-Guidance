"""Compatibility wrapper for the deprecated Phase 2 eval entrypoint."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evals.run_phase3_eval import main


if __name__ == "__main__":
    main()
