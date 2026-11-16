from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

TEST_STATE_DIR = Path(tempfile.mkdtemp(prefix="canlytics-tests-state-"))
os.environ["CANLYTICS_STATE_DIR"] = str(TEST_STATE_DIR)
os.environ["CANLYTICS_STATE_MIGRATION"] = "0"
atexit.register(shutil.rmtree, TEST_STATE_DIR, ignore_errors=True)
