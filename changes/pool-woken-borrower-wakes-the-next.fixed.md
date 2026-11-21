- A `Pool` borrower no longer sleeps forever next to a free item. A woken borrower whose run
  was busy kept its place in line; a borrower that came meanwhile queued behind it and slept,
  and when the woken one took its item it left the line without waking it, though another
  item was free. Leaving the line now always wakes the next borrower asleep while an item is
  free. A pool made in a run that had ended hung growing about one time in 250 without the GIL.
