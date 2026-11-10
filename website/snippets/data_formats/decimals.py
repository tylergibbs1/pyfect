from pyfect import big_decimal
from pyfect.big_decimal import BigDecimal

price = big_decimal.from_string_unsafe("0.1")
fee = big_decimal.from_string_unsafe("0.2")
total = price.sum(fee)
print(total.format())
assert total == big_decimal.from_string_unsafe("0.30")  # 0.3 equals 0.30

# Division gives 100 significant digits; dividing by zero gives None.
third = big_decimal.from_string_unsafe("10").divide_unsafe(BigDecimal(3, 0))
print(third.format()[:12])
assert price.divide(BigDecimal(0, 0)) is None

amount = big_decimal.from_string_unsafe("2.345")
print(amount.round(scale=2).format(), amount.round(scale=2, mode="half-even").format())
print(amount.floor(1).format(), amount.multiply(amount).format())
assert big_decimal.from_string("12,5") is None
