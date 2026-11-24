- A tag's key is its identity, as in Effect (whose `Context` maps key strings to services):
  two tag classes declared with the same `key=` are now one service, so providing either
  satisfies both and the later provision replaces the earlier, where they used to be two
  services that only shared a display name. pyright still sees two classes, so read and
  provide such a service through one of them. Tags without `key=` keep their distinct default
  keys (module and qualified name). Declaring a tag class with a key another declaration
  already holds warns with `pyfect.context.DuplicateTagKeyWarning`, naming both (`HttpApiGroup`s
  sharing an identifier are one service too, without the warning). To keep two such tags
  apart, give them different keys, for example prefixed with your package (`key="myapp/Mail"`).
