"""The WHATWG URL Standard in pure Python, matched against Node's ``URL``
on the web-platform-tests URL suite: the basic URL parser, the host parser
with IDNA (UTS #46, Unicode 17 as in Node), the ``URL`` setters and
``application/x-www-form-urlencoded``. ``pyfect._url.Url`` is the public
face; this package works on ``UrlRecord`` values."""

from pyfect._whatwg_url import _form as form
from pyfect._whatwg_url import _setters as setters
from pyfect._whatwg_url._parser import parse
from pyfect._whatwg_url._record import SPECIAL_PORTS, UrlRecord

__all__ = ["SPECIAL_PORTS", "UrlRecord", "form", "parse", "setters"]
