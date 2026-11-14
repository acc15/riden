#!/usr/bin/env .venv/bin/python

import timeit

import config

from riden import Field, Riden


def measure_perf(rd, fn):
    elapsed = timeit.timeit(lambda: fn(rd), number=1)
    print(f"{fn.__name__} executed in {elapsed}s")

def single_long_read(rd: Riden):
    print(rd.read(f for f in Field if f.is_readable))

def two_short_reads(rd: Riden):
    print(rd.read(Field.ID), rd.read(Field.V))

with Riden.connect(config.DEFAULT_URL) as rd:
    measure_perf(rd, single_long_read)
    measure_perf(rd, two_short_reads)