import pytest
from cogs.vibecheck_cog import VibeCheckCog

@pytest.mark.parametrize(
    "score,label",
    [
        (95, "Chaos Gremlin"),
        (80, "Chaos Gremlin"),
        (79, "Hype Train"),
        (60, "Hype Train"),
        (59, "Cozy Chill"),
        (40, "Cozy Chill"),
        (39, "Quiet Focus"),
        (20, "Quiet Focus"),
        (19, "Dead Server"),
        (0, "Dead Server"),
    ],
)
def test_score_to_label(score, label):
    assert VibeCheckCog.score_to_label(score)[0] == label

