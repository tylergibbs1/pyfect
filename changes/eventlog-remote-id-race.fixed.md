- Encrypted event log servers that start at the same moment on a new SQL database now agree on
  its remote id. Each one used to read the empty remote id table and insert its own id, so the
  servers disagreed about which log they serve. A start that finds no id now locks the upgrade
  record's row, reads again, and inserts only if the table is still empty.
