import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    discord_token: str = ""
    pg_dsn: str | None = None
    debug: bool = False
    command_prefix: str = "!"

    class Config:
        env_file = ".env"

settings = Settings()

TOKEN = settings.discord_token

# Legacy ID constants for compatibility
GUILD_ID = int(os.getenv("GUILD_ID", 0))
FINANCE_CHANNEL_ID = int(os.getenv("FINANCE_CHANNEL_ID", 0))
MARKET_CHANNEL_ID = int(os.getenv("MARKET_CHANNEL_ID", 0))
F1_DISCORD_CHANNEL_ID = int(os.getenv("F1_DISCORD_CHANNEL_ID", 0))
DAILY_PING_CHANNEL = int(os.getenv("DAILY_PING_CHANNEL", 0))
MONEY_TALK_CHANNEL = int(os.getenv("MONEY_TALK_CHANNEL", 0))
ROLE_GHOST = int(os.getenv("ROLE_GHOST", 0))
ROLE_TOP_POSTER = int(os.getenv("ROLE_TOP_POSTER", 0))
ROLE_CERTIFIED_BANGER = int(os.getenv("ROLE_CERTIFIED_BANGER", 0))
ROLE_TOP_CURATOR = int(os.getenv("ROLE_TOP_CURATOR", 0))
ROLE_FIRST_DROP = int(os.getenv("ROLE_FIRST_DROP", 0))
ROLE_SUMMONER = int(os.getenv("ROLE_SUMMONER", 0))
ROLE_LORE_CREATOR = int(os.getenv("ROLE_LORE_CREATOR", 0))
ROLE_REACTION_ENGINEER = int(os.getenv("ROLE_REACTION_ENGINEER", 0))
ROLE_GALAXY_BRAIN = int(os.getenv("ROLE_GALAXY_BRAIN", 0))
ROLE_WORDSMITH = int(os.getenv("ROLE_WORDSMITH", 0))
ROLE_SNIPER = int(os.getenv("ROLE_SNIPER", 0))
ROLE_NIGHT_OWL = int(os.getenv("ROLE_NIGHT_OWL", 0))
ROLE_COMEBACK_KID = int(os.getenv("ROLE_COMEBACK_KID", 0))
ROLE_GHOSTBUSTER = int(os.getenv("ROLE_GHOSTBUSTER", 0))
ROLE_SHADOW_FLAG = int(os.getenv("ROLE_SHADOW_FLAG", 0))
ROLE_LURKER_FLAG = int(os.getenv("ROLE_LURKER_FLAG", 0))
ROLE_NPC_FLAG = int(os.getenv("ROLE_NPC_FLAG", 0))
INACTIVE_DAYS = int(os.getenv("INACTIVE_DAYS", 14))
