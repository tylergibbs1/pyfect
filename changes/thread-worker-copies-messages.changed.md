- A `ThreadWorker` and its parent hand each other copies of their messages, not the objects
  themselves, as a `ProcessWorker` does and as Effect's `postMessage` structured-clones
  them: a change made after `send` no longer reaches the other side (and on free-threaded
  Python the two sides no longer race on one object). Each message is copied by a pickle
  round trip when it is sent, so a message that can't be pickled fails `send`, and one that
  can't be unpickled is a `WorkerReceiveError`. Code that relied on sharing an object with a
  thread worker sends what changed as a new message instead, or passes the object in `send`'s
  transfer list (`send(message, [obj])`), which moves it to the thread worker uncopied; a
  message holding unpicklable values (locks, open files, lambdas) sends a picklable
  description of them instead.
