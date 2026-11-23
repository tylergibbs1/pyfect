- `Stream.merge` and `Channel.merge` start both sides as soon as the merged stream is opened,
  before its first value is asked for, and so do the combinators built on them
  (`merge_effect`, `merge_left`, `merge_right`, `merge_result`, `Channel.interrupt_when`). Both
  sides used to be scheduled to start later.
