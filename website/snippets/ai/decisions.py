from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.ai import decision, decision_model


class Ticket(TypedDict):
    message: str


team = decision.classify(
    instructions="Which team should handle this?",
    criteria={"billing": "Payments and refunds", "technical": "Outages and bugs"},
)
severity = decision.rate(instructions="How severe is it?", criteria=["minor", "major"])
urgent = decision.probability(instructions="Does this need attention now?")
triage = decision.make(
    input=S.Struct(Ticket), decisions={"team": team, "severity": severity, "urgent": urgent}
)


@fx.fn
def program():
    result = yield from decision_model.decide(triage, input={"message": "Checkout is down"})
    answers = result.answers
    # Looked up by its decision, an answer's label is one of that decision's labels.
    print(answers[team].label, answers[severity].label, answers[urgent].probability)


# A provider such as openai.decision_model.model("gpt-6-luna") answers in production.
# Here a test DecisionModel answers each named decision; its answers are checked
# (distributions must sum to 1) before the program sees them.
def answer(options: decision_model.ProviderOptions):
    return fx.succeed(
        decision_model.ProviderResponse(
            {
                "team": {
                    "_tag": "Classify",
                    "label": "technical",
                    "probabilities": {"billing": 0.2, "technical": 0.8},
                },
                "severity": {
                    "_tag": "Rate",
                    "rating": 0.9,
                    "probabilities": {"minor": 0.1, "major": 0.9},
                },
                "urgent": {"_tag": "Probability", "probability": 0.97},
            }
        )
    )


TestDecisions = fx.layer.effect(decision_model.DecisionModel, decision_model.make(decide=answer))

fx.run_main(program().pipe(fx.provide(TestDecisions)))
