- `Command.with_handler` keeps the command's error type, as Effect 4.1.4's `withHandler` does
  (Effect-TS/effect#10376): the errors of a handler it replaces, and of `validate` checks, stay
  in the result type. A command annotated with a narrower error type must widen the
  annotation, or pass the final handler to `command.make` instead.
