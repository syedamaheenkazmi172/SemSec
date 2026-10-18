"""
warmup.py - Warms up the LLM in Ollama and keeps it in memory.

Sends one short throwaway instruction through extract() and prints how long
it took, then repeats it once and prints the second duration.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__) or ".")
from extractor import extract


def warmup():
    instruction = "show record"

    print("--- Ollama Model Warmup ---")
    print(f"Pass 1: extracting '{instruction}'...")
    t0 = time.perf_counter()
    res1 = extract(instruction)
    t1 = time.perf_counter()
    dur1 = t1 - t0
    print(f"Pass 1 completed in {dur1:.2f}s -> action={res1.get('action')}")

    print(f"\nPass 2: repeating '{instruction}'...")
    t2 = time.perf_counter()
    res2 = extract(instruction)
    t3 = time.perf_counter()
    dur2 = t3 - t2
    print(f"Pass 2 completed in {dur2:.2f}s -> action={res2.get('action')}")

    if dur2 > 0:
        print(f"\nModel warmed up and kept in memory (keep_alive: 60m).")


if __name__ == "__main__":
    warmup()

