from pyfect import rational

third = rational.from_string_unsafe("1/3")
one = third.sum(third).sum(third)
print(one.format(), repr(third.multiply(rational.from_big_int(3))))
assert one == rational.from_big_int(1)  # exactly one, no rounding

# 0.1 is the float's exact binary value; "6/-4" is reduced to lowest terms.
print(rational.from_number_unsafe(0.1).format())
print(rational.from_string_unsafe("6/-4").format())
assert rational.from_string("1/0") is None

print(third.to_big_decimal(scale=3).format(), third.to_number_unsafe())
