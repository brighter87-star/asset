"""
Database setup script.
Creates the asset database and all tables.
"""

import pymysql
from config.settings import Settings


def setup_database():
    """Create database and tables."""
    settings = Settings()

    # Connect to asset database
    conn = pymysql.connect(
        host=settings.DB_HOST,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database="asset",  # Connect directly to asset database
        charset="utf8mb4",
        autocommit=False,
    )

    try:
        with conn.cursor() as cur:
            # Read schema file
            with open("db/schema.sql", "r", encoding="utf-8") as f:
                schema_sql = f.read()

            # Split by semicolon and execute each statement
            statements = [s.strip() for s in schema_sql.split(";") if s.strip()]

            for statement in statements:
                if statement:
                    # Skip CREATE DATABASE and USE statements
                    if statement.strip().upper().startswith("CREATE DATABASE"):
                        print("Skipping CREATE DATABASE (database already exists)")
                        continue
                    if statement.strip().upper().startswith("USE"):
                        print("Skipping USE statement")
                        continue

                    print(f"Executing: {statement[:80]}...")
                    cur.execute(statement)

        conn.commit()
        print("\n✓ Database and tables created successfully!")

    except Exception as e:
        print(f"\n✗ Error creating database: {e}")
        import traceback
        traceback.print_exc()

    finally:
        conn.close()


if __name__ == "__main__":
    setup_database()
