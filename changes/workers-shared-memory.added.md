- `pyfect.workers.shared_memory` (Effect's `SharedMemory`, Effect #10644): `make(kind, length)`
  allocates a zero-filled `SharedArray` in a `multiprocessing.shared_memory` segment that the
  scope frees when it closes, and `schema(kind)` is the worker message field that carries it.
  Thread and process workers both write into the sender's memory: a process worker maps the
  segment by name rather than getting a copy.
