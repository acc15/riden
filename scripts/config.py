"""Project-wide device defaults."""

import logging

DEFAULT_ADDRESS = "E1:F9:C6:24:71:C8"
DEFAULT_URL = f"bt://{DEFAULT_ADDRESS}"

logging.basicConfig(
    format="[%(asctime)s.%(msecs)03d][%(name)s] %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%dT%H:%M:%S"
)
logging.getLogger("riden").setLevel(logging.DEBUG)