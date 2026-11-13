#!/usr/bin/env .venv/bin/python

import time

import config

from riden import Riden

with Riden.connect(config.DEFAULT_URL, keepalive=None, retry_attempts=0) as rd:
    rd.write(v_set=12, en=True)
    time.sleep(20)
    rd.write(v_set=5, en=False)
