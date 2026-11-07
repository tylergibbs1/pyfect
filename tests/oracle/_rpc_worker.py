"""The child process of the "e2e worker process" suite (Effect's
browser/test/fixtures/rpc-worker.ts): run with ``python -m oracle._rpc_worker``."""

from oracle._rpc import run_worker

if __name__ == "__main__":
    run_worker()
