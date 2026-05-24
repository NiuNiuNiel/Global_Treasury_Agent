# Global Treasury Agent - Frontend Dashboard
# main.py

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import os
from datetime import datetime

# Try to import backend modules; fall back gracefully if unavailable
try:
    from Data_Retrieval import Database_Connector
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False

try:
    from Agent import Agent
    _AGENT_AVAILABLE = True
except ImportError:
    _AGENT_AVAILABLE = False

# ── Appearance ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CONFIDENCE_THRESHOLD = 0.95  # >= 95% => auto-validated

C = {
    "bg":         "#0e0e1a",
    "panel":      "#14142a",
    "card":       "#1a1a30",
    "row_even":   "#181828",
    "row_odd":    "#1d1d30",
    "row_sel":    "#252545",
    "border":     "#2a2a45",
    "accent":     "#4f8ef7",
    "accent_dim": "#3a6ec4",
    "text":       "#e0e0f0",
    "text_dim":   "#8888aa",
    "text_muted": "#50506a",
}

STATUS_META = {
    "pending":            {"label": "●  Pending",          "fg": "#f5a623"},
    "processing":         {"label": "⟳  Processing...",    "fg": "#4f8ef7"},
    "auto_validated":     {"label": "✓  Auto-Validated",   "fg": "#2ecc71"},
    "needs_manual":       {"label": "⚠  Needs Review",     "fg": "#e67e22"},
    "manually_validated": {"label": "✓  Approved",         "fg": "#2ecc71"},
    "error":              {"label": "✗  Error",            "fg": "#e74c3c"},
}

COLUMNS = [
    ("select",      "",              44,   "center"),
    ("invoice_id",  "Invoice ID",   140,   "w"),
    ("date",        "Date",         105,   "center"),
    ("amount",      "Amount",       110,   "e"),
    ("currency",    "CCY",           58,   "center"),
    ("description", "Description",  235,   "w"),
    ("confidence",  "Confidence",   100,   "center"),
    ("status",      "Status",       165,   "center"),
    ("actions",     "Actions",      145,   "center"),
]

# Supported upload extensions -> (file_type stored in DB, requires_OCR)
UPLOAD_EXT_MAP = {
    "pdf":  ("pdf",  False),
    "docx": ("docx", False),
    "jpg":  ("jpg",  True),
    "jpeg": ("jpg",  True),
    "png":  ("png",  True),
}

MOCK_INVOICES = [
    {
        "invoice_id": "INV-0001", "_db_id": None, "_confidence": None, "_matched_ids": [],
        "date_of_purchase": "2026-05-10", "amount": 15000.00, "currency": "USD",
        "description": "Software licensing Q2 - Acme Corp",
        "validation_status": "pending",
    },
    {
        "invoice_id": "INV-0002", "_db_id": None, "_confidence": None, "_matched_ids": [],
        "date_of_purchase": "2026-05-12", "amount": 4200.50, "currency": "EUR",
        "description": "Cloud infrastructure - Globex Solutions",
        "validation_status": "pending",
    },
    {
        "invoice_id": "INV-0003", "_db_id": None, "_confidence": 0.82, "_matched_ids": [],
        "date_of_purchase": "2026-05-14", "amount": 87500.00, "currency": "MYR",
        "description": "Consulting retainer - TechServe Sdn Bhd",
        "validation_status": "needs_manual",
    },
    {
        "invoice_id": "INV-0004", "_db_id": None, "_confidence": 0.97, "_matched_ids": [],
        "date_of_purchase": "2026-05-15", "amount": 320.00, "currency": "SGD",
        "description": "Office supplies - StatioNow",
        "validation_status": "auto_validated",
    },
    {
        "invoice_id": "INV-0005", "_db_id": None, "_confidence": None, "_matched_ids": [],
        "date_of_purchase": "2026-05-18", "amount": 9800.75, "currency": "GBP",
        "description": "Legal services - Chambers & Partners",
        "validation_status": "pending",
    },
]


# =============================================================================
#  HELPER WIDGETS
# =============================================================================

class Separator(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, height=1, fg_color=C["border"], **kwargs)


class StatusBadge(ctk.CTkLabel):
    def __init__(self, master, status_key, **kwargs):
        meta = STATUS_META.get(status_key, {"label": status_key, "fg": C["text_dim"]})
        super().__init__(master, text=meta["label"], text_color=meta["fg"],
                         font=ctk.CTkFont(size=12), **kwargs)

    def update_status(self, status_key):
        meta = STATUS_META.get(status_key, {"label": status_key, "fg": C["text_dim"]})
        self.configure(text=meta["label"], text_color=meta["fg"])


class StatCard(ctk.CTkFrame):
    def __init__(self, master, title, value, color=None, **kwargs):
        if color is None:
            color = C["text"]
        super().__init__(master, fg_color=C["card"], corner_radius=10,
                         border_width=1, border_color=C["border"], **kwargs)
        self.value_label = ctk.CTkLabel(self, text=value,
                                        font=ctk.CTkFont(size=26, weight="bold"),
                                        text_color=color)
        self.value_label.pack(padx=20, pady=(14, 0))
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=11),
                     text_color=C["text_dim"]).pack(padx=20, pady=(2, 14))

    def set_value(self, value):
        self.value_label.configure(text=value)


# =============================================================================
#  INVOICE ROW
# =============================================================================

class InvoiceRow(ctk.CTkFrame):
    def __init__(self, master, invoice, row_index,
                 on_run_ai, on_approve, on_select_change, **kwargs):
        bg = C["row_even"] if row_index % 2 == 0 else C["row_odd"]
        super().__init__(master, fg_color=bg, corner_radius=0, **kwargs)

        self.invoice    = invoice
        self.row_index  = row_index
        self.on_run_ai  = on_run_ai
        self.on_approve = on_approve
        self._bg        = bg
        self._selected  = tk.BooleanVar(value=False)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._build(on_select_change)

    def _build(self, on_select_change):
        for i, (key, _label, width, _anchor) in enumerate(COLUMNS):
            self.columnconfigure(i, minsize=width,
                                 weight=(1 if key == "description" else 0))
        inv = self.invoice
        col = 0

        # Checkbox
        ctk.CTkCheckBox(self, variable=self._selected, text="",
                        width=24, height=24, command=on_select_change,
                        fg_color=C["accent"], hover_color=C["accent_dim"],
                        border_color=C["border"]
                        ).grid(row=0, column=col, padx=(8, 4), pady=8)
        col += 1

        # Invoice ID
        ctk.CTkLabel(self, text=inv.get("invoice_id", "-"),
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["accent"], anchor="w"
                     ).grid(row=0, column=col, padx=(4, 8), pady=8, sticky="ew")
        col += 1

        # Date
        raw_date = inv.get("date_of_purchase", "")
        try:
            date_str = datetime.strptime(str(raw_date), "%Y-%m-%d").strftime("%d %b %Y")
        except (ValueError, TypeError):
            date_str = str(raw_date) if raw_date else "-"
        ctk.CTkLabel(self, text=date_str, font=ctk.CTkFont(size=12),
                     text_color=C["text_dim"], anchor="center"
                     ).grid(row=0, column=col, padx=4, pady=8, sticky="ew")
        col += 1

        # Amount
        try:
            amt = float(inv.get("amount", 0))
            amount_str = "{:,.2f}".format(amt) if amt != 0 else "-"
        except (ValueError, TypeError):
            amount_str = "-"
        ctk.CTkLabel(self, text=amount_str,
                     font=ctk.CTkFont(size=12, family="Courier"),
                     text_color=C["text"], anchor="e"
                     ).grid(row=0, column=col, padx=(4, 2), pady=8, sticky="ew")
        col += 1

        # Currency
        ctk.CTkLabel(self, text=inv.get("currency", ""),
                     font=ctk.CTkFont(size=11), text_color=C["text_muted"], anchor="center"
                     ).grid(row=0, column=col, padx=(2, 4), pady=8, sticky="ew")
        col += 1

        # Description
        self.desc_label = ctk.CTkLabel(self, text=inv.get("description", ""),
                                       font=ctk.CTkFont(size=12),
                                       text_color=C["text"], anchor="w")
        self.desc_label.grid(row=0, column=col, padx=(4, 8), pady=8, sticky="ew")
        col += 1

        # Confidence
        conf = inv.get("_confidence")
        if conf is not None:
            color = "#2ecc71" if conf >= CONFIDENCE_THRESHOLD else "#e67e22"
            conf_text = "{:.1f}%".format(conf * 100)
        else:
            color = C["text_muted"]
            conf_text = "-"
        self.confidence_label = ctk.CTkLabel(self, text=conf_text,
                                              font=ctk.CTkFont(size=12, weight="bold"),
                                              text_color=color, anchor="center")
        self.confidence_label.grid(row=0, column=col, padx=4, pady=8, sticky="ew")
        col += 1

        # Status badge
        self.status_badge = StatusBadge(self,
                                         status_key=inv.get("validation_status", "pending"),
                                         anchor="center")
        self.status_badge.grid(row=0, column=col, padx=4, pady=8, sticky="ew")
        col += 1

        # Action button area
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.grid(row=0, column=col, padx=8, pady=6)
        self._refresh_action_button()

    def _refresh_action_button(self):
        for w in self.action_frame.winfo_children():
            w.destroy()
        status = self.invoice.get("validation_status", "pending")

        if status == "pending":
            ctk.CTkButton(self.action_frame, text="Run AI",
                          width=110, height=30, font=ctk.CTkFont(size=12),
                          fg_color=C["accent"], hover_color=C["accent_dim"],
                          command=lambda: self.on_run_ai(self)).pack()

        elif status == "needs_manual":
            ctk.CTkButton(self.action_frame, text="Approve",
                          width=110, height=30, font=ctk.CTkFont(size=12),
                          fg_color="#1a4a1a", hover_color="#265526",
                          text_color="#2ecc71",
                          border_width=1, border_color="#2ecc71",
                          command=lambda: self.on_approve(self)).pack()

        elif status == "processing":
            ctk.CTkLabel(self.action_frame, text="Running...",
                         font=ctk.CTkFont(size=12), text_color=C["accent"]).pack()

    def set_processing(self):
        self.invoice["validation_status"] = "processing"
        self.status_badge.update_status("processing")
        self.confidence_label.configure(text="...", text_color=C["accent"])
        self._refresh_action_button()

    def set_result(self, status, confidence, matched_ids=None, message=""):
        self.invoice["validation_status"] = status
        self.status_badge.update_status(status)
        if confidence is not None:
            pct   = confidence * 100
            color = "#2ecc71" if confidence >= CONFIDENCE_THRESHOLD else "#e67e22"
            self.confidence_label.configure(text="{:.1f}%".format(pct), text_color=color)
        else:
            self.confidence_label.configure(text="-", text_color=C["text_muted"])
        self._refresh_action_button()

    def set_approved(self):
        self.invoice["validation_status"] = "manually_validated"
        self.status_badge.update_status("manually_validated")
        self._refresh_action_button()

    def _on_enter(self, _event=None):
        self.configure(fg_color=C["row_sel"])

    def _on_leave(self, _event=None):
        self.configure(fg_color=self._bg)

    @property
    def is_selected(self):
        return self._selected.get()

    def set_selected(self, value):
        self._selected.set(value)


# =============================================================================
#  MAIN APPLICATION
# =============================================================================

class GlobalTreasuryApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("Global Treasury Agent")
        self.geometry("1280x780")
        self.minsize(1100, 600)
        self.configure(fg_color=C["bg"])

        self._invoices       = []
        self._rows           = []
        self._db             = None
        self._agent          = None
        self._active_threads = {}
        self._filter_var     = None
        self._search_entry   = None

        self._build_ui()
        self._connect_backend()
        self._load_invoices()

    # =========================================================================
    #  UI CONSTRUCTION
    # =========================================================================

    def _build_ui(self):
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=0)
        self.rowconfigure(2, weight=0)
        self.rowconfigure(3, weight=0)
        self.rowconfigure(4, weight=1)
        self.rowconfigure(5, weight=0)
        self.columnconfigure(0, weight=1)

        self._build_header()
        self._build_toolbar()
        Separator(self).grid(row=2, column=0, sticky="ew")
        self._build_table_header()
        self._build_table_body()
        self._build_status_bar()

    def _build_header(self):
        hf = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=0, height=90)
        hf.grid(row=0, column=0, sticky="ew")
        hf.grid_propagate(False)
        hf.columnconfigure(1, weight=1)

        title_frame = ctk.CTkFrame(hf, fg_color="transparent")
        title_frame.grid(row=0, column=0, padx=24, pady=16, sticky="w")
        ctk.CTkLabel(title_frame, text="  Global Treasury Agent",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="  Invoice Validation Dashboard",
                     font=ctk.CTkFont(size=12),
                     text_color=C["text_dim"]).pack(anchor="w")

        cards_frame = ctk.CTkFrame(hf, fg_color="transparent")
        cards_frame.grid(row=0, column=2, padx=24, pady=12, sticky="e")

        self._card_total   = StatCard(cards_frame, "Total Invoices", "-", C["text"])
        self._card_pending = StatCard(cards_frame, "Pending",        "-", "#f5a623")
        self._card_review  = StatCard(cards_frame, "Needs Review",   "-", "#e67e22")
        self._card_done    = StatCard(cards_frame, "Validated",      "-", "#2ecc71")

        for i, card in enumerate([self._card_total, self._card_pending,
                                   self._card_review, self._card_done]):
            card.grid(row=0, column=i, padx=6)

        self._db_dot = ctk.CTkLabel(hf, text="●", font=ctk.CTkFont(size=14),
                                    text_color=C["text_muted"])
        self._db_dot.grid(row=0, column=2, padx=(0, 12), pady=8, sticky="ne")

    def _build_toolbar(self):
        tf = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=0, height=54)
        tf.grid(row=1, column=0, sticky="ew")
        tf.grid_propagate(False)
        tf.columnconfigure(1, weight=1)

        # Search
        search_frame = ctk.CTkFrame(tf, fg_color="transparent")
        search_frame.grid(row=0, column=0, padx=(16, 8), pady=10, sticky="w")
        self._search_entry = ctk.CTkEntry(search_frame,
                                          placeholder_text="Search invoices...",
                                          width=220, height=32,
                                          font=ctk.CTkFont(size=12),
                                          fg_color=C["card"],
                                          border_color=C["border"])
        self._search_entry.pack(side="left")
        self._search_entry.bind("<KeyRelease>", self._on_search)

        # Filter dropdown
        self._filter_var = ctk.StringVar(value="Show: All")
        ctk.CTkOptionMenu(tf, variable=self._filter_var,
                          values=["Show: All", "Show: Pending",
                                  "Show: Needs Review", "Show: Validated"],
                          width=160, height=32, font=ctk.CTkFont(size=12),
                          fg_color=C["card"], button_color=C["border"],
                          button_hover_color=C["accent"],
                          command=self._on_filter_change
                          ).grid(row=0, column=1, padx=8, pady=10, sticky="w")

        # Right-side buttons
        btn_frame = ctk.CTkFrame(tf, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=(8, 16), pady=10, sticky="e")

        self._select_all_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(btn_frame, text="Select All",
                        variable=self._select_all_var,
                        font=ctk.CTkFont(size=12), text_color=C["text_dim"],
                        fg_color=C["accent"], hover_color=C["accent_dim"],
                        border_color=C["border"],
                        command=self._on_select_all).pack(side="left", padx=(0, 12))

        ctk.CTkButton(btn_frame, text="Run AI on Selected",
                      width=160, height=32, font=ctk.CTkFont(size=12),
                      fg_color=C["accent"], hover_color=C["accent_dim"],
                      command=self._run_selected).pack(side="left", padx=(0, 8))

        # Upload button (green-tinted to signal "add" action)
        ctk.CTkButton(btn_frame, text="+ Upload Invoice",
                      width=140, height=32, font=ctk.CTkFont(size=12),
                      fg_color="#1a4a2e", hover_color="#235e3a",
                      text_color="#2ecc71",
                      border_width=1, border_color="#2ecc71",
                      command=self._upload_invoices).pack(side="left", padx=(0, 8))

        ctk.CTkButton(btn_frame, text="Refresh",
                      width=100, height=32, font=ctk.CTkFont(size=12),
                      fg_color=C["card"], hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      command=self._refresh).pack(side="left")

    def _build_table_header(self):
        hf = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=0, height=36)
        hf.grid(row=3, column=0, sticky="ew")
        hf.grid_propagate(False)
        for i, (key, label, width, anchor) in enumerate(COLUMNS):
            hf.columnconfigure(i, minsize=width,
                               weight=(1 if key == "description" else 0))
            ctk.CTkLabel(hf, text=label, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["text_dim"], anchor=anchor
                         ).grid(row=0, column=i,
                                padx=(8 if i == 0 else 4), pady=4, sticky="ew")

    def _build_table_body(self):
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=C["bg"], corner_radius=0,
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["accent"])
        self._scroll.grid(row=4, column=0, sticky="nsew")
        self._scroll.columnconfigure(0, weight=1)

    def _build_status_bar(self):
        sb = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=0, height=28)
        sb.grid(row=5, column=0, sticky="ew")
        sb.grid_propagate(False)
        sb.columnconfigure(1, weight=1)
        self._db_status_label = ctk.CTkLabel(sb, text="",
                                              font=ctk.CTkFont(size=11),
                                              text_color=C["text_dim"])
        self._db_status_label.grid(row=0, column=0, padx=14, pady=4, sticky="w")
        self._last_refresh_label = ctk.CTkLabel(sb, text="",
                                                 font=ctk.CTkFont(size=11),
                                                 text_color=C["text_muted"])
        self._last_refresh_label.grid(row=0, column=2, padx=14, pady=4, sticky="e")

    # =========================================================================
    #  BACKEND CONNECTION
    # =========================================================================

    def _connect_backend(self):
        if _DB_AVAILABLE:
            try:
                self._db = Database_Connector()
                self._db_dot.configure(text_color="#2ecc71")
                self._db_status_label.configure(text="● Database connected")
            except Exception as e:
                self._db = None
                self._db_dot.configure(text_color="#e74c3c")
                self._db_status_label.configure(text="● DB error: {}".format(e))
        else:
            self._db_dot.configure(text_color="#f5a623")
            self._db_status_label.configure(
                text="● Database module unavailable - using mock data")

        if _AGENT_AVAILABLE and self._db:
            try:
                self._agent = Agent(self._db)
            except Exception:
                self._agent = None

    # =========================================================================
    #  DATA LOADING
    # =========================================================================

    def _db_rollback(self):
        """Reset a failed psycopg2 transaction so the connection can be reused."""
        try:
            self._db.conn.rollback()
        except Exception:
            pass

    def _load_invoices(self):
        if self._db:
            # Always rollback first to clear any aborted-transaction state
            self._db_rollback()
            try:
                raw = self._db.retrieve_data("invoices")

                import json as _json

                # Build OCR lookup: db_id (int) -> parsed JSONB dict
                ocr_lookup = {}
                try:
                    for ocr_row in self._db.retrieve_data("ocr_results"):
                        db_id  = ocr_row.get("invoice_id") or ocr_row.get("invoice_ID")
                        result = ocr_row.get("ocr_result") or ocr_row.get("OCR_result")
                        if db_id is not None and result:
                            if isinstance(result, str):
                                result = _json.loads(result)
                            ocr_lookup[int(db_id)] = result
                except Exception:
                    self._db_rollback()

                # Build validation_details lookup: db_id -> {confidence, transaction_id}
                val_lookup = {}
                try:
                    for val_row in self._db.retrieve_data("validation_details"):
                        did = val_row.get("invoice_id")
                        if did is not None:
                            val_lookup[int(did)] = {
                                "confidence":     float(val_row.get("confidence_score", 0)),
                                "transaction_id": val_row.get("transaction_id"),
                            }
                except Exception:
                    self._db_rollback()

                self._invoices = []
                for r in raw:
                    db_id = int(r.get("invoice_id") or r.get("invoice_ID", 0))
                    ocr   = ocr_lookup.get(db_id, {})
                    val   = val_lookup.get(db_id, {})

                    # validation_status is BOOLEAN in DB:
                    #   TRUE  = validated (auto or manual, distinguished by confidence)
                    #   FALSE = not yet validated (pending)
                    validated = bool(r.get("validation_status", False))
                    if validated:
                        confidence = val.get("confidence")
                        if confidence is not None and confidence >= CONFIDENCE_THRESHOLD:
                            ui_status = "auto_validated"
                        else:
                            ui_status = "manually_validated"
                    else:
                        ui_status  = "pending"
                        confidence = None

                    matched = []
                    txn_id  = val.get("transaction_id")
                    if txn_id:
                        matched = [txn_id]

                    self._invoices.append({
                        "invoice_id":        "INV-{:04d}".format(db_id),
                        "_db_id":            db_id,
                        "_confidence":       confidence,
                        "_matched_ids":      matched,
                        "date_of_purchase":  str(ocr.get("date", "")),
                        "amount":            float(ocr.get("invoice_amount", 0) or 0),
                        "currency":          str(ocr.get("currency", "")),
                        "description":       ocr.get("vendor") or str(r.get("file_name", "")),
                        "validation_status": ui_status,
                    })

            except Exception as e:
                self._db_rollback()
                messagebox.showerror("Load Error", "Could not load invoices:\n{}".format(e))
                self._invoices = list(MOCK_INVOICES)
        else:
            self._invoices = list(MOCK_INVOICES)

        self._render_invoices()
        self._update_stats()
        self._last_refresh_label.configure(
            text="Last refreshed: {}".format(datetime.now().strftime("%H:%M:%S")))

    def _render_invoices(self):
        for w in self._scroll.winfo_children():
            w.destroy()
        self._rows = []

        filtered = self._apply_filters(self._invoices)

        if not filtered:
            ctk.CTkLabel(self._scroll, text="No invoices match the current filter.",
                         font=ctk.CTkFont(size=14),
                         text_color=C["text_muted"]).pack(pady=60)
            return

        for idx, inv in enumerate(filtered):
            row = InvoiceRow(self._scroll, inv, idx,
                             on_run_ai=self._run_ai_for_row,
                             on_approve=self._approve_row,
                             on_select_change=self._update_select_all_state)
            row.grid(row=idx * 2, column=0, sticky="ew")
            self._scroll.columnconfigure(0, weight=1)
            self._rows.append(row)
            if idx < len(filtered) - 1:
                Separator(self._scroll).grid(row=idx * 2 + 1, column=0, sticky="ew")

    def _apply_filters(self, invoices):
        fv    = self._filter_var.get() if self._filter_var else "Show: All"
        query = self._search_entry.get().lower().strip() if self._search_entry else ""

        result = []
        for inv in invoices:
            s = inv.get("validation_status", "")
            if fv == "Show: Pending"      and s != "pending":          continue
            if fv == "Show: Needs Review" and s != "needs_manual":     continue
            if fv == "Show: Validated"    and s not in ("auto_validated", "manually_validated"): continue
            if query:
                haystack = " ".join([
                    inv.get("invoice_id", ""),
                    inv.get("description", ""),
                    inv.get("currency", ""),
                    str(inv.get("amount", "")),
                ]).lower()
                if query not in haystack:
                    continue
            result.append(inv)
        return result

    # =========================================================================
    #  STATS
    # =========================================================================

    def _update_stats(self):
        total   = len(self._invoices)
        pending = sum(1 for i in self._invoices if i["validation_status"] == "pending")
        review  = sum(1 for i in self._invoices if i["validation_status"] == "needs_manual")
        done    = sum(1 for i in self._invoices
                      if i["validation_status"] in ("auto_validated", "manually_validated"))
        self._card_total.set_value(str(total))
        self._card_pending.set_value(str(pending))
        self._card_review.set_value(str(review))
        self._card_done.set_value(str(done))

    # =========================================================================
    #  UPLOAD
    # =========================================================================

    def _upload_invoices(self):
        if not self._db:
            messagebox.showerror("No Database",
                                 "Cannot upload: not connected to the database.\n"
                                 "Running in mock mode.")
            return

        paths = filedialog.askopenfilenames(
            title="Select Invoice Files",
            filetypes=[
                ("Invoice files", "*.pdf *.docx *.jpg *.jpeg *.png"),
                ("PDF",   "*.pdf"),
                ("Word",  "*.docx"),
                ("Image", "*.jpg *.jpeg *.png"),
            ]
        )
        if not paths:
            return

        uploaded, skipped, errors = [], [], []

        for path in paths:
            filename = os.path.basename(path)
            ext      = os.path.splitext(filename)[1].lower().lstrip(".")

            if ext not in UPLOAD_EXT_MAP:
                skipped.append("{} (unsupported type .{})".format(filename, ext))
                continue

            file_type, requires_ocr = UPLOAD_EXT_MAP[ext]

            try:
                self._db.insert_data(
                    "invoices",
                    ["file_name", "file_path", "file_type", "requires_ocr", "validation_status"],
                    [filename, path, file_type, requires_ocr, False]  # FALSE (bool) = pending
                )
                uploaded.append(filename)
            except Exception as e:
                self._db_rollback()
                errors.append("{}: {}".format(filename, e))

        lines = []
        if uploaded:
            lines.append("Uploaded ({}):\n  ".format(len(uploaded)) +
                         "\n  ".join(uploaded))
        if skipped:
            lines.append("Skipped ({}):\n  ".format(len(skipped)) +
                         "\n  ".join(skipped))
        if errors:
            lines.append("Errors ({}):\n  ".format(len(errors)) +
                         "\n  ".join(errors))

        if uploaded:
            messagebox.showinfo("Upload Complete", "\n\n".join(lines))
            self._refresh()
        else:
            messagebox.showwarning("Nothing Uploaded",
                                   "\n\n".join(lines) or "No files uploaded.")

    # =========================================================================
    #  AI VALIDATION
    # =========================================================================

    def _run_ai_for_row(self, row):
        db_id = row.invoice.get("_db_id", row.invoice["invoice_id"])
        t = self._active_threads.get(db_id)
        if t and t.is_alive():
            return
        row.set_processing()
        t = threading.Thread(target=self._validation_worker, args=(db_id, row), daemon=True)
        self._active_threads[db_id] = t
        t.start()

    def _run_selected(self):
        selected = [r for r in self._rows
                    if r.is_selected and r.invoice.get("validation_status") == "pending"]
        if not selected:
            messagebox.showinfo("Nothing Selected",
                                "Please select one or more pending invoices.")
            return
        for row in selected:
            self._run_ai_for_row(row)

    def _validation_worker(self, db_id, row):
        result = {"status": "error", "confidence": None,
                  "matched_ids": [], "message": "Agent not available"}

        if self._agent:
            try:
                raw = self._agent.validate_transaction(db_id)
                if raw is None:
                    result = {"status": "error", "confidence": None,
                              "matched_ids": [], "message": "Agent returned None (WIP)"}
                elif isinstance(raw, dict):
                    result = raw
                else:
                    result = {"status": "error", "confidence": None,
                              "matched_ids": [], "message": str(raw)}
            except Exception as e:
                result = {"status": "error", "confidence": None,
                          "matched_ids": [], "message": str(e)}
        else:
            # Simulation mode — remove once real agent is connected
            import time, random
            time.sleep(2.5)
            confidence = round(random.uniform(0.72, 0.99), 4)
            status = "auto_validated" if confidence >= CONFIDENCE_THRESHOLD else "needs_manual"
            result = {
                "status":      status,
                "confidence":  confidence,
                "matched_ids": ["TXN-{}".format(random.randint(100000, 999999))],
                "message":     "Simulated (agent not connected)",
            }

        self.after(0, self._on_validation_done, db_id, row, result)

    def _on_validation_done(self, db_id, row, result):
        status     = result.get("status", "error")
        confidence = result.get("confidence")
        matched_ids = result.get("matched_ids") or []

        row.set_result(status, confidence, matched_ids, result.get("message", ""))

        # Update in-memory invoice
        for inv in self._invoices:
            if inv.get("_db_id") == db_id:
                inv["validation_status"] = status
                inv["_confidence"]       = confidence
                inv["_matched_ids"]      = matched_ids
                break

        # Only auto_validated writes TRUE to DB immediately.
        # needs_manual stays FALSE until the user clicks Approve.
        if self._db and status == "auto_validated" and confidence is not None:
            try:
                self._db.update_data(
                    "invoices", ["validation_status"], [True],
                    "invoice_id = %s", (db_id,)
                )
                txn_id = matched_ids[0] if matched_ids else None
                self._db.insert_data(
                    "validation_details",
                    ["invoice_id", "confidence_score", "transaction_id"],
                    [db_id, confidence, txn_id]
                )
            except Exception as e:
                self._db_rollback()
                print("[DB] Failed to persist auto_validated for {}: {}".format(db_id, e))

        self._active_threads.pop(db_id, None)
        self._update_stats()

    # =========================================================================
    #  MANUAL APPROVAL
    # =========================================================================

    def _approve_row(self, row):
        display_id = row.invoice["invoice_id"]
        db_id      = row.invoice.get("_db_id", display_id)
        confidence = row.invoice.get("_confidence") or 0.0
        matched_ids = row.invoice.get("_matched_ids") or []

        if not messagebox.askyesno("Confirm Approval",
                                   "Manually approve invoice {}?\n\n"
                                   "This will mark it as validated in the database.".format(display_id)):
            return

        row.set_approved()
        for inv in self._invoices:
            if inv.get("_db_id") == db_id:
                inv["validation_status"] = "manually_validated"
                break

        if self._db:
            try:
                # Write boolean TRUE (not the string "manually_validated")
                self._db.update_data(
                    "invoices", ["validation_status"], [True],
                    "invoice_id = %s", (db_id,)
                )
                txn_id = matched_ids[0] if matched_ids else None
                self._db.insert_data(
                    "validation_details",
                    ["invoice_id", "confidence_score", "transaction_id"],
                    [db_id, confidence, txn_id]
                )
            except Exception as e:
                self._db_rollback()
                messagebox.showerror("DB Error", "Could not update database:\n{}".format(e))

        self._update_stats()

    # =========================================================================
    #  TOOLBAR INTERACTIONS
    # =========================================================================

    def _on_search(self, _event=None):
        self._render_invoices()

    def _on_filter_change(self, _value=None):
        self._render_invoices()

    def _refresh(self):
        self._load_invoices()

    def _on_select_all(self):
        val = self._select_all_var.get()
        for row in self._rows:
            row.set_selected(val)

    def _update_select_all_state(self):
        if self._rows:
            self._select_all_var.set(all(r.is_selected for r in self._rows))

    # =========================================================================
    #  CLEANUP
    # =========================================================================

    def on_close(self):
        if self._db:
            try:
                self._db.close_connection()
            except Exception:
                pass
        self.destroy()


# =============================================================================
#  ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    app = GlobalTreasuryApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()