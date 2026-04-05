#!/usr/bin/env python3
"""Brute-force KakaoTalk userId by matching SHA512 hashes against known values."""

import hashlib
import multiprocessing
import sys
import time

TARGET_HASHES = {
    "485a6dcc047ee1de96fd0a6b80c03234bfe5d4b9260fb38f6b784b3dba153f157f764c46affd59f73359c03148a578de0140f8964ff3b8a479eca1961a3131b0",
    "957e2be29f9982afc0acb6bdce77a202af2064d4766498e4745e41c41e54a07a65e8b97f077fe6a5a3d890c064ed74e6cdfe98e55b16103b88f42092a432a795",
}


def search_range(args):
    start, end = args
    for uid in range(start, end):
        h = hashlib.sha512(str(uid).encode()).hexdigest()
        if h in TARGET_HASHES:
            return uid
    return None


def main():
    CHUNK = 5_000_000
    MAX_ID = 500_000_000
    ranges = [(i, min(i + CHUNK, MAX_ID)) for i in range(0, MAX_ID, CHUNK)]

    cores = multiprocessing.cpu_count()
    print(f"Searching 0 to {MAX_ID:,} using {cores} cores...")
    start_time = time.time()

    with multiprocessing.Pool(cores) as pool:
        for i, result in enumerate(pool.imap_unordered(search_range, ranges)):
            if result is not None:
                elapsed = time.time() - start_time
                print(f"\nFOUND userId = {result} (in {elapsed:.1f}s)")
                h = hashlib.sha512(str(result).encode()).hexdigest()
                print(f"SHA512 = {h}")
                pool.terminate()
                return
            if (i + 1) % 10 == 0:
                searched = (i + 1) * CHUNK
                elapsed = time.time() - start_time
                rate = searched / elapsed / 1_000_000
                print(f"  {searched:,} searched ({rate:.1f}M/s, {elapsed:.0f}s)")
                sys.stdout.flush()

    print(f"Not found in 0-{MAX_ID:,}")


if __name__ == "__main__":
    main()
