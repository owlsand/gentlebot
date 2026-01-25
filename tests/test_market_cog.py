from gentlebot.cogs import market_cog


def test_period_map():
    """Test that period_map returns correct fetch/interval tuples."""
    assert market_cog.MarketCog._period_map("1d") == ("1d", "1m")
    assert market_cog.MarketCog._period_map("1w") == ("7d", "5m")
    assert market_cog.MarketCog._period_map("1mo") == ("1mo", "1d")
    assert market_cog.MarketCog._period_map("1y") == ("1y", "1d")
    assert market_cog.MarketCog._period_map("5y") == ("5y", "1wk")
    assert market_cog.MarketCog._period_map("10y") == ("10y", "1mo")
