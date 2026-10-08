"""Simplified commercial module — Invoice ONLY (no quotation/order/production)."""
from datetime import date, timedelta, timezone
import logging
from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template,
    request, send_file, url_for
)
from .auth import require_permission
from .invoice_pdf import render_invoice_pdf
import sqlite3

_logger = logging.getLogger(__name__)

INVOICE_BP = Blueprint("invoices", __name__, url_prefix="/invoices")
INV_STATUSES = ["draft", "issued", "partially_paid", "paid", "overdue", "cancelled"]
PAY_METHODS = ["transfer", "cash", "qris", "other"]

def _db():
    conn = sqlite3.connect(current_app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    return conn

def _next_number(prefix, table, col):
    conn = _db()
    cur = conn.execute(f"SELECT {col} FROM {table} ORDER BY {col} DESC LIMIT 1")
    last = cur.fetchone()
    conn.close()
    year = date.today().strftime("%Y")
    if last:
        num_part = str(last[col]).replace(prefix, "").replace("-" + year, "")
        try:
            n = int(num_part) + 1
        except ValueError:
            n = 1
    else:
        n = 1
    return f"{prefix}-{year}-{n:04d}"

def _money(amount):
    return f"Rp {amount:,.0f}"

@INVOICE_BP.route("/")
@require_permission("invoice.view")
def list():
    conn = _db()
    rows = conn.execute("SELECT * FROM invoices ORDER BY invoice_id DESC").fetchall()
    conn.close()
    return render_template("invoice_list.html", rows=rows, statuses=INV_STATUSES)

@INVOICE_BP.route("/new", methods=["GET", "POST"])
@require_permission("invoice.create")
def new_invoice():
    if request.method == "POST":
        conn = _db()
        number = _next_number("INV", "invoices", "invoice_number")
        customer_id = request.form.get("customer_id") or 1
        subtotal = float(request.form.get("subtotal") or 0)
        discount = float(request.form.get("discount") or 0)
        tax_rate = float(request.form.get("tax_rate") or 0)
        tax = subtotal * tax_rate / 100
        grand_total = round(subtotal - discount + tax, 2)
        due = (date.today() + timedelta(days=14)).isoformat()
        cur = conn.execute(
            "INSERT INTO invoices (invoice_number, order_id, customer_id, invoice_date, due_date, subtotal, discount, tax, grand_total, amount_paid, outstanding, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (number, 1, customer_id, date.today().isoformat(), due, subtotal, discount, tax, grand_total, 0, grand_total, "draft")
        )
        inv_id = cur.lastrowid
        conn.commit()
        descriptions = request.form.getlist("item_description[]")
        quantities = request.form.getlist("item_qty[]")
        prices = request.form.getlist("item_price[]")
        for desc, qty_str, price_str in zip(descriptions, quantities, prices):
            qty = float(qty_str or 1)
            price = float(price_str or 0)
            subtotal_item = round(qty * price, 2)
            conn.execute(
                "INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, subtotal) VALUES (?, ?, ?, ?, ?)",
                (inv_id, desc, qty, price, subtotal_item)
            )
        conn.commit()
        conn.close()
        flash(f"Invoice {number} created.", "success")
        return redirect(url_for("invoices.detail", iid=inv_id))
    conn = _db()
    customers = conn.execute("SELECT customer_id, name FROM customers").fetchall()
    conn.close()
    return render_template("invoice_form.html", customers=customers)

@INVOICE_BP.route("/<int:iid>")
@require_permission("invoice.view")
def detail(iid):
    conn = _db()
    inv = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (iid,)).fetchone()
    if not inv:
        conn.close()
        abort(404)
    items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (iid,)).fetchall()
    payments = conn.execute("SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_id DESC", (iid,)).fetchall()
    customers = conn.execute("SELECT * FROM customers WHERE customer_id = ?", (inv["customer_id"],)).fetchone()
    conn.close()
    i_data = dict(inv)
    i_data["items"] = [dict(r) for r in items]
    i_data["payments"] = [dict(r) for r in payments]
    i_data["customer"] = dict(customers) if customers else {}
    return render_template("invoice_detail.html", i=i_data, items=items, payments=payments, methods=PAY_METHODS, statuses=INV_STATUSES)

@INVOICE_BP.route("/<int:iid>/pdf")
@require_permission("invoice.view")
def pdf(iid):
    conn = _db()
    inv = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (iid,)).fetchone()
    if not inv:
        conn.close()
        abort(404)
    items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (iid,)).fetchall()
    payments = conn.execute("SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_id DESC", (iid,)).fetchall()
    customers = conn.execute("SELECT * FROM customers WHERE customer_id = ?", (inv["customer_id"],)).fetchone()
    conn.close()
    company = current_app.config.get("COMPANY", {})
    payload = render_invoice_pdf({"invoices": [dict(inv)], "invoice_items": [dict(r) for r in items], "payments": [dict(r) for r in payments], "customers": [dict(customers) if customers else {}]}, iid, company=company)
    import io
    return send_file(io.BytesIO(payload), mimetype="application/pdf", as_attachment=False, download_name=f"{inv['invoice_number']}.pdf")


@INVOICE_BP.route("/<int:iid>/status", methods=["POST"])
@require_permission("invoice.update")
def set_status(iid):
    conn = _db()
    inv = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (iid,)).fetchone()
    if not inv:
        conn.close()
        abort(404)
    new_status = request.form.get("status")
    if new_status in INV_STATUSES:
        conn.execute("UPDATE invoices SET status = ? WHERE invoice_id = ?", (new_status, iid))
        conn.commit()
        flash(f"Status updated to {new_status}.", "success")
    else:
        flash("Invalid status.", "danger")
    conn.close()
    return redirect(url_for("invoices.detail", iid=iid))

@INVOICE_BP.route("/<int:iid>/payment", methods=["POST"])
@require_permission("invoice.payment")
def add_payment(iid):
    conn = _db()
    inv = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (iid,)).fetchone()
    if not inv:
        conn.close()
        abort(404)
    amount = float(request.form.get("amount") or 0)
    if amount <= 0:
        flash("Payment must be positive.", "danger")
        conn.close()
        return redirect(url_for("invoices.detail", iid=iid))
    method = request.form.get("method") or "transfer"
    reference = request.form.get("reference") or None
    notes = request.form.get("notes") or None
    conn.execute(
        "INSERT INTO payments (invoice_id, payment_date, amount, method, reference, notes, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (iid, date.today().isoformat(), amount, method, reference, notes, g.current_user.get("user_id", 1))
    )
    conn.commit()
    payments = conn.execute("SELECT SUM(amount) as total FROM payments WHERE invoice_id = ?", (iid,)).fetchone()
    total_paid = float(payments["total"] or 0)
    grand_total = float(inv["grand_total"])
    outstanding = round(grand_total - total_paid, 2)
    status = "paid" if outstanding <= 0.005 else ("partially_paid" if total_paid > 0 else inv["status"])
    conn.execute("UPDATE invoices SET amount_paid = ?, outstanding = ?, status = ? WHERE invoice_id = ?",
                 (total_paid, outstanding, status, iid))
    conn.commit()
    conn.close()
    flash(f"Payment recorded. Outstanding: Rp {outstanding:,.0f} ({status}).", "success")
    return redirect(url_for("invoices.detail", iid=iid))
