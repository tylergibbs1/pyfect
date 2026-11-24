from pyfect.protobuf import descriptor, message

# A FileDescriptorProto, as `protoc --descriptor_set_out` writes it (here by hand):
# syntax = "proto3"; package shop; message Order { string id = 1; repeated int32 items = 2; }
registry = descriptor.make(
    [
        {
            "name": "shop.proto",
            "package": "shop",
            "syntax": "proto3",
            "message_type": [
                {
                    "name": "Order",
                    "field": [
                        {"name": "id", "number": 1, "label": 1, "type": 9},
                        {"name": "items", "number": 2, "label": 3, "type": 5},
                    ],
                }
            ],
        }
    ]
).get_or_raise()
order = registry.get_message("shop.Order")
assert order is not None

data = message.encode(order)({"id": "A-1", "items": [3, 300]}).get_or_raise()
print(data.hex(" "))

decode = message.decode(order, max_size=1 << 20)
print(decode(data))
# A field this descriptor doesn't know is kept as bytes and written back.
print(decode(data + bytes([0x18, 0x07])).get_or_raise()[message.unknown_fields])
print(decode(bytes([0x0A, 0x05])))
