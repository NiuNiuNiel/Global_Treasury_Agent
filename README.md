# Global Treasury Agent

An AI-powered invoice validation dashboard that automatically matches uploaded invoices against bank transaction records. The agent extracts invoice data (via OCR for images, or direct text extraction for PDFs and Word documents), filters candidate transactions from a PostgreSQL database, and uses a multi-model LLM pipeline to reconcile payments — accounting for exchange rate variances, platform fees, and split-payment scenarios.

---

## Table of Contents

- [System Requirements](#system-requirements)
- [Dependencies](#dependencies)
- [Installation](#installation)
- [Database Setup](#database-setup)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Features Overview](#features-overview)
- [Project Structure](#project-structure)

---

## System Requirements

| Requirement | Minimum Version | Notes |
|---|---|---|
| Python | 3.10+ | 3.11 or 3.12 recommended |
| PostgreSQL | 13+ | Must be running and accessible |
| Tesseract OCR | 5.0+ | Required for image invoice processing |
| Poppler | 23.0+ | Required by `pdf2image` for PDF rendering |
| OS | Windows 10 / macOS 12 / Ubuntu 20.04 | Desktop GUI requires a display server |

---

## Dependencies

All Python packages are listed in `requirements.txt`. Key packages include:

- **`customtkinter`** — Modern dark-themed desktop GUI framework
- **`psycopg2-binary`** — PostgreSQL database adapter
- **`openai`** — OpenAI-compatible SDK (used to call the Morpheus LLM gateway)
- **`PyMuPDF` (`fitz`)** — Digital PDF text extraction
- **`pdf2image`** — Converts scanned PDFs to images for OCR
- **`pytesseract`** — Python wrapper for Tesseract OCR
- **`python-docx`** — Word document text extraction
- **`python-dotenv`** — Loads environment variables from `.env`
- **`pillow`** — Image handling for OCR and PDF previews

---

## Installation

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd <repo-directory>
```

### 2. Create and Activate a Virtual Environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Tesseract OCR

Tesseract must be installed at the OS level — it is not a Python package.

**Windows:**
Download and run the installer from the [UB-Mannheim Tesseract releases page](https://github.com/UB-Mannheim/tesseract/wiki). During installation, note the install path (e.g. `C:\Program Files\Tesseract-OCR`). Add this path to your system `PATH` environment variable.

**macOS (Homebrew):**
```bash
brew install tesseract
```

**Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install tesseract-ocr
```

### 5. Install Poppler

Poppler provides the PDF rendering utilities required by `pdf2image`.

**Windows:**
Download the latest Poppler for Windows from [github.com/oschwartz10612/poppler-windows/releases](https://github.com/oschwartz10612/poppler-windows/releases). Extract it and add the `bin/` folder to your system `PATH`.

**macOS (Homebrew):**
```bash
brew install poppler
```

**Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install poppler-utils
```

---

## Database Setup

### 1. Create the Database

Connect to PostgreSQL and create the application database:

```sql
CREATE DATABASE "Global_Treasury_Agent_DB";
```

### 2. Run the Schema

Connect to the newly created database and execute the following DDL statements to create all required tables:

```sql
CREATE TABLE invoices (
    invoice_id        SERIAL          PRIMARY KEY,
    file_name         VARCHAR(255)    NOT NULL,
    file_path         TEXT            NOT NULL,
    file_type         VARCHAR(20)     NOT NULL,
    requires_ocr      BOOLEAN         NOT NULL DEFAULT FALSE,
    ocr_status        BOOLEAN,
    validation_status BOOLEAN         NOT NULL DEFAULT FALSE,
    uploaded_at       TIMESTAMP       NOT NULL DEFAULT NOW()
);

CREATE TABLE ocr_results (
    ocr_id      SERIAL      PRIMARY KEY,
    invoice_id  INTEGER     NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    ocr_result  JSONB       NOT NULL
);

CREATE TABLE transactions (
    transaction_id        VARCHAR(50)     PRIMARY KEY,
    bank_name             VARCHAR(100)    NOT NULL,
    transaction_datetime  TIMESTAMP       NOT NULL,
    amount                DECIMAL(18, 4)  NOT NULL,
    currency              VARCHAR(10)     NOT NULL,
    description           TEXT
);

CREATE TABLE registered_banks (
    bank_id   SERIAL        PRIMARY KEY,
    bank_name VARCHAR(100)  NOT NULL UNIQUE,
    mock_api  TEXT
);

CREATE TABLE validation_details (
    detail_id        SERIAL          PRIMARY KEY,
    invoice_id       INTEGER         NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    confidence_score DECIMAL(5, 4)   NOT NULL,
    validated_at     TIMESTAMP       NOT NULL DEFAULT NOW()
);

CREATE TABLE validation_transactions (
    id             SERIAL       PRIMARY KEY,
    invoice_id     INTEGER      NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    transaction_id VARCHAR(50)  NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    UNIQUE (invoice_id, transaction_id)
);

CREATE TABLE activity_log (
    log_id      SERIAL       PRIMARY KEY,
    logged_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    invoice_ref VARCHAR(20),
    action      VARCHAR(120) NOT NULL,
    details     TEXT,
    level       VARCHAR(20)  DEFAULT 'info'
);
```

> **Note:** The `activity_log` table is also auto-created at startup by the application if it does not already exist.

---

## Configuration

### 1. Create the `.env` File

Copy the example below and save it as `.env` in the root of the project directory. **Do not commit this file to version control** — it is already listed in `.gitignore`.

```env
# Morpheus LLM Gateway
MORPHEUS_API_KEY=your_morpheus_api_key_here
MORPHEUS_BASE_URL=https://api.mor.org/api/v1

# PostgreSQL connection
DB_HOST=localhost
DB_PORT=5432
DB_NAME=Global_Treasury_Agent_DB
DB_USER=postgres
DB_PASSWORD=your_database_password_here
```

### 2. Environment Variable Reference

| Variable | Description |
|---|---|
| `MORPHEUS_API_KEY` | API key for the Morpheus LLM gateway |
| `MORPHEUS_BASE_URL` | Base URL for the Morpheus OpenAI-compatible API endpoint |
| `DB_HOST` | PostgreSQL server hostname (use `localhost` for a local instance) |
| `DB_PORT` | PostgreSQL port (default: `5432`) |
| `DB_NAME` | Name of the database created in the setup step |
| `DB_USER` | PostgreSQL username |
| `DB_PASSWORD` | PostgreSQL password for the specified user |

### 3. LLM Model Configuration (Optional)

The `Agent` class in `Agent.py` uses four models by default. These can be overridden when instantiating the agent if you need to swap models:

| Parameter | Default Model | Role |
|---|---|---|
| `searching_model` | `deepseek-v3.2:web` | Web-search agent for historical exchange rates and bank fee policies |
| `OCR_model` | `kimi-k2.6` | Vision model for image-based invoice OCR |
| `fast_model` | `glm-4.7-flash` | Fast model for transaction filtering and date window extraction |
| `thinking_model` | `deepseek-v4-pro` | Reasoning model for matching invoices to transactions |

---

## Running the Application

With the virtual environment activated and the `.env` file in place, launch the dashboard from the project root:

```bash
python main.py
```

The GUI window will open. The status bar at the bottom will show a green **● Database connected** indicator if the PostgreSQL connection is successful. An amber indicator means the database module is unavailable and the app will run in mock-data mode.

---

## Features Overview

**Invoice Upload**
Click **+ Upload Invoice** to select one or more files. Supported formats: `.pdf`, `.docx`, `.jpg`, `.jpeg`, `.png`. Image files are automatically flagged as requiring OCR.

**AI Validation**
Click **Run AI** on any pending invoice, or select multiple invoices with the checkboxes and click **Run AI on Selected**. The agent will:
1. Extract text from the invoice (OCR for images; PyMuPDF or python-docx for digital files).
2. Identify the relevant bank(s) and a transaction date window.
3. Query the database for unmatched transactions within that window.
4. Use a reasoning model to find matching transaction candidates (including split payments).
5. Fetch historical exchange rates and bank fees to calculate a confidence score.
6. Auto-validate if confidence ≥ 95%; otherwise flag for manual review.

**Manual Review**
Invoices that fall below the confidence threshold are flagged as **⚠ Needs Review**. Clicking **Approve** opens a cross-check dialog displaying the invoice summary, extracted OCR data, the raw database row, and all matched transactions side-by-side.

**Bank Manager**
Click **🏦 Banks** to register or remove banks. Only registered banks are searched during AI validation. An API endpoint field is provided for integration with real bank transaction APIs.

**Activity Log**
Click **📋 Log** to view a live audit trail of all validation events, persisted to the `activity_log` table in PostgreSQL.

---

## Project Structure

```
.
├── main.py               # Desktop GUI application (CustomTkinter)
├── Agent.py              # AI validation pipeline (OCR, LLM calls, confidence scoring)
├── Data_Retrieval.py     # PostgreSQL database connector (CRUD helpers)
├── requirements.txt      # Python package dependencies
├── .env                  # Environment variables (not committed)
└── .gitignore
```
