- `discord_chat.command_requests` raises `ValueError` naming a command or option whose name
  Discord refuses (`^[-_ʼ\p{L}\p{N}\p{sc=Deva}\p{sc=Thai}]{1,32}$`, lowercase where a
  letter has a lowercase), or whose description is not 1 to 100 characters, instead of
  building a list Discord rejects as a whole when it is registered. Effect builds the list
  unchecked.
