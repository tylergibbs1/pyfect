- The request URL of a server span's synthesized 5xx error hides the query names an HttpApi
  endpoint's `RedactedNames` declares, as the span's URL attributes already did (Effect #10790).
