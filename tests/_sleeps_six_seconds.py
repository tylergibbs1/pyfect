"""Completes 6 s of live-clock sleep in about 0.1 s of real time
(`test_doc_snippets.py::test_a_snippet_sleeping_over_the_limit_fails`)."""

import pyfect as fx

fx.run_main(fx.for_each(range(60), lambda _: fx.sleep("100 millis"), concurrency="unbounded"))
