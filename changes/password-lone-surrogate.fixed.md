- `crypto.password` turns a password into bytes as Effect's `Password` does (`TextEncoder`): a
  lone surrogate (a JSON `"\ud800"` decodes to one) is U+FFFD. It was written as the
  surrogate's own three bytes, so a hash Effect made for such a password never verified in
  pyfect, and pyfect's never verified in Effect. Hashes of such passwords made by earlier
  pyfect versions no longer verify; every other password hashes as before. The URL username
  and password setters percent-encode a lone surrogate as `%EF%BF%BD` too, as the URL Standard
  does and as parsing a URL already did.
