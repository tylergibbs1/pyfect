- HttpApi: `client[Group]` (`Client.__getitem__`), deprecated and typed to reject every group.
  Use `http_api.get_group(client, Group)`, which pyright types as the group you name.
