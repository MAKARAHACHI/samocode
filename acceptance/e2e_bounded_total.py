"""Strict bounded summation of a one-pass iterable."""


def bounded_total(values, limit):
    """Sum built-in nonnegative integers, enforcing an inclusive limit."""
    if type(limit) is not int:
        raise TypeError("limit must be a built-in int")
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    total = 0
    for value in values:
        if type(value) is not int:
            raise TypeError("values must contain built-in ints only")
        if value < 0:
            raise ValueError("values must be nonnegative")
        total += value
        if total > limit:
            raise OverflowError("total exceeds limit")
    return total
