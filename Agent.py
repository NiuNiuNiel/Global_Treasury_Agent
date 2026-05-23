import os
from dotenv import load_dotenv
from openai import OpenAI

class Agent():
    def __init__(self):
        load_dotenv()
        self.client = OpenAI(api_key=os.getenv("MORPHEUS_API_KEY"), base_url=os.getenv("MORPHEUS_BASE_URL"))

    def __get_invoices(self, invoice_ID, db_connector):
        db_connector.retrieve_data("invoices", condition=f"WHERE `invoice_ID` in {invoice_ID}")

    def validate_transaction(self, invoice_ID, db_connector):
        invoice = self.__get_invoices(invoice_ID, db_connector)



