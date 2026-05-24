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
    def __init__(self, db_connector, searching_model = "deepseek-v3.2", OCR_model = "kimi-k2.6", fast_model = "glm-4.7-flash", thinking_model = "deepseek-v4-pro"):
        load_dotenv()
        self.client = OpenAI(api_key=os.getenv("MORPHEUS_API_KEY"), base_url=os.getenv("MORPHEUS_BASE_URL"))
        self.searching_model = searching_model
        self.OCR_model = OCR_model
        self.fast_model = fast_model
        self.thinking_model = thinking_model
        self.db_connector = db_connector

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
        invoice_metadata = self.db_connector.retrieve_data("invoices", condition="`invoice_ID` = %s", condition_values=(invoice_ID,))[0]
        if invoice_metadata["requires_OCR"]:
            if invoice_metadata["OCR_status"]:
               return json.loads(self.db_connector.retrieve_data("OCR_results",["OCR_result"],"`invoice_ID` = %s",(invoice_ID,)))

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
                    invoice_amount: float,"
                    currency: string,"
                    vendor: string,"
                    date: date,"
                    bank: string,
                    text_content: string"
                }
                
                Field description:
                - confidence: A floating-point number between 0.00 and 1.00 indicating your extraction confidence accuracy. If you are highly uncertain of the text legibility, score it below 0.90.
                - invoice_amount: The total final payable amount indicated on the invoice. Must be a clean floating-point number (e.g., 1250.50). Do not include currency symbols or thousands separators.
                - currency: The standard 3-letter ISO currency code representing the invoice currency (e.g., 'USD', 'MYR', 'EUR', 'SGD').
                - vendor: The name of the merchant, company, or individual issuing the invoice (e.g., 'Example Corp').
                - date: The date the invoice was issued, strictly formatted as an ISO 8601 string ('YYYY-MM-DD').
                - bank: The name of the receiving bank listed in the payment instructions section of the invoice if available (e.g., 'Maybank', 'CIMB'). If no specific bank is found, return null.
                - text_content: A single flat text string containing the entire raw text layer extracted from the document for fallback matching purposes. Escaped line breaks are permitted.
                """
            )

            messages = [
                {"role": "system", "content": ocr_system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}
                        }
                    ]
                }
            ]

            OCR_result = json.loads(self.__prompt(self.OCR_model, messages))

            if OCR_result["confidence"] < 0.90:
                self.db_connector.update_data("invoices", ["OCR_status"], [False], "`invoice_ID` = %s",(invoice_ID,))
                print("Detection result inaccurate, please upload a clearer picture.")
                return

            self.db_connector.update_data("invoices", ["OCR_status"], [True], "`invoice_ID` = %s",(invoice_ID,))
            self.db_connector.insert_data("OCR_results", ["invoice_ID", "OCR_result"], [invoice_ID, OCR_result])

            return {"OCR":True, "OCR_result":OCR_result}

        return {"OCR":False, "file_path":invoice_metadata["file_path"], "file_type":invoice_metadata["file_type"]}

    def __filter_transactions(self, invoice):
        registered_banks = [bank["bank_name"] for bank in
                            json.loads(self.db_connector.retrieve_data("registered_banks", ["bank_name"]))]
        messages = [{"role":"system","content":""""""}]
        if invoice["OCR"]:
            messages.append({"role": "user", "content": invoice["OCR_result"]})
        else:
            if invoice["file_type"] == "pdf":
                content = self.__pdf_extraction(invoice["file_path"])
            elif invoice["file_type"] == "docx":
                content = self.__word_doc_extraction(invoice["file_path"])
            else:
                raise TypeError(f"Unsupported file type: {invoice['file_type']}")

            messages.append({"role": "user", "content": content})

        return json.loads(self.__prompt(self.fast_model, messages))

    def validate_transaction(self, invoice_ID):
        invoice = self.__get_invoices(invoice_ID)
        filter = self.__filter_transactions(invoice)

        if filter["bank"] is None:
            filter["bank"] = self.db_connector.retrieve_data("registered_banks", ["bank_name"])
        elif filter["bank"] is False:
            print("Bank given by the filter model has not been registered.")
            return





