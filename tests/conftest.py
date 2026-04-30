"""Make project root importable as `db`, `backend`, etc. when running pytest."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# `db.database` imports psycopg2 at module level; CI / minimal envs may lack the binary wheel.
try:
    import psycopg2  # noqa: F401
except ModuleNotFoundError:
    _extras = MagicMock()
    _extras.RealDictCursor = MagicMock()
    _extras.execute_values = MagicMock()
    sys.modules["psycopg2"] = MagicMock()
    sys.modules["psycopg2.extras"] = _extras
