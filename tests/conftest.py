import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="civil-test-")
os.environ["CIVIL_DATA_DIR"] = _tmp
os.environ["CIVIL_ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"
# never touch a running ejabberd: unit tests see the chat server as "down"
os.environ["CIVIL_XMPP_API_PORT"] = "9"
os.environ["CIVIL_XMPP_WS_PORT"] = "9"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
