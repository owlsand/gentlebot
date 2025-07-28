from gentlebot.tasks.daily_digest import assign_tiers


def test_assign_tiers():
    rankings = list(range(1, 20))
    roles = {'gold': 100, 'silver': 200, 'bronze': 300}
    mapping = assign_tiers(rankings, roles)
    # gold for top three users
    assert mapping[1] == 100
    assert mapping[2] == 100
    assert mapping[3] == 100
    # silver for ranks 4-8
    for uid in range(4, 9):
        assert mapping[uid] == 200
    # bronze for ranks 9-15
    for uid in range(9, 16):
        assert mapping[uid] == 300
    # no roles beyond rank 15
    assert 16 not in mapping
