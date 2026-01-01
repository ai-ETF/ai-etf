import os


class Settings:
    def __init__(self):
        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        self.SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        self.DB_PATH = os.getenv("ETFSERVER_DB_PATH", "server_data.db")
        self.EMBED_DIM = int(os.getenv("ETFSERVER_EMBED_DIM", "128"))


SETTINGS = Settings()
