"""
Run this file once to create DB tables in Neon.
It creates tables defined in src/db/models.py.
"""

from src.db.session import engine, Base
import src.db.models  # noqa: F401  (ensures models are registered)

def main():
    Base.metadata.create_all(bind=engine)
    print("✅ DB tables created successfully")

if __name__ == "__main__":
    main()
