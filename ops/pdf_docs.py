"""Generate Arabic PDF documents for ops (returns / supply)."""
from __future__ import annotations

import io
from pathlib import Path

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_PATH = Path(__file__).resolve().parent / "fonts" / "NotoNaskhArabic-Regular.ttf"
_FONT_NAME = "NotoNaskhArabic"
_FONT_REGISTERED = False


def _ensure_font() -> str:
    global _FONT_REGISTERED
    if not _FONT_REGISTERED and FONT_PATH.exists():
        pdfmetrics.registerFont(TTFont(_FONT_NAME, str(FONT_PATH)))
        _FONT_REGISTERED = True
    return _FONT_NAME if _FONT_REGISTERED else "Helvetica"


def _ar(text) -> str:
    """Shape Arabic for left-to-right PDF drawing (visual RTL)."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(raw))
    except Exception:
        return raw


def _styles():
    font = _ensure_font()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ArTitle",
            parent=base["Title"],
            fontName=font,
            fontSize=16,
            leading=22,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "h": ParagraphStyle(
            "ArH",
            parent=base["Normal"],
            fontName=font,
            fontSize=11,
            leading=16,
            alignment=TA_RIGHT,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "ArBody",
            parent=base["Normal"],
            fontName=font,
            fontSize=10,
            leading=14,
            alignment=TA_RIGHT,
        ),
        "meta": ParagraphStyle(
            "ArMeta",
            parent=base["Normal"],
            fontName=font,
            fontSize=9,
            leading=13,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#334155"),
        ),
        "cell": ParagraphStyle(
            "ArCell",
            parent=base["Normal"],
            fontName=font,
            fontSize=8,
            leading=11,
            alignment=TA_RIGHT,
        ),
    }


def _meta_block(rows: list[tuple[str, str]], styles) -> list:
    flow = []
    for label, value in rows:
        flow.append(
            Paragraph(f"{_ar(value)}  :{_ar(label)}", styles["meta"])
        )
    flow.append(Spacer(1, 0.35 * cm))
    return flow


def _table(headers: list[str], rows: list[list[str]], styles) -> Table:
    font = _ensure_font()
    head = [Paragraph(_ar(h), styles["cell"]) for h in headers]
    body = [[Paragraph(_ar(c), styles["cell"]) for c in row] for row in rows]
    data = [head] + body
    col_w = A4[0] - 2.4 * cm
    n = max(len(headers), 1)
    widths = [col_w / n] * n
    tbl = Table(data, colWidths=widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f1f5f9")],
                ),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return tbl


def _build(story) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title="عمليات الفرش",
    )
    doc.build(story)
    return buf.getvalue()


def role_label(user) -> str:
    if not user:
        return "—"
    return getattr(user, "get_role_display", lambda: "")() or "—"


def build_return_batch_pdf(batch) -> tuple[bytes, str]:
    """Return (pdf_bytes, filename) for a ReturnBatch."""
    styles = _styles()
    items = list(batch.items.select_related("representative").all())
    created = timezone.localtime(batch.created_at).strftime("%Y-%m-%d %H:%M")
    creator = batch.created_by
    rep = batch.representative

    story = [
        Paragraph(_ar("عمليات الفرش — ملف مرتجع"), styles["title"]),
        Paragraph(_ar("مستند تشغيلي رسمي"), styles["h"]),
        Spacer(1, 0.2 * cm),
    ]
    story.extend(
        _meta_block(
            [
                ("رقم الملف", batch.return_number),
                ("الفرع", batch.branch),
                ("الحالة", batch.get_display_status_display()),
                ("عدد الأصناف", str(len(items))),
                ("تاريخ الإنشاء", created),
                ("المرسل", f"{creator.display_name} — {role_label(creator)}"),
                ("المندوب المسؤول", f"{rep.display_name} — {role_label(rep)}"),
            ],
            styles,
        )
    )
    story.append(Paragraph(_ar("تفاصيل الأصناف"), styles["h"]))

    headers = ["السبب", "النوع", "الكمية", "العبوة", "الوحدة", "رقم الصنف", "الاسم", "#"]
    rows = []
    for i, it in enumerate(items, 1):
        rows.append(
            [
                (it.reason or "")[:80],
                it.get_return_type_display(),
                str(it.quantity),
                it.package or "—",
                it.unit or "—",
                it.item_number or "—",
                it.item_name,
                str(i),
            ]
        )
    story.append(_table(headers, rows, styles))
    story.append(Spacer(1, 0.5 * cm))
    story.append(
        Paragraph(
            _ar(
                "إجراء مطلوب من المندوب: متابعة الملف، تعميد/رفض الأصناف، والرد على النظام."
            ),
            styles["body"],
        )
    )

    filename = f"return_{batch.return_number.replace('#', '')}.pdf"
    return _build(story), filename


def build_supply_orders_pdf(orders: list, *, actor) -> tuple[bytes, str]:
    """Return (pdf_bytes, filename) for one or more SupplyOrder rows."""
    styles = _styles()
    if not orders:
        raise ValueError("لا توجد طلبات توريد")
    first = orders[0]
    created = timezone.localtime(first.created_at).strftime("%Y-%m-%d %H:%M")
    rep = first.representative
    nums = [o.order_number for o in orders]

    story = [
        Paragraph(_ar("عمليات الفرش — طلبات توريد"), styles["title"]),
        Paragraph(_ar("مستند تشغيلي رسمي"), styles["h"]),
        Spacer(1, 0.2 * cm),
    ]
    story.extend(
        _meta_block(
            [
                ("أرقام الطلبات", "، ".join(nums)),
                ("عدد الطلبات", str(len(orders))),
                ("تاريخ الإنشاء", created),
                ("المرسل", f"{actor.display_name} — {role_label(actor)}"),
                ("المندوب", f"{rep.display_name} — {role_label(rep)}"),
            ],
            styles,
        )
    )
    story.append(Paragraph(_ar("تفاصيل الأصناف"), styles["h"]))
    headers = ["ملاحظات", "التاريخ المتوقع", "الكمية", "العبوة", "الوحدة", "رقم الصنف", "الاسم", "رقم الطلب"]
    rows = []
    for o in orders:
        exp = o.expected_date.isoformat() if o.expected_date else "—"
        rows.append(
            [
                (o.notes or "")[:60] or "—",
                exp,
                str(o.quantity),
                o.package or "—",
                o.unit or "—",
                o.item_number or "—",
                o.item_name,
                o.order_number,
            ]
        )
    story.append(_table(headers, rows, styles))
    filename = f"supply_{nums[0].replace('#', '')}.pdf"
    if len(nums) > 1:
        filename = f"supply_batch_{len(nums)}.pdf"
    return _build(story), filename
