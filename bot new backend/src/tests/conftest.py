import os
import sys
from pathlib import Path

# Tests must not require TensorFlow / model files unless explicitly enabled.
os.environ.setdefault("ML_ENABLED", "false")
os.environ.setdefault("ML_STRICT", "false")
# get_settings() requires DATABASE_URL at import time (session module loads settings).
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
