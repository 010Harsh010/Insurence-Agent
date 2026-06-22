import json
import re
from collections import defaultdict
from typing import Dict, List, Optional
import os
import dotenv
dotenv.load_dotenv()
import pandas as pd
import psycopg2
from pydantic import BaseModel
import sub_agent.llm as llm


# ============================================================
# SCHEMA LINKING OUTPUT
# ============================================================

class SchemaLinkOutput(BaseModel):
    tables: List[str]
    columns: List[str]
    filters: Dict[str, str]
    joins: List[str]


# ============================================================
# POSTGRES TEXT TO SQL AGENT
# ============================================================
class PostgreSQLQueryAgent:

    def __init__(
        self):
        self.llm_client = llm.LLMClient()

        self.schema_json = {}
        self.schema_metadata = {}

        self._load_db_schema()

    # ============================================================
    # DATABASE CONNECTION
    # ============================================================

    def _connect_db(self):

        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "claims"),
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASSWORD", "admin"),
        )

    def disconnect_db(self, conn):

        if conn:
            conn.close()

    # ============================================================
    # LOAD METADATA
    # ============================================================

    def _load_schema_metadata(
        self,
        cursor
    ):

        metadata = defaultdict(dict)

        try:

            cursor.execute("""
                SELECT
                    table_name,
                    column_name,
                    description
                FROM schema_metadata
            """)

            rows = cursor.fetchall()

            for table_name, column_name, description in rows:

                if column_name is None:
                    metadata[table_name]["__table__"] = description
                else:
                    metadata[table_name][column_name] = description

        except Exception:
            print(
                "schema_metadata table not found."
            )

        return metadata

    # ============================================================
    # LOAD DATABASE SCHEMA
    # ============================================================

    def _load_db_schema(self):
        try: 
            conn = self._connect_db()
            cursor = conn.cursor()

            self.schema_metadata = (
                self._load_schema_metadata(cursor)
            )

            cursor.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
            """)

            tables = [
                row[0]
                for row in cursor.fetchall()
            ]

            schema = {}

            for table in tables:

                if table == "schema_metadata":
                    continue

                schema[table] = {
                    "columns": []
                }

                # ------------------------------------------------
                # Columns
                # ------------------------------------------------

                cursor.execute("""
                    SELECT
                        column_name,
                        data_type
                    FROM information_schema.columns
                    WHERE table_name = %s
                    ORDER BY ordinal_position
                """, (table,))

                columns = cursor.fetchall()

                # ------------------------------------------------
                # Primary Keys
                # ------------------------------------------------

                cursor.execute("""
                    SELECT
                        kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.table_name = %s
                    AND tc.constraint_type = 'PRIMARY KEY'
                """, (table,))

                primary_keys = {
                    row[0]
                    for row in cursor.fetchall()
                }

                # ------------------------------------------------
                # Foreign Keys
                # ------------------------------------------------

                cursor.execute("""
                    SELECT
                        kcu.column_name,
                        ccu.table_name,
                        ccu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage ccu
                        ON ccu.constraint_name = tc.constraint_name
                    WHERE tc.constraint_type='FOREIGN KEY'
                    AND tc.table_name = %s
                """, (table,))

                foreign_keys = {
                    row[0]: {
                        "table": row[1],
                        "column": row[2]
                    }
                    for row in cursor.fetchall()
                }

                # ------------------------------------------------
                # Build Schema
                # ------------------------------------------------

                for column_name, column_type in columns:

                    col = {
                        "name": column_name,
                        "type": column_type
                    }

                    if column_name in primary_keys:
                        col["key"] = "PRIMARY"

                    if column_name in foreign_keys:

                        col["key"] = "FOREIGN"

                        col["references"] = (
                            foreign_keys[column_name]
                        )

                    schema[table]["columns"].append(
                        col
                    )

            conn.close()

            self.schema_json = schema
        except Exception as e:
            self.conn.rollback()
            raise

    # ============================================================
    # SCHEMA DESIGN FOR LLM
    # ============================================================

    def _create_schema_design(self):

        schema_text = ""
        relationships = []

        for table, details in self.schema_json.items():

            schema_text += f"\nTable: {table}\n"

            table_desc = (
                self.schema_metadata
                .get(table, {})
                .get("__table__")
            )

            if table_desc:
                schema_text += (
                    f"Description: {table_desc}\n"
                )

            schema_text += "Columns:\n"

            for col in details["columns"]:

                schema_text += (
                    f"  - {col['name']} "
                    f"({col['type']})"
                )

                description = (
                    self.schema_metadata
                    .get(table, {})
                    .get(col["name"])
                )

                if description:

                    schema_text += (
                        f' desc="{description}"'
                    )

                if col.get("key") == "PRIMARY":

                    schema_text += (
                        " [PRIMARY]"
                    )

                if col.get("key") == "FOREIGN":

                    ref = col["references"]

                    schema_text += (
                        f" [FOREIGN -> "
                        f"{ref['table']}"
                        f".{ref['column']}]"
                    )

                    relationships.append(
                        {
                            "from_table": table,
                            "from_column": col["name"],
                            "to_table": ref["table"],
                            "to_column": ref["column"]
                        }
                    )

                schema_text += "\n"

        if relationships:

            schema_text += (
                "\nRelationships:\n"
            )

            for rel in relationships:

                schema_text += (
                    f"  - "
                    f"{rel['from_table']}."
                    f"{rel['from_column']} "
                    f"-> "
                    f"{rel['to_table']}."
                    f"{rel['to_column']}\n"
                )
                
                
        print(schema_text)

        return schema_text

    # ============================================================
    # SCHEMA LINKING
    # ============================================================

    def _schema_linking(
        self,
        user_query: str
    ) -> Optional[SchemaLinkOutput]:

        schema = self._create_schema_design()

        prompt = f"""
You are a schema linking agent.

DATABASE SCHEMA:

{schema}

RULES:

1. Use only provided schema.
2. Never invent tables.
3. Never invent columns.
4. Identify:
    - tables
    - columns
    - joins
    - filters

Return JSON only.

OUTPUT FORMAT:

{json.dumps(
    SchemaLinkOutput.model_json_schema(),
    indent=2
)}

USER QUERY:

{user_query}
"""

        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]

        try:

            response = (
                self.llm_client
                .call_llm_json(messages)
            )

            return (
                SchemaLinkOutput
                .model_validate(response)
            )

        except Exception as e:

            print(
                "Schema Linking Error:",
                e
            )

            return None

    # ============================================================
    # SQL GENERATION
    # ============================================================

    def _generate_sql(
        self,
        user_query,
        schema_link_output=None
    ):

        schema = self._create_schema_design()

        prompt = f"""
You are an expert PostgreSQL Text-to-SQL agent.

DATABASE SCHEMA:

{schema}

RULES:

1. Generate valid PostgreSQL SQL.
2. Use only schema tables.
3. Use only schema columns.
4. Never invent columns.
5. Use proper joins.
6. Use aggregations when needed.
7. Output SQL only.
8. No markdown.
9. No explanation.

{f"Schema Linking Information:\n{schema_link_output.model_dump_json(indent=2)}" if schema_link_output else ""}

Question:

{user_query}
"""

        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]

        response = (
            self.llm_client
            .call_llm(messages)
        )

        return response.strip()

    # ============================================================
    # SQL VALIDATION
    # ============================================================

    def _validate_sql(
        self,
        sql_query
    ):

        if not sql_query:
            raise ValueError(
                "Empty SQL generated"
            )

        match = re.search(
            r"```sql(.*?)```",
            sql_query,
            re.DOTALL | re.IGNORECASE
        )

        if match:
            sql_query = (
                match.group(1)
                .strip()
            )

        sql = sql_query.strip().upper()

        if not sql.startswith("SELECT"):
            raise ValueError(
                "Only SELECT queries are allowed"
            )

        return sql_query

    # ============================================================
    # SQL EXECUTION
    # ============================================================

    def _execute_sql(
        self,
        sql_query
    ):

        conn = self._connect_db()

        try:
            cursor = conn.cursor()

            cursor.execute(sql_query)

            db_results = cursor.fetchall()
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                response_df = pd.DataFrame(db_results, columns=columns)
            else:
                response_df = pd.DataFrame(db_results)
            
            print(response_df)
            return response_df

        finally:

            conn.close()

    # ============================================================
    # MAIN RUN
    # ============================================================

    def run(
        self,
        user_query: str,
        enable_schema_linking=False
    ):

        if not user_query.strip():

            raise ValueError(
                "Empty query"
            )

        schema_link_output = None

        if enable_schema_linking:

            schema_link_output = (
                self._schema_linking(
                    user_query
                )
            )

            print(
                "\nSchema Linking Output:\n"
            )

            print(
                schema_link_output
            )

        sql_query = (
            self._generate_sql(
                user_query,
                schema_link_output
            )
        )

        print(
            "\nGenerated SQL:\n"
        )

        print(sql_query)

        sql_query = (
            self._validate_sql(
                sql_query
            )
        )

        df = (
            self._execute_sql(
                sql_query
            )
        )

        return {
            "query": user_query,
            "sql": sql_query,
            "row_count": len(df),
            "data": df.to_dict(
                orient="records"
            )
        }


# ============================================================
# EXAMPLE
# ============================================================

if __name__ == "__main__":

    from sub_agent.llm import LLMClient


    llm_client = LLMClient()

    agent = PostgreSQLQueryAgent()

    while True:

        query = input(
            "\nAsk SQL > "
        )

        if query.lower() == "exit":
            break

        try:

            result = agent.run(
                user_query=query,
                enable_schema_linking=True
            )

            print(
                "\nRows:",
                result["row_count"]
            )

            print(
                json.dumps(
                    result["data"],
                    indent=2,
                    default=str
                )
            )

        except Exception as e:

            print(
                "\nError:",
                e
            )