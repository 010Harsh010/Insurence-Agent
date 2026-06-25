from pathlib import Path
import json
from sub_agent.policyAgent import ClaimProcessingPipeline
from document_agent.document_identifier import DocumentAgent
import os

documentAgent = DocumentAgent()

class ClaimTest:
    def __init__(self, testcase, testcase_dir):

        self.testcase = testcase
        self.case_id = testcase["case_id"]
        self.testcase_dir = Path(testcase_dir)

        # upload_folder = os.path.join(
        #     "documents",
        #     testcase["case_id"]
        # )

        # for filename in os.listdir(upload_folder):

        #     filepath = os.path.join(
        #         upload_folder,
        #         filename
        #     )

        #     if not os.path.isfile(filepath):
        #         continue

        #     ext = os.path.splitext(filename)[1].lower()

        #     if ext not in [".pdf", ".jpg", ".jpeg", ".png"]:
        #         continue

        #     response = documentAgent.process_document(
        #         filepath
        #     )

        #     json_path = os.path.join(
        #         upload_folder,
        #         f"{os.path.splitext(filename)[0]}.json"
        #     )

        #     md_path = os.path.join(
        #         upload_folder,
        #         f"{os.path.splitext(filename)[0]}.md"
        #     )

        #     with open(json_path, "w") as f:
        #         json.dump(
        #             response,
        #             f,
        #             indent=4
        #         )

        #     with open(md_path, "w", encoding="utf-8") as f:
        #         f.write(response["markdown"])

        self.pipeline = ClaimProcessingPipeline(
            member_id=testcase["input"]["member_id"],
            claim_category=testcase["input"]["claim_category"],
            output_dir=str(self.testcase_dir / "output"),
            testing_id=self.case_id
        )

    def run(self):

        try:
            response = self.pipeline.run()

            return {
                "case_id": self.case_id,
                "expected": self.testcase["expected"],
                "actual": response
            }

        except Exception as e:
            return {
                "case_id": self.case_id,
                "error": str(e)
            }
            
def process():
        with open("../test_cases.json") as f:
            testcases = json.load(f)["test_cases"]

        results = []

        for testcase in testcases:
            print(f"Running {testcase['case_id']}")
            test = ClaimTest(
                testcase=testcase,
                testcase_dir=f"./test/output/{testcase['case_id']}"
            )
            results.append(test.run())
        Path("./test").mkdir(
            parents=True,
            exist_ok=True
        )

        with open("./test/result.json", "w") as f:
            json.dump(
                results,
                f,
                indent=4
            )    
            
        return results