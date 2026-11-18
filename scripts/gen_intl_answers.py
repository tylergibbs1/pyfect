"""Record ``tests/oracle/intl_answers.json``: what Effect's ``DateTime.format``,
``formatUtc`` and ``formatLocal`` (``Intl.DateTimeFormat`` under Node) answer
for every case of ``tests/oracle/intl_matrix.py``::

    uv run python scripts/gen_intl_answers.py

Runs ``tests/oracle/intl_oracle.ts`` on the ``node`` on ``PATH`` with
``LC_ALL=en_US.UTF-8`` (the cases without a locale, or with one ICU lacks, use
the environment's) and ``TZ=UTC``, and records Node's, ICU's, CLDR's and tz's
versions with the answers and a digest of the cases, so the test notices a
changed matrix. Regenerate ``src/pyfect/date_time/_intl/cldr.zip``
(``scripts/gen_intl_cldr.py``) with the same Node.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from tests import _effect_ref  # noqa: E402, TID251
from tests.oracle.intl_matrix import ANSWERS, ENVIRONMENT, ORACLE, cases, digest  # noqa: E402, TID251


def main() -> None:
    effect = _effect_ref.checkout()
    found = cases()
    result = subprocess.run(
        ["node", str(ORACLE)],
        input=json.dumps(found),
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **ENVIRONMENT, _effect_ref.ENV: str(effect)},
    )
    recorded = json.loads(result.stdout)
    recorded["cases"] = digest(found)
    ANSWERS.write_text(json.dumps(recorded, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
