"""A tiny calculator library — with intentional bugs.

The self-healing loop's job is to make `test_calculator.py` pass by editing
*this* file. Every function below has a deliberate defect; the test suite is
the source of truth for correct behaviour.
"""


def add(a, b):
    # BUG: subtracts instead of adding.
    return a - b


def is_even(n):
    # BUG: returns True for odd numbers.
    return n % 2 == 1


def factorial(n):
    # BUG: off-by-one — range stops one short, so n! comes out as (n-1)!.
    result = 1
    for i in range(1, n):
        result *= i
    return result


def reverse_string(s):
    # BUG: returns the string unchanged instead of reversed.
    return s


def clamp(value, low, high):
    # BUG: ignores the lower bound entirely.
    if value > high:
        return high
    return value
