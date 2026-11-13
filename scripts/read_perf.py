#!/usr/bin/env .venv/bin/python

import time

import config

from riden import Field, Riden


def measure_perf(rd, fn):
    start = time.perf_counter()
    fn(rd)
    end = time.perf_counter()
    print(f"{fn.__name__} executed in {(end-start)}s")

def single_long_read(rd: Riden):
    print(rd.read(f for f in Field if f.is_readable))

def two_short_reads(rd: Riden):
    print(rd.read(Field.ID), rd.read(Field.V))

with Riden.connect(config.DEFAULT_URL) as rd:
    measure_perf(rd, single_long_read)
    measure_perf(rd, two_short_reads)