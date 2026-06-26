import os
import psycopg2
from psycopg2 import sql

DB_NAME = os.environ.get('DB_NAME', 'cricket_db')
DB_USER = os.environ.get('DB_USER', 'vnaykumart')
DB_PASS = os.environ.get('DB_PASS', '')
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '5432')

def get_db_connection(autocommit=True):
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT
    )
    if autocommit:
        conn.autocommit = True
    return conn

def create_database():
    try:
        conn = psycopg2.connect(
            dbname='postgres',
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT
        )
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (DB_NAME,))
        exists = cur.fetchone()

        if not exists:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(DB_NAME))
            )
            print(f"Database {DB_NAME} created successfully.")
        else:
            print(f"Database {DB_NAME} already exists.")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error creating database: {e}")

def initialize_schema():
    """Apply schema DDL then seed reference data. Idempotent."""
    conn = get_db_connection()
    cur = conn.cursor()

    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path, 'r') as f:
        cur.execute(f.read())
    conn.commit()
    print("Schema initialized.")

    seed_path = os.path.join(os.path.dirname(__file__), 'seed_data.sql')
    with open(seed_path, 'r') as f:
        cur.execute(f.read())
    conn.commit()
    print("Seed data applied.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    create_database()
    initialize_schema()
