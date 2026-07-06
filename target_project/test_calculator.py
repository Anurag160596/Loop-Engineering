"""The specification, written as tests.

The self-healing loop treats this file as read-only ground truth: it never
edits the tests, only `calculator.py`, until every assertion here passes.
"""

from calculator import add, is_even, factorial, reverse_string, clamp


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0


def test_is_even():
    assert is_even(4) is True
    assert is_even(7) is False
    assert is_even(0) is True


def test_factorial():
    assert factorial(0) == 1
    assert factorial(1) == 1
    assert factorial(5) == 120


def test_reverse_string():
    assert reverse_string("abc") == "cba"
    assert reverse_string("") == ""
    assert reverse_string("racecar") == "racecar"


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-3, 0, 10) == 0
    assert clamp(42, 0, 10) == 10
