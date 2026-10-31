"""``workflow.result_schema`` writes Effect's ``Workflow.Result`` JSON
(expected values from Effect under Node): a ``Suspended`` leaves out a
``failed`` that is not set, as Effect's optional key does."""

from __future__ import annotations

from pyfect import exit as Exit
from pyfect import schema as S
from pyfect.workflow import Complete, Suspended
from pyfect.workflow.workflow import result_schema

_codec = S.to_codec_json(result_schema(success=S.String, error=S.Number))
_encode = S.encode_sync(_codec)
_decode = S.decode_unknown_sync(_codec)


def test_a_suspended_result_leaves_out_an_unset_failed():
    assert _encode(Suspended()) == {"_tag": "Suspended"}
    assert _encode(Suspended(failed=True)) == {"_tag": "Suspended", "failed": True}


def test_a_complete_result_writes_its_exit():
    assert _encode(Complete(Exit.succeed("a"))) == {
        "_tag": "Complete",
        "exit": {"_tag": "Success", "value": "a"},
    }
    assert _encode(Complete(Exit.fail(1))) == {
        "_tag": "Complete",
        "exit": {"_tag": "Failure", "cause": ({"_tag": "Fail", "error": 1},)},
    }


def test_a_suspended_result_decodes_with_or_without_failed():
    assert _decode({"_tag": "Suspended"}) == Suspended()
    assert _decode({"_tag": "Suspended", "failed": False}) == Suspended()
    assert _decode({"_tag": "Suspended", "failed": True}) == Suspended(failed=True)
