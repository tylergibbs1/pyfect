- The SQL event log storages (`make_storage`, `layer_storage`, `layer_storage_subtle`) refuse a
  `poll_interval` of zero, a negative one or infinity when called, raising
  `IllegalArgumentError` (a `ValueError`) that names the value, instead of dying when the layer
  is built.
