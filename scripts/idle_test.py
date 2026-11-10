#!/usr/bin/env .venv/bin/python

import time

from config import DEFAULT_URL

from riden import Delayed, Modbus, Reconnectable, Riden, KeepAlive

with Riden(Reconnectable(KeepAlive(Delayed(Modbus(DEFAULT_URL))))) as rd:
    rd.write(v_set=12, en=True)
    time.sleep(20)
    rd.write(v_set=5, en=False)
