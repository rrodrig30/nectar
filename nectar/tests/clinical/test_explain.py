"""Clinical golden test for grounded narration. [INVARIANT] Must pass in CI.

An explanation that cites an unretrieved guideline, names an out-of-set recipe, or makes a numeric
claim with no citation is stripped, so no ungrounded clinical claim reaches the clinician.
See nectar/docs/PDD.md Section 12 (interaction golden), SDD Section 7.
"""
from nectar.interact.explain import ground, narrate

ALLOWED_CITES = {"kdoqi-potassium", "dash-sodium"}
ALLOWED_DISHES = {"dish:mashed_potato", "dish:lentil_soup"}


class _Backend:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    def generate(self, prompt: str, system: str | None = None,
                 temperature: float | None = None) -> str:
        return self._reply


def test_ground_keeps_only_grounded_sentences():
    text = (
        "{{dish:mashed_potato}} is a good fit, its potassium is 300 mg [[kdoqi-potassium]]. "        # keep
        "{{dish:fried_chicken}} is also fine. "                                                        # out-of-set dish -> strip
        "It lowers sodium to 200 mg. "                                                                 # numeric, uncited -> strip
        "Avoid it per [[made-up-guideline]]. "                                                         # bad citation -> strip
        "Variety helps adherence."                                                                     # non-numeric, no marker -> keep
    )
    out = ground(text, ALLOWED_CITES, ALLOWED_DISHES)
    assert "mashed_potato" in out and "kdoqi-potassium" in out
    assert "fried_chicken" not in out
    assert "200 mg" not in out
    assert "made-up-guideline" not in out
    assert "Variety helps adherence" in out


def test_narrate_grounds_backend_output():
    raw = "{{dish:lentil_soup}} suits the renal limit [[kdoqi-potassium]]. {{dish:steak}} does too."
    out = narrate("summary", ALLOWED_CITES, ALLOWED_DISHES, _Backend(raw))
    assert "lentil_soup" in out and "steak" not in out
