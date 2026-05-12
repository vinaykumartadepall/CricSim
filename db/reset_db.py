from db.database import get_db_connection

def drop_schemas():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DROP SCHEMA IF EXISTS history CASCADE;")
    cur.execute("DROP SCHEMA IF EXISTS simulation CASCADE;")
    conn.commit()
    print("Dropped schemas 'history' and 'simulation' with CASCADE.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    drop_schemas()
