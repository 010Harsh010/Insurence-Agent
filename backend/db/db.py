import os
import psycopg2
import dotenv
dotenv.load_dotenv()

class Database:
    def __init__(self):
        self.conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )

    def initialize_schema(self):
        print("Initializing database schema...")
        with open("db/schema.sql", "r", encoding="utf-8") as f:
            schema = f.read()

        with self.conn.cursor() as cursor:
            cursor.execute(schema)

        self.conn.commit()
        print("Database schema initialized successfully.")

    def close(self):
        self.conn.close()