#!/usr/bin/env .venv/bin/python

import time

import config

from riden import Riden

with Riden.connect(config.DEFAULT_URL) as rd:
    try:
        rd.write(v_set = 0, i_set = 0.1, en = True)
        for v in range(0, 60, 5):
            start = time.perf_counter()
            rd.write(v_set = v)
            v_set_time = time.perf_counter()
            time.sleep(2)
            print(rd.status())
            end = time.perf_counter()
            print(f"executed in {end-start}s, v_set in {v_set_time-start}s")

    finally:
        rd.write(v_set = 5, i_set = 0.1, en = False)