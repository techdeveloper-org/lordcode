"""Central logging setup for Vishwakarma's CLI and web app.

Every model call, fallback, and self-heal step already calls logging.info/
logging.warning from router.py, llm_client.py, and engine/calling.py -- this
module just wires those up to a readable console format so the user can see
which provider/model handled what without needing to read source code.
"""

from __future__ import annotations

import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"


def configure_logging() -> None:
    """Configure the root logger for readable console output.

    Level is controlled by the VISHWAKARMA_LOG_LEVEL env var (default INFO)
    so a user can set it to DEBUG to see skipped skill/agent files, etc.
    """
    level_name = os.environ.get("VISHWAKARMA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT)
