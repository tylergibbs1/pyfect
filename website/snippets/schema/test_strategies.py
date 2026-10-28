from hypothesis import given

from pyfect import schema as S


class Signup(S.Class):
    username: str = S.field(S.String.check(S.is_min_length(3), S.is_max_length(20)))
    age: int = S.field(S.Int.check(S.is_between(minimum=13, maximum=130)))
    referrer: str | None = None


SignupJson = S.from_json_string(Signup)


# to_strategy draws values that satisfy every check; Hypothesis shrinks a failure
# to the smallest example. Needs the pyfect[hypothesis] extra.
@given(S.to_strategy(Signup))
def test_signups_survive_json(signup: Signup):
    text = S.encode_sync(SignupJson)(signup)
    assert S.decode_unknown_sync(SignupJson)(text) == signup


@given(S.to_strategy(Signup))
def test_checks_hold(signup: Signup):
    assert 3 <= len(signup.username) <= 20
    assert 13 <= signup.age <= 130
