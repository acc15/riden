"""Project-wide device defaults."""

import logging

DEFAULT_ADDRESS = 1
DEFAULT_URL = "bt://E1:F9:C6:24:71:C8"
# DEFAULT_URL = "/dev/ttyUSB0"
# DEFAULT_URL = "tcp://127.0.0.1:5020"

logging.basicConfig(
    format="[%(asctime)s.%(msecs)03d][%(levelname)s][%(name)s] %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%dT%H:%M:%S"
)
logging.getLogger("riden").setLevel(logging.DEBUG)
# logging.getLogger("tmodbus").setLevel(logging.DEBUG)