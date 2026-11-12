"""
Pure-stdlib reproducible test table: primes with derived, human-interesting fields.
No third-party dependencies. Deterministic output (no RNG needed).

The spelled column can be restyled for a live demo; that mapping is also
deterministic, driven by an MD5 hash of ``(cycle, rank)``.
"""

from __future__ import annotations

import hashlib
from typing import ClassVar, Iterator


class PrimeRows:
    """Class to generate interesting, deterministic data for table presentation """
    primes: ClassVar[list[int]] = []
    ones: ClassVar[list[str]] = [
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen",
    ]
    tens: ClassVar[list[str]] = [
        "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
        "eighty", "ninety",
    ]
    scales: ClassVar[list[tuple[int, str]]] = [
        (10**12, "trillion"),
        (10**9, "billion"),
        (10**6, "million"),
        (1000, "thousand"),
    ]

    # ---------------------------------------------------------------------------
    # 1. Sieve of Eratosthenes — yields primes up to `limit`.
    # ---------------------------------------------------------------------------
    def make_primes(self) -> list[int]:
        """Return all primes <= limit via a bytearray sieve. ~10 ms for limit=10**6."""
        if self.primes:
            return self.primes
        limit = 200_000  # raise if need be
        sieve = bytearray([1]) * (limit + 1)
        sieve[0] = sieve[1] = 0
        # Only need to sieve up to sqrt(limit)
        for i in range(2, int(limit ** 0.5) + 1):
            if sieve[i]:
                # slice-assignment is C-speed
                sieve[i * i :: i] = bytearray(len(sieve[i * i :: i]))
        PrimeRows.primes = [i for i, is_p in enumerate(sieve) if is_p]
        return self.primes


    # ---------------------------------------------------------------------------
    # 2. Number spelling — supports 0..10**12ish, negative numbers too.
    # ---------------------------------------------------------------------------
    def spell_number(self, n: int) -> str:
        """ convert a number to its brief (no ands) spelled out word form"""
        if n < 0:
            return "minus " + self.spell_number(-n)
        if n < 20:
            return self.ones[n]
        if n < 100:
            tens, rem = divmod(n, 10)
            return self.tens[tens] + ("-" + self.ones[rem] if rem else "")
        if n < 1000:
            hundreds, rem = divmod(n, 100)
            s = self.ones[hundreds] + " hundred"
            return s + (" " + self.spell_number(rem) if rem else "")
        for scale, name in self.scales:
            if n >= scale:
                high, rem = divmod(n, scale)
                s = self.spell_number(high) + " " + name
                return s + (" " + self.spell_number(rem) if rem else "")
        raise ValueError(f"out of range: {n}")


    # ---------------------------------------------------------------------------
    # 3. Derived fields
    # ---------------------------------------------------------------------------
    @staticmethod
    def digit_sum(n: int) -> int:
        """Sum the digits of a number """
        return sum(int(c) for c in str(n))


    @staticmethod
    def is_palindrome(n: int) -> bool:
        """ Return whether palindrome"""
        s = str(n)
        return s == s[::-1]


    # ---------------------------------------------------------------------------
    # 3b. Deterministic style churn for the basic pager demo.
    # ---------------------------------------------------------------------------
    QUOTE_STYLES = ("", "'", '"')
    CASE_STYLES = ("lower", "title", "upper")
    STYLE_COUNT = len(QUOTE_STYLES) * len(CASE_STYLES)

    @staticmethod
    def pseudo_random_map(value: int, bound: int = 9) -> int:
        """Map any integer to a well-mixed value in ``range(bound)`` (MD5)."""
        if value == 0:
            byte_data = b"\x00"
        else:
            # Round up with one spare bit for the two's-complement sign, so
            # positive values whose bit_length is a multiple of 8 (128, 256,
            # ...) do not overflow a signed field.
            byte_length = (value.bit_length() + 8) // 8
            byte_data = value.to_bytes(byte_length, "big", signed=True)
        digest = hashlib.md5(byte_data).digest()
        return int.from_bytes(digest, "big") % bound

    @classmethod
    def apply_style(cls, text: str, state: int) -> str:
        """Apply one of the nine quote x case styles to *text*."""
        quote = cls.QUOTE_STYLES[state // len(cls.CASE_STYLES)]
        case = cls.CASE_STYLES[state % len(cls.CASE_STYLES)]
        if case == "title":
            text = text.title()
        elif case == "upper":
            text = text.upper()
        return quote + text + quote

    @classmethod
    def altered_spelled(cls, spelled: str, rank: int, iteration: int,
                        interval: int) -> str:
        """Return *spelled* with the style this row has in *iteration*'s cycle.

        A row is reassigned once per ``interval`` passes, at phase
        ``rank % interval``.  The style is hashed from ``(cycle, rank)``, so it
        persists until the row's next reassignment instead of flickering for a
        single pass.  Before the row's first reassignment the base text comes
        back unchanged.
        """
        if interval <= 0:
            raise ValueError("interval must be positive")
        cycle, phase = divmod(iteration, interval)
        if phase < rank % interval:
            cycle -= 1
        if cycle < 0:
            return spelled
        state = cls.pseudo_random_map((cycle << 32) + rank, cls.STYLE_COUNT)
        return cls.apply_style(spelled, state)


    # ---------------------------------------------------------------------------
    # 4. The generator — yields dicts, one per row.
    # ---------------------------------------------------------------------------
    def generate_rows(self,
        start_rank: int = 1,
        end_rank: int = 10_000
    ) -> Iterator[dict]:
        """
        1-based inclusive rank range of primes. Yields one dict per prime.

        sieve_limit=200_000 comfortably covers the first ~18k primes; bump it
        if you ask for higher ranks.
        """
        primes = self.make_primes()
        if end_rank > len(primes):
            raise ValueError(
                f"end_rank={end_rank} exceeds available primes ({len(primes)}). "
                f"Increase sieve_limit."
            )
        prev = primes[start_rank - 2] if start_rank > 1 else None
        for rank in range(start_rank, end_rank + 1):
            p = primes[rank - 1]
            yield {
                "rank":               rank,
                "prime":              p,
                "digits":             len(str(p)),
                "digit_sum":          self.digit_sum(p),
                "binary":             bin(p)[2:],       # no "0b" prefix
                "mod_10":             p % 10,
                "gap_from_previous":  None if prev is None else p - prev,
                "is_palindrome":      self.is_palindrome(p),
                "spelled":            self.spell_number(p),
            }
            prev = p


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import time

    prime_rows = PrimeRows()
    t0 = time.perf_counter()
    rows = list(prime_rows.generate_rows(1, 10_000))
    dt = time.perf_counter() - t0
    print(f"{len(rows):,} rows in {dt*1000:.1f} ms\n")

    # First 5, last 2
    for r in rows[:5]:
        print(r)
    print("...")
    for r in rows[-2:]:
        print(r)

    # A quick sanity check that the middle row makes sense
    r = rows[199]  # 200th prime
    assert r["rank"] == 200 and r["prime"] == 1223
    print(f"\n200th prime: {r['prime']} -> {r['spelled']!r}")
