"""Circuit breakers per key (Effect's ``effect/persistence/CircuitBreaker``)::

    breaker = yield from circuit_breaker.make(
        trip_policy=circuit_breaker.consecutive(5), open_duration=30
    )
    yield from call_api.pipe(breaker.execute(key="api"))

A key's circuit is ``Closed`` (calls run and are counted), ``Open`` (calls
fail with ``CircuitOpen`` for the open time) or ``HalfOpen`` (one probe
runs; its success closes the circuit, its failure reopens it). The trip
policy is ``consecutive`` failures or a failure ``rate``; ``classify``
decides how a call counts (``success``, ``ignored``, ``failure()``), and
``on_rejection="allow"`` runs a call the circuit refuses, unrecorded.

States live in a ``CircuitBreakerStore``: ``layer_store_memory``, or
``layer_store_redis`` (shared by every process using that Redis).
"""

from pyfect._public import publish
from pyfect.persistence.circuit_breaker._breaker import (
    CircuitBreaker,
    CircuitBreakerService,
    Classifier,
    Executor,
    OnRejection,
    OnStoreError,
    OpenDuration,
    layer,
    make,
)
from pyfect.persistence.circuit_breaker._errors import (
    CIRCUIT_BREAKER_ERROR_REASON,
    CircuitBreakerError,
    CircuitBreakerErrorReason,
    CircuitBreakerStoreError,
    CircuitHalfOpen,
    CircuitOpen,
)
from pyfect.persistence.circuit_breaker._memory import layer_store_memory, make_store_memory
from pyfect.persistence.circuit_breaker._redis import (
    layer_store_redis,
    layer_store_redis_config,
    make_store_redis,
)
from pyfect.persistence.circuit_breaker._store import (
    CircuitBreakerStore,
    CircuitBreakerStoreService,
    Record,
)
from pyfect.persistence.circuit_breaker._types import (
    Admission,
    ClassifyContext,
    Closed,
    CloseTransition,
    Consecutive,
    FailureOutcome,
    HalfOpen,
    HalfOpenTransition,
    IgnoredOutcome,
    Open,
    OpenTransition,
    Outcome,
    OutcomeKind,
    Rate,
    State,
    SuccessOutcome,
    Transition,
    TripPolicy,
    consecutive,
    failure,
    ignored,
    rate,
    success,
)

__all__ = [
    "CIRCUIT_BREAKER_ERROR_REASON",
    "Admission",
    "CircuitBreaker",
    "CircuitBreakerError",
    "CircuitBreakerErrorReason",
    "CircuitBreakerService",
    "CircuitBreakerStore",
    "CircuitBreakerStoreError",
    "CircuitBreakerStoreService",
    "CircuitHalfOpen",
    "CircuitOpen",
    "Classifier",
    "ClassifyContext",
    "CloseTransition",
    "Closed",
    "Consecutive",
    "Executor",
    "FailureOutcome",
    "HalfOpen",
    "HalfOpenTransition",
    "IgnoredOutcome",
    "OnRejection",
    "OnStoreError",
    "Open",
    "OpenDuration",
    "OpenTransition",
    "Outcome",
    "OutcomeKind",
    "Rate",
    "Record",
    "State",
    "SuccessOutcome",
    "Transition",
    "TripPolicy",
    "consecutive",
    "failure",
    "ignored",
    "layer",
    "layer_store_memory",
    "layer_store_redis",
    "layer_store_redis_config",
    "make",
    "make_store_memory",
    "make_store_redis",
    "rate",
    "success",
]

publish(globals())
