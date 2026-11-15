import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="civil-test-")
os.environ["CIVIL_DATA_DIR"] = _tmp
os.environ["CIVIL_ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
