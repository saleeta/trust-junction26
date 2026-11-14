"""Shim: the shared logic lives in trust/generic/logic.py."""
import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parents[1] / "trust" / "generic" / "logic.py"
_s = importlib.util.spec_from_file_location("_trust_logic", _p)
_m = importlib.util.module_from_spec(_s)
import sys; sys.modules["_trust_logic"] = _m   # dataclasses need the module registered
_s.loader.exec_module(_m)
globals().update({k: v for k, v in vars(_m).items() if not k.startswith("__")})
