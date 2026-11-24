- The Teams docs say that the key set is refetched for an unknown key at most once every 30
  seconds, as in Effect's `Jwks`, so a token signed with a key Microsoft added within 30 seconds of
  the last fetch is refused with 403 until those 30 seconds pass.
