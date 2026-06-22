import os
import psycopg2
import dotenv
dotenv.load_dotenv()
import json

class Database:
    def __init__(self):
        self.conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )

    def load_schema_metadata(
        self,
        metadata_file: str
    ):
        """
        Load metadata.json into schema_metadata table.
        """

        with open(
            metadata_file,
            "r",
            encoding="utf-8"
        ) as f:
            metadata = json.load(f)

        cursor = self.conn.cursor()

        query = """
        INSERT INTO schema_metadata
        (
            table_name,
            column_name,
            description
        )
        VALUES
        (
            %s,
            %s,
            %s
        )
        ON CONFLICT
        (
            table_name,
            column_name
        )
        DO UPDATE
        SET description = EXCLUDED.description;
        """

        for row in metadata:

            cursor.execute(
                query,
                (
                    row["table_name"],
                    row["column_name"],
                    row["description"]
                )
            )

        self.conn.commit()

        print(
            f"Loaded {len(metadata)} metadata entries"
        )

    def initialize_schema(self):
        print("Initializing database schema...")
        with open("db/schema.sql", "r", encoding="utf-8") as f:
            schema = f.read()

        with self.conn.cursor() as cursor:
            cursor.execute(schema)

        self.conn.commit()
        print("Database schema initialized successfully.")
        
        self.load_schema_metadata(
            metadata_file="db/metadata.json"
        )

    def reset_all_tables(self):
        try:
            cursor  = self.conn.cursor()
            cursor.execute("""
                DROP SCHEMA public CASCADE;
                CREATE SCHEMA public;
            """)
            self.initialize_schema()
            
            self.conn.commit()
        except Exception as e :
            self.conn.rollback()
            raise Exception(str(e))
            
    def close(self):
        self.conn.close()