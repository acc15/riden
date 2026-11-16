"""Project-wide device defaults."""

import logging

DEFAULT_ADDRESS = "26:05:E9:A3:00:37"
DEFAULT_URL = f"bt://{DEFAULT_ADDRESS}"

logging.basicConfig(
    format="[%(asctime)s.%(msecs)03d][%(name)s] %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%dT%H:%M:%S"
)
logging.getLogger("riden").setLevel(logging.DEBUG)