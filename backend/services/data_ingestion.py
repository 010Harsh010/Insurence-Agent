import json
import os

import dotenv
import psycopg2
from psycopg2.extras import Json
dotenv.load_dotenv()

class PolicyLoader:
    def __db_connect(self):
        return psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )

    def load_policy_file(self, file_path: str) -> bool:
        with open(file_path, "r", encoding="utf-8") as f:
            policy = json.load(f)

        return self.ingest_data(policy)

    def ingest_data(self, data: dict) -> bool:

        db = None

        try:
            db = self.__db_connect()
            cur = db.cursor()
            

            cur.execute("""
                INSERT INTO policies (
                    policy_id,
                    policy_name,
                    insurer_name,
                    company_name,
                    employee_count,
                    policy_start_date,
                    policy_end_date,
                    renewal_status,
                    coverage,
                    opd_categories,
                    waiting_periods,
                    exclusions,
                    pre_authorization,
                    submission_rules,
                    document_requirements,
                    fraud_thresholds
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT (policy_id)
                DO UPDATE SET
                    policy_name = EXCLUDED.policy_name,
                    insurer_name = EXCLUDED.insurer_name,
                    company_name = EXCLUDED.company_name,
                    employee_count = EXCLUDED.employee_count,
                    policy_start_date = EXCLUDED.policy_start_date,
                    policy_end_date = EXCLUDED.policy_end_date,
                    renewal_status = EXCLUDED.renewal_status,
                    coverage = EXCLUDED.coverage,
                    opd_categories = EXCLUDED.opd_categories,
                    waiting_periods = EXCLUDED.waiting_periods,
                    exclusions = EXCLUDED.exclusions,
                    pre_authorization = EXCLUDED.pre_authorization,
                    submission_rules = EXCLUDED.submission_rules,
                    document_requirements = EXCLUDED.document_requirements,
                    fraud_thresholds = EXCLUDED.fraud_thresholds,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                data["policy_id"],
                data["policy_name"],
                data["insurer"],
                data["policy_holder"]["company_name"],
                data["policy_holder"]["employee_count"],
                data["policy_holder"]["policy_start_date"],
                data["policy_holder"]["policy_end_date"],
                data["policy_holder"]["renewal_status"],
                Json(data["coverage"]),
                Json(data["opd_categories"]),
                Json(data["waiting_periods"]),
                Json(data["exclusions"]),
                Json(data["pre_authorization"]),
                Json(data["submission_rules"]),
                Json(data["document_requirements"]),
                Json(data["fraud_thresholds"])
            ))

            for member in data.get("members", []):

                cur.execute("""
                    INSERT INTO members (
                        member_id,
                        policy_id,
                        primary_member_id,
                        name,
                        date_of_birth,
                        gender,
                        relationship,
                        join_date
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s
                    )
                    ON CONFLICT (member_id)
                    DO UPDATE SET
                        policy_id = EXCLUDED.policy_id,
                        primary_member_id = EXCLUDED.primary_member_id,
                        name = EXCLUDED.name,
                        date_of_birth = EXCLUDED.date_of_birth,
                        gender = EXCLUDED.gender,
                        relationship = EXCLUDED.relationship,
                        join_date = EXCLUDED.join_date
                """, (
                    member["member_id"],
                    data["policy_id"],
                    member.get("primary_member_id"),
                    member["name"],
                    member.get("date_of_birth"),
                    member.get("gender"),
                    member.get("relationship"),
                    member.get("join_date")
                ))

            for hospital_name in data.get("network_hospitals", []):

                cur.execute("""
                    INSERT INTO network_hospitals (
                        hospital_name,
                        policy_id
                    )
                    VALUES (%s,%s)
                    ON CONFLICT (hospital_name)
                    DO NOTHING
                """, (
                    hospital_name,
                    data["policy_id"]
                ))

                cur.execute("""
                    INSERT INTO hospitals (
                        hospital_name,
                        is_network_hospital
                    )
                    VALUES (%s, TRUE)
                    ON CONFLICT (hospital_name)
                    DO UPDATE SET
                        is_network_hospital = TRUE
                """, (
                    hospital_name,
                ))

            db.commit()

            print(
                f"Policy {data['policy_id']} loaded successfully."
            )

            return True

        except Exception as e:

            if db:
                db.rollback()

            print(f"Policy ingestion failed: {e}")

            return False

        finally:

            if db:
                db.close()