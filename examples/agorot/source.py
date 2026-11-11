def agorot_total(values):
    """Return the sum of nonnegative built-in integers in *values*.

    Iterate only once without modifying the input collection. Reject booleans,
    integer subclasses, and other non-built-in ints with TypeError; reject
    negative built-in integers with ValueError. Python integers are unbounded.
    """
    total = 0
    for value in values:
        if type(value) is not int:
            raise TypeError("each agorot value must be a built-in int")
        if value < 0:
            raise ValueError("agorot values must be nonnegative")
        total += value
    return total
