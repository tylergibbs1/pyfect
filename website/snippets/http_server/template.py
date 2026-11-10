from html import escape

import pyfect as fx
from pyfect.http import template

comment = "<script>alert(1)</script>"

# Values go in as they are: this comment would run in the reader's browser.
raw = fx.run_blocking(template.make(["<p>", "</p>"], comment))
assert raw == "<p><script>alert(1)</script></p>"

# Escape text that isn't yours before it goes in.
safe = fx.run_blocking(template.make(["<p>", "</p>"], escape(comment)))
print(safe)
