- A derived `HttpApiClient` decodes a form-urlencoded response or declared error whose array
  field arrived as a single key (`tags=a`) into a one-element array. It failed with
  `SchemaError: Expected array` before, also under `WithHeaders`; payloads and query strings
  already did this. Port of Effect #10699.
