from gentlebot.tasks.daily_digest import assign_tiers


def test_assign_tiers():
    rankings = list(range(1, 20))
    roles = {'gold': 100, 'silver': 200, 'bronze': 300}
    mapping = assign_tiers(rankings, roles)
    # gold for top user
    assert mapping[1] == 100
    # silver for second user
    assert mapping[2] == 200
    # bronze for third and fourth
    assert mapping[3] == 300
    assert mapping[4] == 300
    # no roles beyond fourth user
    assert 5 not in mapping
