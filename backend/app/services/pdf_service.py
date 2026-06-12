from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas.travel import Itinerary, Place

# Brand colours
GREEN = colors.HexColor("#1f6f5c")
GOLD = colors.HexColor("#bd8f33")
PAPER = colors.HexColor("#f6f4ef")
INK = colors.HexColor("#1a1a18")
INK_3 = colors.HexColor("#6b6b65")
INK_4 = colors.HexColor("#9e9e96")
LINE = colors.HexColor("#e0ddd6")
GREEN_SOFT = colors.HexColor("#e8f2ef")
WHITE = colors.white


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("→", "->").replace("—", "-").strip()


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    from xml.sax.saxutils import escape
    return Paragraph(escape(_clean(text)).replace("\n", "<br/>"), style)


def _map_url(stop: Place) -> str:
    return stop.google_maps_url or stop.map_url or (
        f"https://www.google.com/maps/search/?api=1&query={stop.latitude},{stop.longitude}"
    )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "CoverTitle": ParagraphStyle("CoverTitle", parent=base["Title"],
            fontName="Helvetica-Bold", fontSize=32, leading=36,
            textColor=WHITE, spaceAfter=6),
        "CoverSub": ParagraphStyle("CoverSub", parent=base["Normal"],
            fontName="Helvetica", fontSize=13, leading=16,
            textColor=colors.HexColor("#d4ede8"), spaceAfter=4),
        "CoverMeta": ParagraphStyle("CoverMeta", parent=base["Normal"],
            fontName="Helvetica", fontSize=10, leading=13,
            textColor=colors.HexColor("#a8cfc7")),
        "DayLabel": ParagraphStyle("DayLabel", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=7, leading=9,
            textColor=WHITE, spaceAfter=0),
        "DayTitle": ParagraphStyle("DayTitle", parent=base["Heading2"],
            fontName="Helvetica-Bold", fontSize=15, leading=18,
            textColor=INK, spaceBefore=0, spaceAfter=3),
        "DaySummary": ParagraphStyle("DaySummary", parent=base["Normal"],
            fontName="Helvetica", fontSize=9, leading=12,
            textColor=INK_3, spaceAfter=8),
        "StopNum": ParagraphStyle("StopNum", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=WHITE),
        "StopName": ParagraphStyle("StopName", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=11, leading=13, textColor=INK),
        "StopCat": ParagraphStyle("StopCat", parent=base["Normal"],
            fontName="Helvetica", fontSize=8, leading=10, textColor=INK_3),
        "Label": ParagraphStyle("Label", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=INK_3),
        "Body": ParagraphStyle("Body", parent=base["Normal"],
            fontName="Helvetica", fontSize=9, leading=12, textColor=INK),
        "Tip": ParagraphStyle("Tip", parent=base["Normal"],
            fontName="Helvetica-Oblique", fontSize=8.5, leading=11, textColor=colors.HexColor("#1f6f5c")),
        "Link": ParagraphStyle("Link", parent=base["Normal"],
            fontName="Helvetica", fontSize=8, leading=10,
            textColor=colors.HexColor("#476782"), wordWrap="CJK"),
        "NoteItem": ParagraphStyle("NoteItem", parent=base["Normal"],
            fontName="Helvetica", fontSize=9, leading=13, textColor=INK_3,
            leftIndent=8, spaceAfter=3),
        "SectionTitle": ParagraphStyle("SectionTitle", parent=base["Heading3"],
            fontName="Helvetica-Bold", fontSize=11, leading=14,
            textColor=GREEN, spaceBefore=6, spaceAfter=4),
    }


def _cover_page(itinerary: Itinerary, styles: dict) -> list:
    """Build a green cover page."""
    W, H = A4
    elements = []

    # Full-page green background drawn via canvas — we use a Table as a colour block
    cover_table = Table(
        [[_p(itinerary.title, styles["CoverTitle"])]],
        colWidths=[W - 40 * mm],
    )
    cover_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREEN),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 60),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    elements.append(cover_table)

    meta_rows = []
    if itinerary.destination:
        meta_rows.append([_p(f"Destination  ·  {itinerary.destination}", styles["CoverSub"])])
    if itinerary.days:
        meta_rows.append([_p(f"{len(itinerary.days)}-day itinerary  ·  {sum(len(d.stops) for d in itinerary.days)} stops", styles["CoverSub"])])
    if itinerary.themes:
        meta_rows.append([_p("  ·  ".join(t.title() for t in itinerary.themes[:4]), styles["CoverMeta"])])

    if meta_rows:
        meta_table = Table(meta_rows, colWidths=[W - 40 * mm])
        meta_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREEN),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(meta_table)

    # Summary block
    summary_table = Table(
        [[_p(itinerary.summary, styles["Body"])]],
        colWidths=[W - 40 * mm],
    )
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREEN_SOFT),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("BOX", (0, 0), (-1, -1), 0.5, GREEN),
    ]))
    elements.append(Spacer(1, 6 * mm))
    elements.append(summary_table)
    elements.append(PageBreak())
    return elements


def _stop_card(stop: Place, index: int, styles: dict) -> Table:
    rating = (
        f"★ {stop.google_rating:.1f}  ({stop.google_user_rating_count:,} reviews)"
        if stop.google_rating and stop.google_user_rating_count
        else ""
    )
    price = stop.price_label or stop.google_price_label or ""
    rating_price = "  ·  ".join(filter(None, [rating, price])) or "Not available"

    hours = stop.open_status_label or ""
    area = stop.neighborhood or stop.city or ""

    # Left number badge cell
    num_cell = Table(
        [[_p(str(index), styles["StopNum"])]],
        colWidths=[8 * mm], rowHeights=[8 * mm],
    )
    num_cell.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREEN),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))

    name_block = [
        [num_cell, _p(stop.name, styles["StopName"])],
        ["", _p(f"{stop.category}  ·  {area}" if area else stop.category, styles["StopCat"])],
    ]
    header_table = Table(name_block, colWidths=[10 * mm, 146 * mm])
    header_table.setStyle(TableStyle([
        ("SPAN", (0, 0), (0, 1)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    detail_rows = []
    if hours:
        detail_rows.append([_p("Hours", styles["Label"]), _p(hours, styles["Body"])])
    if rating_price:
        detail_rows.append([_p("Rating / Price", styles["Label"]), _p(rating_price, styles["Body"])])
    if stop.reason:
        detail_rows.append([_p("Why go", styles["Label"]), _p(stop.reason, styles["Body"])])
    if stop.local_tip and stop.local_tip != "Use this as a candidate and verify current details before going.":
        detail_rows.append([_p("Local tip", styles["Label"]), _p(stop.local_tip, styles["Tip"])])
    map_url = _map_url(stop)
    if map_url:
        detail_rows.append([_p("Map", styles["Label"]), _p("google.com/maps →  " + map_url[:80], styles["Link"])])

    detail_table = Table(detail_rows, colWidths=[24 * mm, 132 * mm])
    detail_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f5f3")),
    ]))

    outer = Table(
        [[header_table], [detail_table]],
        colWidths=[156 * mm],
    )
    outer.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -2), 0),
        ("BACKGROUND", (0, 0), (-1, 0), PAPER),
    ]))
    return outer


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(INK_4)
    canvas.drawString(20 * mm, 10 * mm, "TravelBuddy — AI Travel Planner")
    canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {document.page}")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 13 * mm, A4[0] - 20 * mm, 13 * mm)
    canvas.restoreState()


def build_itinerary_pdf(itinerary: Itinerary) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=itinerary.title,
    )
    styles = _styles()
    story = _cover_page(itinerary, styles)

    day_sections = itinerary.days or [
        type("FallbackDay", (), {
            "day": 1, "title": "Stops", "summary": "", "stops": itinerary.stops,
        })()
    ]

    for day_idx, day in enumerate(day_sections):
        if day_idx:
            story.append(PageBreak())

        # Day badge
        badge = Table(
            [[_p(f"DAY {day.day}", styles["DayLabel"])]],
            colWidths=[18 * mm], rowHeights=[6 * mm],
        )
        badge.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREEN),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(badge)
        story.append(Spacer(1, 3 * mm))
        story.append(_p(day.title or f"Day {day.day}", styles["DayTitle"]))
        if day.summary:
            story.append(_p(day.summary, styles["DaySummary"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=LINE, spaceAfter=6))

        for stop_idx, stop in enumerate(day.stops, start=1):
            story.append(_stop_card(stop, stop_idx, styles))
            story.append(Spacer(1, 4 * mm))

    # Notes
    all_notes = [*(itinerary.avoidance_notes or []), *(itinerary.practical_notes or [])]
    if all_notes:
        story.append(HRFlowable(width="100%", thickness=0.5, color=LINE, spaceBefore=4, spaceAfter=6))
        story.append(_p("Notes & Tips", styles["SectionTitle"]))
        for note in all_notes:
            story.append(_p(f"· {note}", styles["NoteItem"]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer.read()
