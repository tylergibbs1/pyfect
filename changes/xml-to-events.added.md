- `xml.to_events(element)` turns an `xml.Element` tree, such as one `xml.elements` collected,
  back into events for `xml.encode` and `xml.encode_string`. It walks the tree without
  recursion, so a deep tree cannot overflow the stack (Effect #10687).
