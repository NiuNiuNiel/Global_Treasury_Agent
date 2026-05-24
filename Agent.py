import os
from dotenv import load_dotenv
from openai import OpenAI
import base64
import json
import fitz
from pdf2image import convert_from_path
import pytesseract
import docx



class Agent():
    def __init__(self, db_connector, searching_model = "deepseek-v3.2:web", OCR_model = "kimi-k2.6", fast_model = "glm-4.7-flash", thinking_model = "deepseek-v4-pro"):
        load_dotenv()
        self.client = OpenAI(api_key=os.getenv("MORPHEUS_API_KEY"), base_url=os.getenv("MORPHEUS_BASE_URL"))
        self.searching_model = searching_model
        self.OCR_model = OCR_model
        self.fast_model = fast_model
        self.thinking_model = thinking_model
        self.db_connector = db_connector

    def __clean_json(self, raw_string):
        # Strips markdown wrappers just in case the LLM disobeys the prompt
        cleaned = raw_string.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)

    def __pdf_extraction(self, pdf_path, sample_pages=3):
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"The file {pdf_path} was not found.")

        extracted_text = []
        is_scanned = False

        # Step 1: Check if the PDF is scanned or digital
        try:
            with fitz.open(pdf_path) as doc:
                text_length = 0
                pages_to_check = min(sample_pages, len(doc))

                for i in range(pages_to_check):
                    page = doc[i]
                    text = page.get_text().strip()
                    text_length += len(text)

                # If text is extremely sparse, we assume it's scanned/image-based
                if text_length < 10:
                    is_scanned = True
        except Exception as e:
            print(f"Error reading PDF metadata: {e}. Defaulting to OCR.")
            is_scanned = True

        # Step 2: Route to the correct extraction logic
        if is_scanned:
            print(f"--> '{pdf_path}' detected as SCANNED. Extracting with Tesseract OCR...")
            try:
                images = convert_from_path(pdf_path)
                for page_num, image in enumerate(images):
                    text = pytesseract.image_to_string(image)
                    extracted_text.append(f"--- Page {page_num + 1} ---\n{text}")
            except Exception as e:
                raise RuntimeError(f"OCR Extraction failed: {e}")

        else:
            print(f"--> '{pdf_path}' detected as DIGITAL. Extracting with PyMuPDF...")
            try:
                with fitz.open(pdf_path) as doc:
                    for page_num, page in enumerate(doc):
                        text = page.get_text()
                        extracted_text.append(f"--- Page {page_num + 1} ---\n{text}")
            except Exception as e:
                raise RuntimeError(f"Digital Extraction failed: {e}")

        # Step 3: Return the combined text string
        return "\n".join(extracted_text)

    def __word_doc_extraction(self, docx_path):
        # Load the Word document
        doc = docx.Document(docx_path)
        extracted_text = []

        # Iterate through each paragraph in the document
        for paragraph in doc.paragraphs:
            # Ignore completely empty lines
            if paragraph.text.strip():
                extracted_text.append(paragraph.text)

        # Join the paragraphs back together with line breaks
        return "\n".join(extracted_text)

    def __prompt(self, model, messages):
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
        )
        return response.choices[0].message.content

    def __get_invoices(self, invoice_ID):
        invoice_metadata = self.db_connector.retrieve_data("invoices", columns=["file_path", "file_type", "requires_OCR", "OCR_status"],condition="invoice_ID = %s", condition_values=(invoice_ID,))[0]
        if invoice_metadata["requires_OCR"]:
            if invoice_metadata["OCR_status"]:
               return {"OCR": True, "OCR_result": self.db_connector.retrieve_data("OCR_results",["OCR_result"],"invoice_ID = %s",(invoice_ID,))[0]["OCR_result"]}

            try:
                with open(invoice_metadata["file_path"], "rb") as image:
                    encoded_image = base64.b64encode(image.read())
            except FileNotFoundError:
                raise RuntimeError(f"File {invoice_metadata['file_path']} not found.")

            ocr_system_prompt = (
                """You are an expert financial OCR model. Analyze the provided invoice image and extract key details.
                You must return your response strictly as a raw JSON object with no markdown formatting or wrappers.
                The schema must match exactly:
                {
                    confidence: float,
                    invoice_amount: float,
                    currency: string,
                    vendor: string,
                    date: date,
                    bank: string,
                    text_content: string
                }
                
                Field description:
                - confidence: A floating-point number between 0.00 and 1.00 indicating your extraction confidence accuracy. If you are highly uncertain of the text legibility, score it below 0.90.
                - invoice_amount: The total final payable amount indicated on the invoice. Must be a clean floating-point number (e.g., 1250.50). Do not include currency symbols or thousands separators.
                - currency: The standard 3-letter ISO currency code representing the invoice currency (e.g., 'USD', 'MYR', 'EUR', 'SGD').
                - vendor: The name of the merchant, company, or individual issuing the invoice (e.g., 'Example Corp').
                - date: The date the invoice was issued, strictly formatted as an ISO 8601 string ('YYYY-MM-DD').
                - bank: The name of the receiving bank listed in the payment instructions section of the invoice if available (e.g., 'Maybank', 'CIMB'). If no specific bank is found, return null.
                - text_content: A single flat text string containing the entire raw text layer extracted from the document for fallback matching purposes. Escaped line breaks are permitted."""
            )

            messages = [
                {"role": "system", "content": ocr_system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded_image.decode('utf-8')}"}
                        }
                    ]
                }
            ]

            OCR_result = self.__clean_json(self.__prompt(self.OCR_model, messages))

            if OCR_result["confidence"] < 0.90:
                self.db_connector.update_data("invoices", ["OCR_status"], [False], "invoice_ID = %s",(invoice_ID,))
                return None

            self.db_connector.update_data("invoices", ["OCR_status"], [True], "invoice_ID = %s",(invoice_ID,))
            self.db_connector.insert_data("OCR_results", ["invoice_ID", "OCR_result"], [invoice_ID, json.dumps(OCR_result)])

            return {"OCR":True, "OCR_result":OCR_result}

        return {"OCR":False, "file_path":invoice_metadata["file_path"], "file_type":invoice_metadata["file_type"]}

    def __filter_transactions(self, invoice):
        registered_banks = [bank["bank_name"] for bank in
                            self.db_connector.retrieve_data("registered_banks", ["bank_name"])]

        filter_system_prompt = (
            """You are an AI treasury routing agent. Given invoice text data and a list of system-registered banks, 
            your task is to isolate which bank or banks the transaction likely went through, and determine a realistic
            search date window based on the invoice's date context.\n\n""" +

            f"Registered Banks in System: {registered_banks}\n\n" +

            """Instructions:
            1. Identify all suitable 'Bank' options from the allowed list. Return them as a list of strings. If it does not match any registered bank, return false for that key, or null if there is no bank being mentioned.
            2. Generate a 'Date_Window' suffix or clause suitable for a database filter (e.g., a specific start and end date).

            Return strictly a raw JSON object conforming exactly to this layout:
            {
                "Bank": ["Maybank", "CIMB"],
                "Date_Window": "2026-05-23 AND 2026-05-26"
            }

            Field descriptions:
            - Bank: 
                - A list of explicit bank names identified from the invoice payment instructions. Each item MUST be an exact string match to one of the options provided in the 'Registered Banks in System' list.
                - If no bank is mentioned, return null.
                - If the mentioned bank(s) are not on the registered list, return the boolean value false.
            - Date_Window: A string representing a SQL-friendly date range for the database query, formatted strictly as 'YYYY-MM-DD AND YYYY-MM-DD'. The start date should be the invoice issue date. The end date should be the stated due date. If the invoice does not mention a due date or payment terms, calculate the end date by defaulting to exactly 30 days after the invoice issue date.
            """
        )

        messages = [{"role": "system", "content": filter_system_prompt},
                    {"role": "user", "content": invoice}]

        return self.__clean_json(self.__prompt(self.fast_model, messages))

    def __find_matching_candidates(self, invoice, filtered_transactions):
        system_prompt = (
            """You are an expert AI financial reconciliation agent. Your task is to analyze an invoice and a list of potential bank transactions, and identify which transaction(s) likely represent the payment for the invoice.
            
            INSTRUCTIONS & REASONING LOGIC:
            1. Analyze the invoice amount, date, and vendor details.
            2. Compare these against the provided list of bank transactions (amount, datetime, and description).
            3. Account for Payment Delays: Bank transactions usually occur on or a few days after the invoice date.
            4. Account for Variances: The bank transaction amount might NOT match the invoice amount exactly. This can happen due to cross-border currency exchange rates or deducted platform/gateway fees.
            5. Account for Split Payments: A single invoice may be paid across multiple separate bank transactions. If no single transaction is a clear match, evaluate if a combination of transactions made to the same vendor accurately sums up to the expected payment.
            6. If no transactions or combinations are plausible matches, return an empty list for the candidates.
            
            CRITICAL REQUIREMENT:
            You must return your response strictly as a raw JSON object with no markdown formatting, preambles, or explanations.
            The output JSON schema must match this layout exactly:
            {
                "Invoice_Amount": 1234.50,
                "Invoice_Currency": "USD",
                "Matching_Candidates": [["TXN-987654321"], ["TXN-123456789", "TXN-112233445"]]
            }
            
            FIELD DESCRIPTIONS:
            - Invoice_Amount: The total final payable amount indicated on the invoice. Must be a clean floating-point number (e.g., 1250.50). Do not include currency symbols or thousands separators.
            - Invoice_Currency: The standard 3-letter ISO currency code representing the currency the original invoice was billed in (e.g., 'USD', 'MYR').
            - Matching_Candidates: A list of lists containing string 'transaction_ID's. Each inner list represents ONE plausible payment scenario (which may consist of a single transaction, or multiple transactions combined to cover the invoice). If no transactions match, return an empty list []."""
        )

        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Invoice: {invoice}\n\nTransactions: {json.dumps(filtered_transactions)}"}]

        return self.__clean_json(self.__prompt(self.thinking_model, messages))

    def __search_transaction_losses(self, invoice_currency, search_request):
        search_system_prompt = (
            """You are an expert AI financial researcher and treasury analyst. 
            Your task is to determine the historical exchange rates and standard fee deduction policies for a list of bank transactions.

            You will be provided with the original 'invoice' currency and a 'Search request' containing a list of transaction details.

            INSTRUCTIONS & REASONING LOGIC:
            1. Exchange Rate: For each transaction, determine the exchange rate to convert from the original invoice currency to the 'Transaction_Currency' on the specific 'DateTime_of_Transaction'. 
               - If the invoice currency and the transaction currency are identical, the exchange rate is exactly 1.0.
               - If they differ, FIRST attempt to find the specific 'Bank's historical exchange rate (e.g., the Bank's Telegraphic Transfer (TT) Selling rate) for that exact date. 
               - If the specific bank's exchange rate data for that date is unavailable, FALLBACK to the general/mid-market historical exchange rate for that date.
            2. Fee Policy: Identify the standard corporate receiving/transfer fee policy for the specified 'Bank'. Break this policy down into a fixed fee and a percentage rate.

            CRITICAL REQUIREMENT:
            You must return your response strictly as a raw JSON array of objects, with NO markdown formatting, wrappers, or explanations.
            The output MUST conform exactly to this schema:
            [
              {
                "Transaction_ID": "string",
                "Exchange_Rate": float,
                "Fixed_Fee_Amount": float,
                "Percentage_Fee_Rate": float
              }
            ]

            FIELD DESCRIPTIONS:
            - Transaction_ID: The exact transaction ID provided in the search request input.
            - Exchange_Rate: A clean floating-point number representing the exchange rate on the given date. Prioritize the bank-specific rate.
            - Fixed_Fee_Amount: A float representing any flat fee charged by the bank, converted into the 'Transaction_Currency'. If there is no flat fee, return 0.0.
            - Percentage_Fee_Rate: A float representing any percentage-based fee charged by the bank (e.g., if the fee is 0.1%, return 0.001). If there is no percentage fee, return 0.0."""
        )

        messages = [{"role": "system", "content": search_system_prompt},
                    {"role": "user", "content": f"invoice: {invoice_currency}\n\nSearch request: {json.dumps(search_request)}"}]

        return self.__clean_json(self.__prompt(self.searching_model, messages))

    def validate_transaction(self, invoice_ID):
        invoice = self.__get_invoices(invoice_ID)

        print("Debugging",invoice)

        if invoice is None:
            print("Detection result inaccurate, please provide a clearer image.")
            return

        if invoice["OCR"]:
            invoice = json.dumps(invoice["OCR_result"])
        else:
            if invoice["file_type"] == "pdf":
                invoice = self.__pdf_extraction(invoice["file_path"])
            elif invoice["file_type"] == "docx":
                invoice = self.__word_doc_extraction(invoice["file_path"])
            else:
                raise TypeError(f"Unsupported file type: {invoice['file_type']}")

        filter_condition = self.__filter_transactions(invoice)
        print("Debugging",filter_condition)

        bank_filter = filter_condition.get("Bank")
        if bank_filter is False:
            print("Bank given by the filter model has not been registered.")
            return
        elif not bank_filter:  # This safely catches None AND []
            bank_filter = [dic.get("bank_name") for dic in
                           self.db_connector.retrieve_data("registered_banks", ["bank_name"])]

        target_banks = tuple(bank_filter)

        try:
            start_date, end_date = [date.strip() for date in filter_condition["Date_Window"].split("AND")]
        except ValueError:
            print("Error parsing Date_Window from model. Fallback needed.")
            return

        end_timestamp = f"{end_date} 23:59:59"

        condition = "bank_name IN %s AND transaction_datetime BETWEEN %s AND %s AND transaction_ID NOT IN (SELECT transaction_ID FROM validation_transactions WHERE transaction_ID IS NOT NULL)"
        condition_values = (target_banks, start_date, end_timestamp)

        filtered_transactions = self.db_connector.retrieve_data(
            table_name="transactions",
            condition=condition,
            condition_values=condition_values
        )

        if not filtered_transactions:
            print("No transactions found in the database for this search window.")
            return

        matching_result = self.__find_matching_candidates(invoice, filtered_transactions)

        print("Debugging",matching_result)

        if not matching_result or not matching_result.get("Matching_Candidates"):
            print("AI could not find any matching candidates among the retrieved transactions.")
            return

        invoice_currency = matching_result.get("Invoice_Currency")
        matching_candidates = matching_result.get("Matching_Candidates")

        valid_transaction_ids = {ID for candidate in matching_candidates for ID in candidate}

        # 1. Filter the list down to only the valid transactions (kept for later use)
        filtered_transactions = [
            txn for txn in filtered_transactions
            if txn["transaction_ID"] in valid_transaction_ids
        ]

        # 2. Iterate directly over the newly filtered list to build the payload
        search_request = []
        for txn in filtered_transactions:
            payload = {
                "Transaction_ID": txn["transaction_ID"],
                "Bank": txn["bank_name"],
                "Transaction_Currency": txn["currency"],
                "DateTime_of_Transaction": txn["transaction_datetime"].strftime("%Y-%m-%d %H:%M:%S")
            }
            search_request.append(payload)

        transaction_losses = self.__search_transaction_losses(invoice_currency, search_request)
        print("Debugging", transaction_losses)

        invoice_amount = matching_result.get("Invoice_Amount")

        if not invoice_amount:
            print("Error: Could not determine the original invoice amount for calculation.")
            return

        # 2. Convert lists to dictionaries for O(1) instant data lookups
        loss_lookup = {loss["Transaction_ID"]: loss for loss in transaction_losses}
        txn_lookup = {txn["transaction_ID"]: txn for txn in filtered_transactions}

        best_scenario = None
        highest_confidence = 0.0

        # 3. Calculate Confidence Score
        for scenario in matching_candidates:
            scenario_actual_amount = 0.0
            scenario_expected_amount = 0.0

            for txn_id in scenario:
                txn = txn_lookup.get(txn_id)
                loss = loss_lookup.get(txn_id)

                if not txn or not loss:
                    continue

                # Add up the actual transaction amounts from the database
                scenario_actual_amount += float(txn["amount"])

                # Extract loss parameters
                exchange_rate = loss["Exchange_Rate"]
                fixed_fee = loss["Fixed_Fee_Amount"]
                percentage_rate = loss["Percentage_Fee_Rate"]

                # Calculate exactly as your workflow diagram dictates
                converted_gross = invoice_amount * exchange_rate
                platform_fees = fixed_fee + (converted_gross * percentage_rate)
                expected_amount = converted_gross - platform_fees

                scenario_expected_amount += expected_amount

            # Guard against division by zero
            if scenario_actual_amount > 0:
                confidence = (scenario_expected_amount / scenario_actual_amount) * 100

                # Penalize variances in both directions (e.g., if confidence is 105%, it's functionally a 95% match)
                if confidence > 100.0:
                    confidence = 100.0 - (confidence - 100.0)

                if confidence > highest_confidence:
                    highest_confidence = confidence
                    best_scenario = scenario

        print(f"--> Generated Highest Confidence: {highest_confidence:.2f}% for scenario: {best_scenario}")

        # 4. Satisfy Validation Confident Threshold
        CONFIDENCE_THRESHOLD = 95.0  # You can adjust this threshold

        if highest_confidence >= CONFIDENCE_THRESHOLD:
            print("--> [SUCCESS] Threshold met. Validating payment in database...")

            # Update the main invoice table
            self.db_connector.update_data("invoices", ["validation_status"], [True], "invoice_ID = %s", (invoice_ID,))

            # Insert into the 1-to-1 validation metadata table
            self.db_connector.insert_data("validation_details", ["invoice_ID", "confidence_score"],
                                          [invoice_ID, highest_confidence])

            # Insert into the mapping table (handles split payments natively!)
            for txn_id in best_scenario:
                self.db_connector.insert_data("validation_transactions", ["invoice_ID", "transaction_ID"],
                                              [invoice_ID, txn_id])
            return True

        print("--> [ALERT] Confidence below threshold. Flagged for Manual Validation.")
        return False

