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

# Align with UI: navy ink + sage accent
NAVY = colors.HexColor("#0f2744")
NAVY_MID = colors.HexColor("#1a3a55")
ACCENT = colors.HexColor("#145c4c")
GOLD = colors.HexColor("#b45309")
LINE = colors.HexColor("#c5d2cb")
SLATE = colors.HexColor("#3d524a")
META_BG = colors.HexColor("#f4f7f5")
ROW_ALT = colors.HexColor("#f3f7f5")
WHITE = colors.white


def _ensure_font() -> str:
    global _FONT_REGISTERED
    if not _FONT_REGISTERED and FONT_PATH.exists():
        pdfmetrics.registerFont(TTFont(_FONT_NAME, str(FONT_PATH)))
        _FONT_REGISTERED = True
    return _FONT_NAME if _FONT_REGISTERED else "Helvetica"


def _ar(text) -> str:
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
            "ArBrand", parent=base["Normal"], fontName=font,
            fontSize=16, leading=22, alignment=TA_CENTER, textColor=WHITE,
        ),
        "brand_sub": ParagraphStyle(
            "ArBrandSub", parent=base["Normal"], fontName=font,
            fontSize=8.5, leading=12, alignment=TA_CENTER,
            textColor=colors.HexColor("#d7e8df"),
        ),
        "doc_title": ParagraphStyle(
            "ArDocTitle", parent=base["Normal"], fontName=font,
            fontSize=14, leading=20, alignment=TA_CENTER, textColor=NAVY,
            spaceBefore=2, spaceAfter=2,
        ),
        "doc_sub": ParagraphStyle(
            "ArDocSub", parent=base["Normal"], fontName=font,
            fontSize=9, leading=13, alignment=TA_CENTER, textColor=ACCENT,
            spaceAfter=8,
        ),
        "h": ParagraphStyle(
            "ArH", parent=base["Normal"], fontName=font,
            fontSize=10.5, leading=15, alignment=TA_RIGHT, textColor=NAVY,
            spaceBefore=8, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "ArBody", parent=base["Normal"], fontName=font,
            fontSize=9, leading=13, alignment=TA_RIGHT, textColor=SLATE,
        ),
        "meta_label": ParagraphStyle(
            "ArMetaLabel", parent=base["Normal"], fontName=font,
            fontSize=8, leading=11, alignment=TA_RIGHT,
            textColor=colors.HexColor("#5a6f66"),
        ),
        "meta_value": ParagraphStyle(
            "ArMetaValue", parent=base["Normal"], fontName=font,
            fontSize=9, leading=12, alignment=TA_RIGHT, textColor=NAVY,
        ),
        "cell": ParagraphStyle(
            "ArCell", parent=base["Normal"], fontName=font,
            fontSize=8, leading=11, alignment=TA_RIGHT,
        ),
        "cell_head": ParagraphStyle(
            "ArCellHead", parent=base["Normal"], fontName=font,
            fontSize=8, leading=11, alignment=TA_RIGHT, textColor=WHITE,
        ),
        "footer": ParagraphStyle(
            "ArFooter", parent=base["Normal"], fontName=font,
            fontSize=8, leading=11, alignment=TA_CENTER,
            textColor=colors.HexColor("#5a6f66"),
        ),
        "sign": ParagraphStyle(
            "ArSign", parent=base["Normal"], fontName=font,
            fontSize=9, leading=12, alignment=TA_CENTER, textColor=NAVY,
        ),
    }


class _AccentLine(Flowable):
    def __init__(self, width, height=1.6 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        self.canv.setFillColor(ACCENT)
        self.canv.rect(0, 0, self.width * 0.72, self.height, fill=1, stroke=0)
        self.canv.setFillColor(GOLD)
        self.canv.rect(self.width * 0.72, 0, self.width * 0.28, self.height, fill=1, stroke=0)


def _letterhead(styles, *, org_line: str = "بوابة العمليات التشغيلية") -> list:
    """Simplified professional letterhead — brand + thin accent only."""
    page_w = A4[0] - 2.4 * cm
    brand = Table(
        [
            [Paragraph(_ar("عمليات الفرش"), styles["brand"])],
            [Paragraph(_ar(org_line), styles["brand_sub"])],
        ],
        colWidths=[page_w],
    )
    brand.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("TOPPADDING", (0, 0), (-1, 0), 11),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
                ("TOPPADDING", (0, 1), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [brand, _AccentLine(page_w), Spacer(1, 0.4 * cm)]


def _doc_heading(styles, title: str, subtitle: str, ref: str, dated: str) -> list:
    page_w = A4[0] - 2.4 * cm
    flow = [
        Paragraph(_ar(title), styles["doc_title"]),
        Paragraph(_ar(subtitle), styles["doc_sub"]),
    ]
    ref_row = Table(
        [[
            Paragraph(f"{_ar(dated)}  :{_ar('التاريخ')}", styles["meta_value"]),
            Paragraph(f"{_ar(ref)}  :{_ar('الرقم')}", styles["meta_value"]),
        ]],
        colWidths=[page_w / 2, page_w / 2],
    )
    ref_row.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), META_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    flow.append(ref_row)
    flow.append(Spacer(1, 0.3 * cm))
    return flow


def _meta_grid(rows: list[tuple[str, str]], styles) -> Table:
    page_w = A4[0] - 2.4 * cm
    half = page_w / 2
    cells, line = [], []
    for label, value in rows:
        inner = Table(
            [
                [Paragraph(_ar(label), styles["meta_label"])],
                [Paragraph(_ar(value or "—"), styles["meta_value"])],
            ],
            colWidths=[half - 8],
        )
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
                ("BOX", (0, 0), (-1, -1), 0.6, NAVY_MID),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
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
    tbl = Table(data, colWidths=[col_w / n] * n, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("BOX", (0, 0), (-1, -1), 0.7, NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ROW_ALT]),
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
        ],
        colWidths=[half, half],
    )
    box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (0, -1), 0.45, LINE),
                ("BOX", (1, 0), (1, -1), 0.45, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), META_BG),
            ]
        )
    )
    return [Spacer(1, 0.5 * cm), box]


def _footer_note(styles, text: str) -> list:
    return [
        Spacer(1, 0.3 * cm),
        HRFlowable(width="100%", thickness=0.5, color=LINE, spaceBefore=2, spaceAfter=6),
        Paragraph(_ar(text), styles["footer"]),
    ]


def _build(story, *, title: str = "عمليات الفرش") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=1.2 * cm, leftMargin=1.2 * cm,
        topMargin=1.0 * cm, bottomMargin=1.2 * cm,
        title=title,
    )
    doc.build(story)
    return buf.getvalue()


def role_label(user) -> str:
    if not user:
        return "—"
    return getattr(user, "get_role_display", lambda: "")() or "—"


def build_return_batch_pdf(batch) -> tuple[bytes, str]:
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
    story.append(
        _meta_grid(
            [
                ("الفرع", batch.branch),
                ("الحالة", batch.get_display_status_display()),
                ("عدد الأصناف", str(len(items))),
                ("المرسل", f"{creator.display_name} — {role_label(creator)}"),
                ("المندوب", f"{rep.display_name} — {role_label(rep)}"),
                ("تاريخ الإنشاء", created),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(_ar("تفاصيل الأصناف"), styles["h"]))
    headers = ["السبب", "النوع", "الكمية", "العبوة", "الوحدة", "الاسم", "رقم الصنف", "#"]
    rows = [
        [
            (it.reason or "")[:80],
            it.get_return_type_display(),
            str(it.quantity),
            it.package or "—",
            it.unit or "—",
            it.item_name,
            it.item_number or "—",
            str(i),
        ]
        for i, it in enumerate(items, 1)
    ]
    story.append(_data_table(headers, rows, styles))
    story.extend(
        _footer_note(
            styles,
            "المطلوب من المندوب: مراجعة الأصناف، التعميد أو الرفض، والرد عبر النظام.",
        )
    )
    story.extend(_signatures(styles, "توقيع المندوب", "اعتماد العمليات"))
    filename = f"return_{batch.return_number.replace('#', '')}.pdf"
    return _build(story, title=f"مرتجع {batch.return_number}"), filename


def build_supply_orders_pdf(orders: list, *, actor) -> tuple[bytes, str]:
    styles = _styles()
    if not orders:
        raise ValueError("لا توجد طلبات توريد")
    first = orders[0]
    created = timezone.localtime(first.created_at).strftime("%Y-%m-%d %H:%M")
    rep = first.representative
    nums = [o.order_number for o in orders]
    batch_ref = getattr(first, "batch_number", "") or ""
    ref = batch_ref or (nums[0] if len(nums) == 1 else f"{nums[0]} … {nums[-1]}")
    status_label = first.get_status_display() if len(orders) == 1 else "مجموعة طلبات"

    story: list = []
    story.extend(_letterhead(styles, org_line="إدارة المشتريات والتوريد"))
    story.extend(
        _doc_heading(
            styles,
            title="أمر توريد / طلب شراء",
            subtitle="مستند رسمي مبسّط للاعتماد والتنفيذ",
            ref=ref,
            dated=created,
        )
    )
    story.append(
        _meta_grid(
            [
                ("نوع المستند", "أمر توريد"),
                ("الحالة", status_label),
                ("عدد الأصناف", str(len(orders))),
                ("أرقام الطلبات", "، ".join(nums)),
                ("طالب التوريد", f"{actor.display_name} — {role_label(actor)}"),
                ("المندوب", f"{rep.display_name} — {role_label(rep)}"),
                ("الفرع", getattr(first, "branch", "") or "—"),
                ("المورد", getattr(first, "supplier", "") or "—"),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(_ar("بيان الأصناف"), styles["h"]))
    headers = ["ملاحظات", "الإجمالي", "سعر", "كمية", "وحدة", "الصنف", "رقم", "طلب"]
    rows = []
    grand_total = 0
    for o in orders:
        line_total = float(o.quantity) * float(o.unit_price or 0)
        grand_total += line_total
        rows.append(
            [
                (o.notes or "")[:50] or "—",
                f"{line_total:.2f}",
                f"{o.unit_price:.2f}",
                str(o.quantity),
                o.unit or "—",
                o.item_name,
                o.item_number or "—",
                o.order_number,
            ]
        )
    story.append(_data_table(headers, rows, styles))
    story.append(Spacer(1, 0.25 * cm))
    total_tbl = Table(
        [[Paragraph(_ar(f"الإجمالي الكلي: {grand_total:.2f}"), styles["meta_value"])]],
        colWidths=[A4[0] - 2.4 * cm],
    )
    total_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), META_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, NAVY_MID),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(total_tbl)
    story.extend(
        _footer_note(
            styles,
            "صادر آلياً من نظام عمليات الفرش — يُعتمد بعد المراجعة والتوقيع.",
        )
    )
    story.extend(_signatures(styles, "توقيع طالب الشراء", "اعتماد أمر التوريد"))
    filename = f"purchase_order_{nums[0].replace('#', '')}.pdf"
    if len(nums) > 1:
        filename = f"purchase_order_batch_{len(nums)}.pdf"
    return _build(story, title=f"أمر توريد {ref}"), filename


def build_daily_orders_pdf(orders: list, *, actor=None) -> tuple[bytes, str]:
    """PDF لملف طلبية يومية (صنف أو أكثر) — بنفس أسلوب المرتجعات."""
    styles = _styles()
    if not orders:
        raise ValueError("لا توجد طلبيات")
    first = orders[0]
    created = timezone.localtime(first.created_at).strftime("%Y-%m-%d %H:%M")
    rep = first.representative
    actor = actor or first.reviewed_by or first.created_by
    batch_ref = first.batch_number or first.order_number
    status_label = (
        first.get_status_display()
        if len({o.status for o in orders}) == 1
        else "متعدد"
    )

    story: list = []
    story.extend(_letterhead(styles, org_line="إدارة المشتريات — الطلبيات اليومية"))
    story.extend(
        _doc_heading(
            styles,
            title="طلب شراء يومي",
            subtitle="مستند رسمي للمورد بعد الاعتماد",
            ref=batch_ref,
            dated=created,
        )
    )
    story.append(
        _meta_grid(
            [
                ("رقم الملف", batch_ref),
                ("تاريخ الطلبية", first.order_date.isoformat()),
                ("الفرع", first.branch or "—"),
                ("المورد", first.supplier or "—"),
                ("المندوب", f"{rep.display_name} — {role_label(rep)}"),
                ("المعتمد / المرسل", f"{actor.display_name} — {role_label(actor)}" if actor else "—"),
                ("عدد الأصناف", str(len(orders))),
                ("الحالة", status_label),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(_ar("بيان الأصناف"), styles["h"]))
    headers = ["الكمية", "العبوة", "اسم الصنف", "رقم الصنف", "#"]
    rows = []
    for i, o in enumerate(orders, 1):
        rows.append(
            [
                str(o.quantity),
                o.package or "—",
                o.item_name,
                o.item_number or "—",
                str(i),
            ]
        )
    story.append(_data_table(headers, rows, styles))
    story.extend(
        _footer_note(
            styles,
            "صادر آلياً من نظام عمليات الفرش بعد اعتماد الطلبية — يُرسل للمورد عبر واتساب.",
        )
    )
    story.extend(_signatures(styles, "توقيع المندوب", "اعتماد المشتريات"))
    safe_ref = str(batch_ref).replace("#", "").replace("/", "-")
    filename = f"daily_order_{safe_ref}.pdf"
    return _build(story, title=f"طلبية {batch_ref}"), filename


def build_offers_batch_pdf(items: list, *, actor=None) -> tuple[bytes, str]:
    """PDF لملف أصناف العروض."""
    styles = _styles()
    if not items:
        raise ValueError("لا توجد أصناف عروض")
    first = items[0]
    actor = actor or first.created_by
    created = timezone.localtime(first.created_at).strftime("%Y-%m-%d %H:%M")
    batch_ref = first.batch_number or f"#OFF-{first.pk}"

    story: list = []
    story.extend(_letterhead(styles, org_line="إدارة المشتريات — أصناف العروض"))
    story.extend(
        _doc_heading(
            styles,
            title="ملف أصناف العروض",
            subtitle="بيان أصناف العرض",
            ref=batch_ref,
            dated=created,
        )
    )
    rep = getattr(first, "representative", None) or first.created_by
    story.append(
        _meta_grid(
            [
                ("رقم الملف", batch_ref),
                ("عدد الأصناف", str(len(items))),
                ("المندوب", f"{rep.display_name} — {role_label(rep)}" if rep else "—"),
                ("أنشئ بواسطة", f"{first.created_by.display_name} — {role_label(first.created_by)}"),
                ("المُصدِر", f"{actor.display_name} — {role_label(actor)}" if actor else "—"),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(_ar("بيان الأصناف"), styles["h"]))
    headers = ["العبوة", "الكمية", "اسم الصنف", "رقم الصنف", "#"]
    rows = []
    for i, o in enumerate(items, 1):
        rows.append(
            [
                o.package or "—",
                str(o.quantity),
                o.item_name,
                o.item_number or "—",
                str(i),
            ]
        )
    story.append(_data_table(headers, rows, styles))
    story.extend(
        _footer_note(
            styles,
            "صادر آلياً من نظام عمليات الفرش — ملف أصناف العروض.",
        )
    )
    story.extend(_signatures(styles, "توقيع المندوب", "اعتماد العروض"))
    safe_ref = str(batch_ref).replace("#", "").replace("/", "-")
    filename = f"offers_{safe_ref}.pdf"
    return _build(story, title=f"عروض {batch_ref}"), filename


def build_distribution_batch_pdf(rows: list, *, actor=None) -> tuple[bytes, str]:
    styles = _styles()
    if not rows:
        raise ValueError("لا توجد سجلات توزيع")
    first = rows[0]
    actor = actor or first.created_by
    created = timezone.localtime(first.created_at).strftime("%Y-%m-%d %H:%M")
    batch_ref = first.batch_number or f"DIST-{first.pk}"
    dist_date = first.distribution_date.strftime("%Y/%m/%d")

    story: list = []
    story.extend(_letterhead(styles, org_line="إدارة التوريد — التوزيع اليومي"))
    story.extend(
        _doc_heading(
            styles,
            title="ملف توزيع توريد يومي",
            subtitle="مستند تشغيلي",
            ref=batch_ref,
            dated=created,
        )
    )
    story.append(
        _meta_grid(
            [
                ("رقم الملف", batch_ref),
                ("تاريخ التوزيع", dist_date),
                ("عدد الأصناف", str(len(rows))),
                ("المرسل", f"{actor.display_name} — {role_label(actor)}" if actor else "—"),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(_ar("تفاصيل التوزيع"), styles["h"]))
    headers = ["الكمية", "الفرع", "اسم الصنف", "رقم الصنف", "#"]
    body = [
        [
            str(r.quantity),
            r.branch,
            r.item_name,
            r.item_number or "—",
            str(i),
        ]
        for i, r in enumerate(rows, 1)
    ]
    story.append(_data_table(headers, body, styles))
    story.extend(_footer_note(styles, "صادر من نظام عمليات الفرش — للمحاسب والعمليات والمستلم."))
    filename = f"distribution_{str(batch_ref).replace('#', '')}.pdf"
    return _build(story, title=f"توزيع {batch_ref}"), filename


def build_variance_batch_pdf(rows: list, *, actor=None) -> tuple[bytes, str]:
    styles = _styles()
    if not rows:
        raise ValueError("لا توجد سجلات")
    first = rows[0]
    actor = actor or first.created_by
    created = timezone.localtime(first.created_at).strftime("%Y-%m-%d %H:%M")
    batch_ref = first.batch_number or f"VAR-{first.pk}"
    rec_date = first.record_date.strftime("%Y/%m/%d")

    story: list = []
    story.extend(_letterhead(styles, org_line="إدارة التوريد — نقص وزيادة"))
    story.extend(
        _doc_heading(
            styles,
            title="ملف نقص / زيادة توزيع",
            subtitle="مستند تشغيلي",
            ref=batch_ref,
            dated=created,
        )
    )
    story.append(
        _meta_grid(
            [
                ("رقم الملف", batch_ref),
                ("التاريخ", rec_date),
                ("عدد السجلات", str(len(rows))),
                ("المرسل", f"{actor.display_name} — {role_label(actor)}" if actor else "—"),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(_ar("التفاصيل"), styles["h"]))
    headers = ["المورد", "الفرع", "الكمية", "اسم الصنف", "رقم الصنف", "النوع", "#"]
    body = [
        [
            r.supplier,
            r.branch,
            str(r.quantity),
            r.item_name,
            r.item_number or "—",
            r.get_variance_type_display(),
            str(i),
        ]
        for i, r in enumerate(rows, 1)
    ]
    story.append(_data_table(headers, body, styles))
    story.extend(_footer_note(styles, "صادر من نظام عمليات الفرش."))
    filename = f"variance_{str(batch_ref).replace('#', '')}.pdf"
    return _build(story, title=f"نقص/زيادة {batch_ref}"), filename


def build_task_pdf(task, *, actor=None) -> tuple[bytes, str]:
    styles = _styles()
    actor = actor or task.created_by
    created = timezone.localtime(task.created_at).strftime("%Y-%m-%d %H:%M")
    assignee = task.assigned_to

    story: list = []
    story.extend(_letterhead(styles, org_line="إدارة المهام الميدانية"))
    story.extend(
        _doc_heading(
            styles,
            title="مهمة تشغيلية",
            subtitle="مستند مهمة",
            ref=f"#{task.pk}",
            dated=created,
        )
    )
    story.append(
        _meta_grid(
            [
                ("المهمة", task.title),
                ("الفرع", task.branch or "—"),
                ("الأولوية", task.get_priority_display()),
                ("المُسند إليه", assignee.display_name if assignee else "—"),
                ("الحالة", task.get_status_display()),
                ("المرسل", f"{actor.display_name} — {role_label(actor)}" if actor else "—"),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(_ar("التفاصيل"), styles["h"]))
    details = (task.visit_details or task.description or "—")[:800]
    story.append(Paragraph(_ar(details), styles["body"]))
    if task.response_text:
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(_ar("الرد"), styles["h"]))
        story.append(Paragraph(_ar(task.response_text[:800]), styles["body"]))
    story.extend(_footer_note(styles, "صادر من نظام عمليات الفرش."))
    safe = str(task.pk)
    filename = f"task_{safe}.pdf"
    return _build(story, title=f"مهمة {task.title}"), filename
