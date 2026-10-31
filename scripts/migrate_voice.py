"""Add the voice journal without changing existing application tables/data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dotenv import load_dotenv
load_dotenv()
from telesale_agent.adapters.db.client import db_client
from telesale_agent.adapters.db.voice_store import metadata

if __name__ == "__main__":
    metadata.create_all(db_client.engine)
    print("Voice journal ready.")
