"""Keep pre-layout dotted test names importable. Discovery runs in each task."""
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
__path__.extend(str(_root / task / "tests") for task in ("w1", "c1", "s1"))
