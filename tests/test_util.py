import pytest

from gentlebot.util import rows_from_tag

@pytest.mark.parametrize("tag,expected", [
    ("INSERT 0 1", 1),
    ("INSERT 0 0", 0),
    ("UPDATE 5", 5),
    ("bogus", 0),
])
def test_rows_from_tag(tag, expected):
    assert rows_from_tag(tag) == expected
