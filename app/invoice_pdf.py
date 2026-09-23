"""Invoice PDF renderer — reportlab, A4 portrait, print-ready, customer-facing.

Layout follows DESIGN_SPEC §4.8 + NEO 2026-09-23 redesign: modern, minimal, whitespace-driven
corporate invoice with hairline rules, tabular figures and a strict value/metadata hierarchy.
The SOLA logo (white wordmark on Sola Gold #CCA300) is the mandatory brand anchor; all other
ink is status-neutral near-black on white with muted-gray metadata. Brand tokens (DS §1.1):
gold #CCA300, gold-dark #8A6D00 (estimated text-on-light derivative), text #0F172A,
text-muted #64748B, border #E2E8F0, surface #FFFFFF / #FEFDFD.

Renders to bytes so the caller (route or test) decides the destination.

Changes here are VISUAL ONLY — no business logic, prices, totals, dates, status or data
source are touched. NEVER embeds HPP/margin/internal notes — only selling line items,
prices, totals and payment terms. NO NPWP rendered anywhere.
"""
import io
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
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
    KeepTogether,
)

# ---------------------------------------------------------------------------
# Brand tokens (DESIGN_SPEC §1.1)
# ---------------------------------------------------------------------------
GOLD = colors.HexColor("#CCA300")           # brand gold — logo field, accent only
GOLD_DARK = colors.HexColor("#8A6D00")      # estimated text-on-light derivative
INK = colors.HexColor("#0F172A")            # primary text
INK_MUTED = colors.HexColor("#64748B")      # labels / meta / footer
RULE = colors.HexColor("#E2E8F0")           # hairline rules / borders
SURFACE = colors.HexColor("#FFFFFF")
ANTIQUE = colors.HexColor("#FEFDFD")        # payment panel fill / zebra

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


def _xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _idr_qty(value):
    v = float(value or 0)
    if v == int(v):
        return str(int(v))
    return f"{v:g}"


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

    # ---- style kit (NEO: one family, no italics/serif; body >=9.5pt, labels >=8pt) ----
    base = ParagraphStyle(
        "base", parent=getSampleStyleSheet()["BodyText"], fontName=F,
        textColor=INK, leading=14,
    )
    s_company = ParagraphStyle("company", parent=base, fontSize=12, leading=15, fontName=FB,
                               textColor=INK)
    s_addr = ParagraphStyle("addr", parent=base, fontSize=8.5, leading=12, textColor=INK_MUTED)
    s_eyebrow = ParagraphStyle("eyebrow", parent=base, fontSize=15, leading=18, fontName=FB,
                               textColor=GOLD, alignment=TA_RIGHT)
    s_ref = ParagraphStyle("ref", parent=base, fontSize=20, leading=24, fontName=FB,
                           textColor=INK, alignment=TA_RIGHT)
    s_meta = ParagraphStyle("metaline", parent=base, fontSize=8.5, leading=12,
                            textColor=INK_MUTED, alignment=TA_RIGHT)
    s_section = ParagraphStyle("section", parent=base, fontSize=8.5, leading=12, fontName=FB,
                               textColor=GOLD_DARK)
    s_btoname = ParagraphStyle("btoname", parent=base, fontSize=15, leading=18, fontName=FB,
                               textColor=INK)
    s_btdetail = ParagraphStyle("btdetail", parent=base, fontSize=9.5, leading=14,
                                textColor=INK_MUTED)
    s_metakey = ParagraphStyle("metakey", parent=base, fontSize=8, leading=11, fontName=FB,
                               textColor=INK_MUTED)
    s_metaval = ParagraphStyle("metaval", parent=base, fontSize=10, leading=14, fontName=FB,
                               textColor=INK, alignment=TA_RIGHT)
    s_th = ParagraphStyle("th", parent=base, fontSize=8.5, leading=11, fontName=FB,
                          textColor=INK_MUTED)
    s_tcell = ParagraphStyle("tcell", parent=base, fontSize=9.5, leading=13, textColor=INK)
    s_tnum = ParagraphStyle("tnum", parent=s_tcell, alignment=TA_RIGHT, textColor=INK)
    s_sumkey = ParagraphStyle("sumkey", parent=base, fontSize=9.5, leading=13, textColor=INK_MUTED)
    s_sumval = ParagraphStyle("sumval", parent=base, fontSize=9.5, leading=13,
                              textColor=INK, alignment=TA_RIGHT)
    s_grand = ParagraphStyle("grandlabel", parent=base, fontSize=12, leading=16, fontName=FB,
                             textColor=INK)
    s_grandval = ParagraphStyle("grandval", parent=base, fontSize=12.5, leading=16, fontName=FB,
                                textColor=INK, alignment=TA_RIGHT)
    s_outl = ParagraphStyle("outl", parent=base, fontSize=9.5, leading=13, fontName=FB,
                            textColor=INK)
    s_outv = ParagraphStyle("outv", parent=base, fontSize=10.5, leading=14, fontName=FB,
                            textColor=GOLD_DARK, alignment=TA_RIGHT)
    s_paynote = ParagraphStyle("paynote", parent=base, fontSize=10, leading=15, textColor=INK)
    s_payinst = ParagraphStyle("payinst", parent=base, fontSize=8.5, leading=12,
                               textColor=INK_MUTED)
    s_footer = ParagraphStyle("footer", parent=base, fontSize=8, leading=11,
                              textColor=INK_MUTED, alignment=TA_CENTER)

    # ---- document with margins = 14mm ----
    margin = 14 * mm
    content_w = A4[0] - 2 * margin  # 182mm
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

    # ---- 1. Masthead: logo + company (left) | INVOICE title + ref (right) ----
    # Logo source is PORTRAIT 1080x1350 (aspect 0.8, gold field edge-to-edge): preserve
    # its natural aspect in a 32x40mm display box so the wordmark stays crisp, not stretched.
    logo_img = Image(logo_abs, width=32 * mm, height=40 * mm) if logo_ok else Paragraph(cname, s_company)
    left_cell = [
        logo_img,
        Spacer(1, 4 * mm),
        Paragraph(cname, s_company),
        Spacer(1, 1 * mm),
        Paragraph(_xml(caddress or ""), s_addr),
        Paragraph(("Telp/WA " + cphone) if cphone else "", s_addr),
    ]
    meta_line = "Tanggal: " + _fmt_date(inv["invoice_date"])
    if inv["due_date"]:
        meta_line += " · Jatuh Tempo: " + _fmt_date(inv["due_date"])
    right_cell = [
        Paragraph("INVOICE", s_eyebrow),
        Spacer(1, 2 * mm),
        Paragraph(_xml(inv["invoice_number"]), s_ref),
        Spacer(1, 6 * mm),
        Paragraph(meta_line, s_meta),
    ]
    masthead = Table([[left_cell, right_cell]], colWidths=[100 * mm, 82 * mm])
    masthead.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    # gold masthead hairline (0.8pt #CCA300)
    hairline = Table([[""]], colWidths=[content_w], rowHeights=[0.8])
    hairline.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(KeepTogether([masthead, Spacer(1, 6 * mm), hairline, Spacer(1, 6 * mm)]))

    # ---- 2. Meta + Bill-To band (2-col, TOP aligned, no borders) ----
    bill_lines = []
    if cust is not None:
        btoname = (cust["name"] or "") + ((", " + cust["company_name"]) if cust["company_name"] else "")
        if cust["pic_name"]:
            bill_lines.append("Attn: " + cust["pic_name"])
        if cust["address"]:
            bill_lines.append(str(cust["address"]))
        if cust["phone"]:
            bill_lines.append("Telp: " + str(cust["phone"]))
    else:
        btoname = "-"
    bill_cell = [Paragraph("BILL TO", s_section), Spacer(1, 3 * mm),
                 Paragraph(_xml(btoname), s_btoname)]
    for ln in bill_lines:
        bill_cell.append(Paragraph(_xml(ln), s_btdetail))

    meta_rows = [
        [Paragraph("NO", s_metakey), Paragraph(_xml(inv["invoice_number"]), s_metaval)],
        [Paragraph("TANGGAL", s_metakey), Paragraph(_fmt_date(inv["invoice_date"]), s_metaval)],
    ]
    if inv["due_date"]:
        meta_rows.append([Paragraph("JATUH TEMPO", s_metakey), Paragraph(_fmt_date(inv["due_date"]), s_metaval)])
    meta_table = Table(meta_rows, colWidths=[40 * mm, 58 * mm])
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    bill_band = Table([[bill_cell, meta_table]], colWidths=[84 * mm, 98 * mm])
    bill_band.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(KeepTogether([bill_band, Spacer(1, 8 * mm)]))

    # ---- 3. Line items table (5 cols, no grid, header underline only) ----
    if not items:
        raise ValueError(f"invoice {invoice_id} has no line items")

    header_row = [
        Paragraph("NO", s_th),
        Paragraph("DESKRIPSI", s_th),
        Paragraph("QTY", s_th),
        Paragraph("HARGA SATUAN", s_th),
        Paragraph("JUMLAH", s_th),
    ]
    rows = [header_row]
    for i, it in enumerate(items, start=1):
        qty = float(it["quantity"] or 0)
        price = float(it["unit_price"] or 0)
        amount = float(it["subtotal"] or 0)
        desc = it["description"] or "-"
        safe_desc = _xml(desc)
        rows.append([
            Paragraph(str(i), s_tcell),
            Paragraph(safe_desc, s_tcell),
            Paragraph(_idr_qty(qty), s_tnum),
            Paragraph(_idr(price), s_tnum),
            Paragraph(_idr(amount), s_tnum),
        ])
    tbl = Table(rows, colWidths=[12 * mm, 74 * mm, 20 * mm, 38 * mm, 38 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        # header underline (1pt #E2E8F0) only — no vertical/side grid
        ("LINEBELOW", (0, 0), (-1, 0), 1, RULE),
        # hairline under last body row (0.6pt #E2E8F0)
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8 * mm))

    # ---- 4. Summary block (right-aligned: label 58mm + value 34mm = 92mm) ----
    subtotal = float(inv["subtotal"] or 0)
    discount = float(inv["discount"] or 0)
    tax = float(inv["tax"] or 0)
    sum_rows = [
        [Paragraph("Subtotal", s_sumkey), Paragraph(_idr(subtotal), s_sumval)],
    ]
    if discount:
        sum_rows.append([Paragraph("Diskon", s_sumkey), Paragraph("- " + _idr(discount), s_sumval)])
    if tax:
        sum_rows.append([Paragraph("Pajak", s_sumkey), Paragraph(_idr(tax), s_sumval)])
    grand_row_idx = len(sum_rows)  # row immediately after subtotal/disc/tax = Grand Total
    # gold rule above the Grand Total row, then dominant Grand Total
    sum_rows.append([Paragraph("Grand Total", s_grand), Paragraph(_idr(grand), s_grandval)])
    sum_rows.append([Paragraph("Jumlah Dibayar", s_sumkey), Paragraph(_idr(paid), s_sumval)])
    sum_rows.append([Paragraph("Sisa Tagihan (Outstanding)", s_outl), Paragraph(_idr(outstanding), s_outv)])
    summary = Table(sum_rows, colWidths=[58 * mm, 34 * mm], hAlign="RIGHT")
    summary.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        # gold rule above the Grand Total row
        ("LINEABOVE", (0, grand_row_idx), (-1, grand_row_idx), 1.2, GOLD),
    ]))
    story.append(KeepTogether([summary, Spacer(1, 10 * mm)]))

    # ---- 5. Payment information panel (182mm box, fill #FEFDFD, pad 6mm) ----
    pay_cell = [
        Paragraph(_xml(pay_label), s_section),
        Spacer(1, 3 * mm),
        Paragraph(_xml(pay_note), s_paynote),
        Spacer(1, 2 * mm),
        Paragraph("Mohon transfer sesuai jumlah Sisa Tagihan di atas dan konfirmasi melalui kontak kami.", s_payinst),
    ]
    pay_panel = Table([[pay_cell]], colWidths=[content_w])
    pay_panel.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, RULE),
        ("BACKGROUND", (0, 0), (-1, -1), ANTIQUE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6 * mm),
    ]))
    story.append(KeepTogether([pay_panel, Spacer(1, 12 * mm)]))

    # ---- 6. Footer (centered muted one line) ----
    footer_note = company.get("footer_note", "Terima kasih atas kepercayaan Anda.")
    story.append(Paragraph(_xml(footer_note), s_footer))

    doc.build(story)
    return buf.getvalue()