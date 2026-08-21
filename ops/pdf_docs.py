"""Generate official Arabic PDF documents for ops (returns / supply purchase orders)."""
from __future__ import annotations

import io
from pathlib import Path

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_PATH = Path(__file__).resolve().parent / "fonts" / "NotoNaskhArabic-Regular.ttf"
_FONT_NAME = "NotoNaskhArabic"
_FONT_REGISTERED = False

# Official document palette (navy + gold accent — not purple)
NAVY = colors.HexColor("#0f2744")
NAVY_MID = colors.HexColor("#1e3a5f")
ACCENT = colors.HexColor("#1d4ed8")
GOLD = colors.HexColor("#b45309")
GOLD_SOFT = colors.HexColor("#c5a572")
SLATE = colors.HexColor("#334155")
LINE = colors.HexColor("#94a3b8")
ROW_ALT = colors.HexColor("#f1f5f9")
META_BG = colors.HexColor("#f8fafc")
WHITE = colors.white


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
        "brand": ParagraphStyle(
            "ArBrand",
            parent=base["Normal"],
            fontName=font,
            fontSize=18,
            leading=24,
            alignment=TA_CENTER,
            textColor=WHITE,
        ),
        "brand_sub": ParagraphStyle(
            "ArBrandSub",
            parent=base["Normal"],
            fontName=font,
            fontSize=9,
            leading=13,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#dbeafe"),
        ),
        "doc_title": ParagraphStyle(
            "ArDocTitle",
            parent=base["Normal"],
            fontName=font,
            fontSize=15,
            leading=22,
            alignment=TA_CENTER,
            textColor=NAVY,
            spaceBefore=4,
            spaceAfter=2,
        ),
        "doc_sub": ParagraphStyle(
            "ArDocSub",
            parent=base["Normal"],
            fontName=font,
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
            textColor=GOLD,
            spaceAfter=6,
        ),
        "h": ParagraphStyle(
            "ArH",
            parent=base["Normal"],
            fontName=font,
            fontSize=11,
            leading=16,
            alignment=TA_RIGHT,
            textColor=NAVY,
            spaceBefore=6,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "ArBody",
            parent=base["Normal"],
            fontName=font,
            fontSize=9.5,
            leading=14,
            alignment=TA_RIGHT,
            textColor=SLATE,
        ),
        "meta_label": ParagraphStyle(
            "ArMetaLabel",
            parent=base["Normal"],
            fontName=font,
            fontSize=8.5,
            leading=12,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#64748b"),
        ),
        "meta_value": ParagraphStyle(
            "ArMetaValue",
            parent=base["Normal"],
            fontName=font,
            fontSize=9.5,
            leading=13,
            alignment=TA_RIGHT,
            textColor=NAVY,
        ),
        "cell": ParagraphStyle(
            "ArCell",
            parent=base["Normal"],
            fontName=font,
            fontSize=8,
            leading=11,
            alignment=TA_RIGHT,
        ),
        "cell_head": ParagraphStyle(
            "ArCellHead",
            parent=base["Normal"],
            fontName=font,
            fontSize=8,
            leading=11,
            alignment=TA_RIGHT,
            textColor=WHITE,
        ),
        "footer": ParagraphStyle(
            "ArFooter",
            parent=base["Normal"],
            fontName=font,
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#64748b"),
        ),
        "sign": ParagraphStyle(
            "ArSign",
            parent=base["Normal"],
            fontName=font,
            fontSize=9,
            leading=12,
            alignment=TA_CENTER,
            textColor=NAVY,
        ),
    }


class _ColorBar(Flowable):
    """Thin accent strip under the letterhead."""

    def __init__(self, width, height=2.2 * mm, color=GOLD_SOFT):
        super().__init__()
        self.width = width
        self.height = height
        self._color = color

    def draw(self):
        self.canv.setFillColor(self._color)
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)


def _letterhead(styles, *, org_line: str = "نظام إدارة العمليات التشغيلية") -> list:
    """Official navy header band + gold accent."""
    page_w = A4[0] - 2.4 * cm
    brand = Table(
        [
            [Paragraph(_ar("عمليات الفرش"), styles["brand"])],
            [Paragraph(_ar(org_line), styles["brand_sub"])],
            [Paragraph(_ar("المملكة العربية السعودية"), styles["brand_sub"])],
        ],
        colWidths=[page_w],
    )
    brand.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("TOPPADDING", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
                ("TOPPADDING", (0, 1), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -2), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    return [brand, _ColorBar(page_w), Spacer(1, 0.35 * cm)]


def _doc_heading(styles, title: str, subtitle: str, ref: str, dated: str) -> list:
    page_w = A4[0] - 2.4 * cm
    flow = [
        Paragraph(_ar(title), styles["doc_title"]),
        Paragraph(_ar(subtitle), styles["doc_sub"]),
    ]
    ref_row = Table(
        [
            [
                Paragraph(f"{_ar(dated)}  :{_ar('التاريخ')}", styles["meta_value"]),
                Paragraph(f"{_ar(ref)}  :{_ar('الرقم المرجعي')}", styles["meta_value"]),
            ]
        ],
        colWidths=[page_w / 2, page_w / 2],
    )
    ref_row.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), META_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, GOLD_SOFT),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    flow.append(ref_row)
    flow.append(Spacer(1, 0.35 * cm))
    return flow


def _meta_grid(rows: list[tuple[str, str]], styles) -> Table:
    """Two-column formal metadata grid (label : value)."""
    page_w = A4[0] - 2.4 * cm
    half = page_w / 2
    # Pack pairs into 2-column layout
    cells = []
    line = []
    for label, value in rows:
        cell = [
            Paragraph(_ar(label), styles["meta_label"]),
            Paragraph(_ar(value or "—"), styles["meta_value"]),
        ]
        inner = Table([[c] for c in cell], colWidths=[half - 8])
        inner.setStyle(
            TableStyle(
                [
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        line.append(inner)
        if len(line) == 2:
            cells.append(line)
            line = []
    if line:
        line.append("")
        cells.append(line)

    tbl = Table(cells, colWidths=[half, half])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), META_BG),
                ("BOX", (0, 0), (-1, -1), 0.7, NAVY_MID),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return tbl


def _data_table(headers: list[str], rows: list[list[str]], styles) -> Table:
    font = _ensure_font()
    head = [Paragraph(_ar(h), styles["cell_head"]) for h in headers]
    body = [[Paragraph(_ar(c), styles["cell"]) for c in row] for row in rows]
    data = [head] + (body or [[Paragraph(_ar("—"), styles["cell"])] * len(headers)])
    col_w = A4[0] - 2.4 * cm
    n = max(len(headers), 1)
    widths = [col_w / n] * n
    tbl = Table(data, colWidths=widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY_MID),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("BOX", (0, 0), (-1, -1), 0.8, NAVY),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [WHITE, ROW_ALT],
                ),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return tbl


def _signatures(styles, left_title: str, right_title: str) -> list:
    page_w = A4[0] - 2.4 * cm
    half = page_w / 2
    box = Table(
        [
            [
                Paragraph(_ar(left_title), styles["sign"]),
                Paragraph(_ar(right_title), styles["sign"]),
            ],
            [
                Paragraph(_ar("الاسم: ...................."), styles["body"]),
                Paragraph(_ar("الاسم: ...................."), styles["body"]),
            ],
            [
                Paragraph(_ar("التوقيع: .................."), styles["body"]),
                Paragraph(_ar("التوقيع: .................."), styles["body"]),
            ],
            [
                Paragraph(_ar("التاريخ: .................."), styles["body"]),
                Paragraph(_ar("التاريخ: .................."), styles["body"]),
            ],
        ],
        colWidths=[half, half],
    )
    box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (0, -1), 0.5, LINE),
                ("BOX", (1, 0), (1, -1), 0.5, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), META_BG),
            ]
        )
    )
    return [Spacer(1, 0.55 * cm), box]


def _footer_note(styles, text: str) -> list:
    return [
        Spacer(1, 0.35 * cm),
        HRFlowable(width="100%", thickness=0.6, color=GOLD_SOFT, spaceBefore=2, spaceAfter=6),
        Paragraph(_ar(text), styles["footer"]),
    ]


def _build(story, *, title: str = "عمليات الفرش") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.0 * cm,
        bottomMargin=1.2 * cm,
        title=title,
    )
    doc.build(story)
    return buf.getvalue()


def role_label(user) -> str:
    if not user:
        return "—"
    return getattr(user, "get_role_display", lambda: "")() or "—"


def build_return_batch_pdf(batch) -> tuple[bytes, str]:
    """Official return-file PDF with letterhead."""
    styles = _styles()
    items = list(batch.items.select_related("representative").all())
    created = timezone.localtime(batch.created_at).strftime("%Y-%m-%d %H:%M")
    creator = batch.created_by
    rep = batch.representative

    story: list = []
    story.extend(_letterhead(styles))
    story.extend(
        _doc_heading(
            styles,
            title="ملف مرتجع",
            subtitle="مستند تشغيلي رسمي",
            ref=batch.return_number,
            dated=created,
        )
    )
    story.append(_meta_grid(
        [
            ("الفرع", batch.branch),
            ("الحالة", batch.get_display_status_display()),
            ("عدد الأصناف", str(len(items))),
            ("المرسل", f"{creator.display_name} — {role_label(creator)}"),
            ("المندوب المسؤول", f"{rep.display_name} — {role_label(rep)}"),
            ("تاريخ الإنشاء", created),
        ],
        styles,
    ))
    story.append(Spacer(1, 0.35 * cm))
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
    story.append(_data_table(headers, rows, styles))
    story.extend(
        _footer_note(
            styles,
            "إجراء مطلوب من المندوب: متابعة الملف، تعميد/رفض الأصناف، والرد على النظام.",
        )
    )
    story.extend(_signatures(styles, "توقيع المندوب", "اعتماد العمليات"))

    filename = f"return_{batch.return_number.replace('#', '')}.pdf"
    return _build(story, title=f"مرتجع {batch.return_number}"), filename


def build_supply_orders_pdf(orders: list, *, actor) -> tuple[bytes, str]:
    """Official purchase / supply order PDF (أمر توريد / طلب شراء)."""
    styles = _styles()
    if not orders:
        raise ValueError("لا توجد طلبات توريد")
    first = orders[0]
    created = timezone.localtime(first.created_at).strftime("%Y-%m-%d %H:%M")
    rep = first.representative
    nums = [o.order_number for o in orders]
    ref = nums[0] if len(nums) == 1 else f"{nums[0]} … {nums[-1]}"
    status_label = (
        first.get_status_display()
        if len(orders) == 1
        else "مجموعة طلبات"
    )

    story: list = []
    story.extend(_letterhead(styles, org_line="إدارة المشتريات والتوريد التشغيلي"))
    story.extend(
        _doc_heading(
            styles,
            title="أمر توريد / طلب شراء",
            subtitle="مستند رسمي — يعتمد للمراجعة والتنفيذ",
            ref=ref,
            dated=created,
        )
    )
    story.append(
        _meta_grid(
            [
                ("نوع المستند", "أمر توريد / طلب شراء"),
                ("الحالة", status_label),
                ("عدد الأصناف", str(len(orders))),
                ("أرقام الطلبات", "، ".join(nums)),
                ("طالب التوريد", f"{actor.display_name} — {role_label(actor)}"),
                ("المندوب المسؤول", f"{rep.display_name} — {role_label(rep)}"),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph(_ar("بيان الأصناف المطلوبة"), styles["h"]))
    headers = [
        "ملاحظات",
        "التاريخ المتوقع",
        "الكمية",
        "العبوة",
        "الوحدة",
        "رقم الصنف",
        "الصنف",
        "رقم الطلب",
    ]
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
    story.append(_data_table(headers, rows, styles))
    story.extend(
        _footer_note(
            styles,
            "هذا المستند صادر آلياً من نظام عمليات الفرش ويُعدّ طلباً رسمياً للتوريد بعد الاعتماد.",
        )
    )
    story.extend(_signatures(styles, "توقيع طالب الشراء", "اعتماد أمر التوريد"))

    filename = f"purchase_order_{nums[0].replace('#', '')}.pdf"
    if len(nums) > 1:
        filename = f"purchase_order_batch_{len(nums)}.pdf"
    return _build(story, title=f"أمر توريد {ref}"), filename
