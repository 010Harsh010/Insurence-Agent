import psycopg2
import dotenv
import os
dotenv.load_dotenv()
import datetime
class Policy_Claim:
    def __init__(self):
        pass
    
    def __db_connect(self):
        return psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )
        
    def claim_policy(self,claim_data):
        db = None
        try:
            db = self.__db_connect()
            cur = db.cursor()
            
            # Step 1 Check Company member Exists
            cur.execute("""        
            select name from members where member_id = %s    
            """,(claim_data["member_id"]))
            
            user  = cur.fetchone()
            if not user:
                Exception("User not found")
            
            # policy validate
            policy = cur.execute("""
            select * from policies where policy_id = %s                    
            """, (user["policy_id"]))
            
            if not policy:
                Exception("Member not Subscribed to Any Policy")
            
            if not (policy["policy_start_date"]>datetime.datetime.now() or policy["policy_end_date"] < datetime.datetime.now() or policy["Renewal_status"] != "Active"):
                Exception("policy is not active")


        except Exception as e:
            if db:
                db.rollback()
        