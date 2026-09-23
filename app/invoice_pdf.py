"""Invoice PDF renderer — reportlab, A4 portrait, print-ready, customer-facing.

Layout follows DESIGN_SPEC §4.8 with the real SOLA company block from
app.config['COMPANY'] (name/address/phone) + KETERANGAN PEMBAYARAN bank note.
NO NPWP is rendered anywhere. Only the brand logo uses the brand color; all
other ink is status-neutral black on white. NEVER embeds HPP/margin/internal
notes — only selling line items, prices, totals and payment terms.

Renders to bytes so the caller (route or test) decides the destination.
"""
import io
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Fonts — Arial TrueType so Unicode (Rp…, accented characters) renders.
# Helvetica (Type1, Latin-1) mangles some glyphs; register TTF instead.
# ---------------------------------------------------------------------------
_FONT_DIR = "C:/Windows/Fonts"
_FONTS_REGISTERED = False


def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    for registered_name, file in (("SOLA-REG", "arial.ttf"), ("SOLA-BOLD", "arialbd.ttf")):
        path = os.path.join(_FONT_DIR, file)
        if os.path.isfile(path):
            try:
                pdfmetrics.registerFont(TTFont(registered_name, path))
            except Exception:
                pass  # fall back to built-in Helvetica below
    # Always register Helvetica aliases so Paragraph styles never reference a
    # missing font even if the TTF registration failed.
    pdfmetrics.registerFontFamily(
        "SOLA",
        normal="SOLA-REG",
        bold="SOLA-BOLD",
        italic="SOLA-REG",
        boldItalic="SOLA-BOLD",
    )
    _FONTS_REGISTERED = True


def _font_available():
    try:
        return pdfmetrics.getFont("SOLA-REG").fontName == "SOLA-REG"
    except Exception:
        return False


def _base_font():
    return "SOLA-REG" if _font_available() else "Helvetica"


def _bold_font():
    return "SOLA-BOLD" if _font_available() else "Helvetica-Bold"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _idr(value):
    """Locale-neutral tabular IDR: 'Rp 55.000' (dot thousands; ASCII)."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0.0
    return "Rp {:,.0f}".format(v).replace(",", ".")


def _fmt_date(value):
    """yyyy-mm-dd -> dd/mm/yyyy (Indonesian business convention)."""
    s = str(value or "")[:10]
    parts = s.split("-")
    if len(parts) == 3:
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return s


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------
def render_invoice_pdf(conn, invoice_id, company=None) -> bytes:
    """Render one invoice to PDF bytes.

    conn: a SheetRelational engine (app.sheetdb, table tabs defined) OR anything
    with .execute (app request conn, direct sqlite conn, test conn).
    company: dict with company_name/address/phone/payment_label/payment_note/brand_logo
    """
    _register_fonts()
    F = _base_font()
    FB = _bold_font()

    _sheet = hasattr(conn, "table")
    if _sheet:
        inv = conn.table("invoices").get(invoice_id)
    else:
        inv = conn.execute(
            "SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)
        ).fetchone()
    if inv is None:
        raise ValueError(f"invoice {invoice_id} not found")

    if _sheet:
        cust = conn.table("customers").get(inv["customer_id"]) if inv.get("customer_id") is not None else None
        items = sorted(conn.table("invoice_items").find(invoice_id=invoice_id),
                       key=lambda r: float(r.get("invoice_item_id") or 0))
        payments = sorted(conn.table("payments").find(invoice_id=invoice_id),
                          key=lambda r: float(r.get("payment_id") or 0))
    else:
        cust = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (inv["customer_id"],)
        ).fetchone()
        items = conn.execute(
            "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY invoice_item_id",
            (invoice_id,),
        ).fetchall()
        payments = conn.execute(
            "SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_id",
            (invoice_id,),
        ).fetchall()

    company = company or {}
    cname = company.get("company_name", "Sola Konveksi Yogyakarta")
    caddress = company.get("address", "")
    cphone = company.get("phone", "")
    pay_label = company.get("payment_label", "KETERANGAN PEMBAYARAN")
    pay_note = company.get(
        "payment_note", "Pembayaran dilakukan secara transfer ke rekening: BCA 4452337111 a.n. Irhami Al Adaby"
    )
    logo_rel = company.get("brand_logo", "app/static/assets/sola-logo-1.png")

    # Resolve logo absolute path relative to project root (D:/Sola).
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logo_abs = os.path.join(project_root, logo_rel) if not os.path.isabs(logo_rel) else logo_rel
    logo_ok = os.path.isfile(logo_abs)

    grand = float(inv["grand_total"] or 0)
    paid = float(inv["amount_paid"] or 0)
    outstanding = float(inv["outstanding"] or 0)

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=styles["BodyText"], fontName=F, fontSize=9.5, leading=13,
        textColor=colors.black, alignment=TA_LEFT,
    )
    small = ParagraphStyle(
        "small", parent=body, fontSize=8.5, leading=11.5, textColor=colors.Color(0, 0, 0),
    )
    head = ParagraphStyle(
        "head", parent=body, fontSize=13, leading=16, fontName=FB,
    )
    title = ParagraphStyle(
        "title", parent=body, fontSize=20, leading=24, fontName=FB,
    )
    th = ParagraphStyle(
        "th", parent=body, fontName=FB, fontSize=9, leading=12,
    )

    # ---- document with margins >= 12mm ----
    margin = 14 * mm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=f"Invoice {inv['invoice_number']}",
        author=cname,
    )

    story = []

    # ---- 1. Company header + INVOICE title + ref ----
    header = Table(
        [[Image(logo_abs, width=58 * mm, height=30 * mm) if logo_ok else "", ""],
         [Paragraph(cname, ParagraphStyle("cn", parent=head, fontSize=16))],
         [Paragraph(caddress or "", small)],
         [Paragraph(("Telp/WA: " + cphone) if cphone else "", small)]],
        colWidths=[90 * mm, 80 * mm],
    )
    header.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(header)
    story.append(Spacer(1, 6 * mm))

    ref_block = Table(
        [[Paragraph("INVOICE", title)],
         [Paragraph(f"No. {inv['invoice_number']}", ParagraphStyle("rn", parent=body, fontName=FB))],
         [Paragraph(
             f"Tanggal: {_fmt_date(inv['invoice_date'])}"
             + (f"   Jatuh Tempo: {_fmt_date(inv['due_date'])}" if inv["due_date"] else ""),
             small)]],
        colWidths=[170 * mm],
    )
    ref_block.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(ref_block)
    story.append(Spacer(1, 8 * mm))

    # ---- 2. Bill-to block ----
    bill_lines = []
    if cust is not None:
        bill = (cust["name"] or "") + ((", " + cust["company_name"]) if cust["company_name"] else "")
        bill_lines.append(bill)
        if cust["pic_name"]:
            bill_lines.append("Attn: " + cust["pic_name"])
        if cust["address"]:
            bill_lines.append(str(cust["address"]))
        if cust["phone"]:
            bill_lines.append("Telp: " + str(cust["phone"]))
    bill_text = "<br/>".join(bill_lines) if bill_lines else "-"
    bill_to = Table(
        [[Paragraph("Kepada / Bill To", ParagraphStyle("bt", parent=body, fontName=FB))],
         [Paragraph(bill_text, body)]],
        colWidths=[80 * mm],
    )
    bill_to.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("BOX", (0, 0), (0, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
        ("BACKGROUND", (0, 0), (0, 0), colors.Color(0.97, 0.97, 0.97)),
    ]))
    story.append(bill_to)
    story.append(Spacer(1, 6 * mm))

    # ---- 3. Line items table (qty | description | unit price | amount) ----
    if not items:
        raise ValueError(f"invoice {invoice_id} has no line items")

    tbl_style = ParagraphStyle("tbl", parent=body, fontSize=9, leading=12)
    tcell = ParagraphStyle("tcell", parent=tbl_style, alignment=TA_LEFT)
    tnum = ParagraphStyle("tnum", parent=tbl_style, alignment=TA_RIGHT, fontName=F)

    header_row = [
        Paragraph("No", th),
        Paragraph("Deskripsi", th),
        Paragraph("Qty", th),
        Paragraph("Harga Satuan", th),
        Paragraph("Jumlah", th),
    ]
    rows = [header_row]
    for i, it in enumerate(items, start=1):
        qty = float(it["quantity"] or 0)
        price = float(it["unit_price"] or 0)
        amount = float(it["subtotal"] or 0)
        desc = it["description"] or "-"
        # ASCII-safe: Arial handles Rp + common punctuation; strip exotic glyphs.
        safe_desc = desc.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rows.append([
            Paragraph(str(i), tcell),
            Paragraph(safe_desc, tcell),
            Paragraph(_idr_qty(qty), tnum),
            Paragraph(_idr(price), tnum),
            Paragraph(_idr(amount), tnum),
        ])
    tbl = Table(rows, colWidths=[12 * mm, 92 * mm, 16 * mm, 26 * mm, 24 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.93, 0.93, 0.93)),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.Color(0.85, 0.85, 0.85)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 5 * mm))

    # ---- 3b. Totals ----
    subtotal = float(inv["subtotal"] or 0)
    discount = float(inv["discount"] or 0)
    tax = float(inv["tax"] or 0)
    total_rows = [
        [Paragraph("Subtotal", small), Paragraph(_idr(subtotal), tnum)],
    ]
    if discount:
        total_rows.append([Paragraph("Diskon", small), Paragraph("- " + _idr(discount), tnum)])
    if tax:
        total_rows.append([Paragraph("Pajak", small), Paragraph(_idr(tax), tnum)])
    total_rows.append([Paragraph("Grand Total", ParagraphStyle("gt", parent=body, fontName=FB)),
                       Paragraph(_idr(grand), ParagraphStyle("gtv", parent=tnum, fontName=FB))])
    totals = Table(total_rows, colWidths=[60 * mm, 30 * mm])
    totals.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
    ]))
    story.append(totals)
    story.append(Spacer(1, 5 * mm))

    # ---- 4. Payment terms + outstanding ----
    pay_in = Table([
        [Paragraph("Jumlah Dibayar", small), Paragraph(_idr(paid), tnum)],
        [Paragraph("Sisa Tagihan (Outstanding)", ParagraphStyle("os", parent=body, fontName=FB)),
         Paragraph(_idr(outstanding), ParagraphStyle("osv", parent=tnum, fontName=FB))],
    ], colWidths=[60 * mm, 30 * mm])
    pay_in.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(pay_in)
    story.append(Spacer(1, 6 * mm))

    pay_note_block = Table(
        [[Paragraph(pay_label, ParagraphStyle("pn", parent=body, fontName=FB))],
         [Paragraph(_xml(pay_note), body)],
         [Paragraph("Mohon transfer sesuai jumlah Sisa Tagihan di atas dan konfirmasi melalui kontak kami.", small)]],
        colWidths=[170 * mm],
    )
    pay_note_block.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("BOX", (0, 0), (0, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
        ("BACKGROUND", (0, 0), (0, 0), colors.Color(0.97, 0.97, 0.97)),
    ]))
    story.append(pay_note_block)

    # ---- 5. Footer ----
    footer_note = company.get("footer_note", "Terima kasih atas kepercayaan Anda.")
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(_xml(footer_note), small))

    doc.build(story)
    return buf.getvalue()


def _xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _idr_qty(value):
    v = float(value or 0)
    if v == int(v):
        return str(int(v))
    return f"{v:g}"