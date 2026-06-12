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
GREEN      = colors.HexColor("#1f6f5c")
GOLD       = colors.HexColor("#bd8f33")
PAPER      = colors.HexColor("#f6f4ef")
INK        = colors.HexColor("#1a1a18")
INK_3      = colors.HexColor("#6b6b65")
INK_4      = colors.HexColor("#9e9e96")
LINE       = colors.HexColor("#e0ddd6")
GREEN_SOFT = colors.HexColor("#e8f2ef")
GREEN_HDR  = colors.HexColor("#e0eeea")
WHITE      = colors.white

W, H = A4
MARGIN = 18 * mm
INNER  = W - 2 * MARGIN          # usable width


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("→", "->").replace("—", "-").strip()


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    from xml.sax.saxutils import escape
    return Paragraph(escape(_clean(text)).replace("\n", "<br/>"), style)


def _map_label(stop: Place) -> str:
    url = stop.google_maps_url or stop.map_url or (
        f"https://www.google.com/maps/search/?api=1&query={stop.latitude},{stop.longitude}"
    )
    # shorten to first 60 chars so it fits in a cell
    short = url if len(url) <= 60 else url[:57] + "..."
    return short


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "CoverTitle": ParagraphStyle("CoverTitle", parent=base["Title"],
            fontName="Helvetica-Bold", fontSize=28, leading=32,
            textColor=WHITE, spaceAfter=4),
        "CoverSub": ParagraphStyle("CoverSub", parent=base["Normal"],
            fontName="Helvetica", fontSize=12, leading=15,
            textColor=colors.HexColor("#d4ede8"), spaceAfter=3),
        "CoverMeta": ParagraphStyle("CoverMeta", parent=base["Normal"],
            fontName="Helvetica", fontSize=9.5, leading=12,
            textColor=colors.HexColor("#a8cfc7")),
        "DayBadge": ParagraphStyle("DayBadge", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=7, textColor=WHITE),
        "DayTitle": ParagraphStyle("DayTitle", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=INK),
        "DaySummary": ParagraphStyle("DaySummary", parent=base["Normal"],
            fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK_3),
        "ColHdr": ParagraphStyle("ColHdr", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=8, leading=10,
            textColor=WHITE),
        "Cell": ParagraphStyle("Cell", parent=base["Normal"],
            fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK),
        "CellSm": ParagraphStyle("CellSm", parent=base["Normal"],
            fontName="Helvetica", fontSize=7.5, leading=10, textColor=INK_3),
        "CellBold": ParagraphStyle("CellBold", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=INK),
        "Tip": ParagraphStyle("Tip", parent=base["Normal"],
            fontName="Helvetica-Oblique", fontSize=8, leading=10,
            textColor=GREEN),
        "Link": ParagraphStyle("Link", parent=base["Normal"],
            fontName="Helvetica", fontSize=7, leading=9,
            textColor=colors.HexColor("#476782")),
        "NoteItem": ParagraphStyle("NoteItem", parent=base["Normal"],
            fontName="Helvetica", fontSize=8.5, leading=12, textColor=INK_3,
            leftIndent=6, spaceAfter=2),
        "SectionTitle": ParagraphStyle("SectionTitle", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=10, leading=13,
            textColor=GREEN, spaceBefore=4, spaceAfter=3),
    }


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(INK_4)
    canvas.drawString(MARGIN, 9 * mm, "TravelBuddy — AI Travel Planner")
    canvas.drawRightString(W - MARGIN, 9 * mm, f"Page {document.page}")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.3)
    canvas.line(MARGIN, 12 * mm, W - MARGIN, 12 * mm)
    canvas.restoreState()


def _cover(itinerary: Itinerary, styles: dict) -> list:
    elements = []

    # Green title block
    title_tbl = Table([[_p(itinerary.title, styles["CoverTitle"])]],
                      colWidths=[INNER])
    title_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), GREEN),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ("TOPPADDING",    (0, 0), (-1, -1), 48),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
    ]))
    elements.append(title_tbl)

    meta_rows = []
    if itinerary.destination:
        meta_rows.append([_p(f"Destination  ·  {itinerary.destination}", styles["CoverSub"])])
    if itinerary.days:
        total = sum(len(d.stops) for d in itinerary.days)
        meta_rows.append([_p(f"{len(itinerary.days)}-day itinerary  ·  {total} stops", styles["CoverSub"])])
    if itinerary.themes:
        meta_rows.append([_p("  ·  ".join(t.title() for t in itinerary.themes[:4]), styles["CoverMeta"])])
    if meta_rows:
        mt = Table(meta_rows, colWidths=[INNER])
        mt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), GREEN),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ]))
        elements.append(mt)

    if itinerary.summary:
        st = Table([[_p(itinerary.summary, styles["Cell"])]],
                   colWidths=[INNER])
        st.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), GREEN_SOFT),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("BOX",           (0, 0), (-1, -1), 0.5, GREEN),
        ]))
        elements.append(Spacer(1, 5 * mm))
        elements.append(st)

    elements.append(PageBreak())
    return elements


# ── Column widths for the itinerary table ─────────────────────────────────────
# #  | Place        | Category   | Rating | Why go / Local tip | Map
_COL_NUM  = 8  * mm
_COL_PLC  = 44 * mm
_COL_CAT  = 24 * mm
_COL_RATE = 20 * mm
_COL_WHY  = 50 * mm
_COL_MAP  = INNER - _COL_NUM - _COL_PLC - _COL_CAT - _COL_RATE - _COL_WHY  # ~28mm
_COL_W = [_COL_NUM, _COL_PLC, _COL_CAT, _COL_RATE, _COL_WHY, _COL_MAP]


def _rating_cell(stop: Place, styles: dict) -> Paragraph:
    parts = []
    if stop.google_rating:
        parts.append(f"★ {stop.google_rating:.1f}")
        if stop.google_user_rating_count:
            parts.append(f"({stop.google_user_rating_count:,})")
    price = stop.price_label or stop.google_price_label or ""
    if price:
        parts.append(price)
    return _p("\n".join(parts) if parts else "—", styles["CellSm"])


def _why_cell(stop: Place, styles: dict) -> Paragraph:
    lines = []
    if stop.reason:
        lines.append(stop.reason)
    tip = stop.local_tip or ""
    if tip and tip != "Use this as a candidate and verify current details before going.":
        lines.append(f"Tip: {tip}")
    return _p("\n".join(lines) if lines else "—", styles["Cell"])


def _day_table(day, styles: dict) -> Table:
    # Header row
    headers = ["#", "Place", "Category", "Rating", "Why go / Tip", "Map"]
    header_row = [_p(h, styles["ColHdr"]) for h in headers]

    rows: list[list] = [header_row]
    for idx, stop in enumerate(day.stops, start=1):
        num_cell = Table([[_p(str(idx), styles["ColHdr"])]], colWidths=[_COL_W[0]])
        num_cell.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), GREEN),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ]))

        time_note = stop.best_time or ""
        place_text = stop.name
        if time_note:
            place_text += f"\n{time_note}"

        hours = stop.open_status_label or ""

        rows.append([
            num_cell,
            _p(place_text, styles["CellBold"]),
            _p(f"{stop.category}\n{stop.neighborhood or stop.city}", styles["CellSm"]),
            _rating_cell(stop, styles),
            _why_cell(stop, styles),
            _p(_map_label(stop), styles["Link"]),
        ])
        # Hours sub-row if available
        if hours and not hours.startswith("Google Maps hours"):
            rows.append([
                "",
                _p(f"  {hours}", styles["CellSm"]),
                "", "", "", "",
            ])

    tbl = Table(rows, colWidths=_COL_W, repeatRows=1)

    row_count = len(rows)
    tbl.setStyle(TableStyle([
        # Header
        ("BACKGROUND",    (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 8),
        ("TOPPADDING",    (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        # All cells
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8.5),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        # Alternating row tint
        *[("BACKGROUND", (0, r), (-1, r), PAPER)
          for r in range(1, row_count, 2)],
        # Grid
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, LINE),
        ("BOX",           (0, 0), (-1, -1), 0.6, colors.HexColor("#c0bdb5")),
        # Number column centre
        ("ALIGN",         (0, 0), (0, -1), "CENTER"),
    ]))
    return tbl


def build_itinerary_pdf(itinerary: Itinerary) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=MARGIN,
        leftMargin=MARGIN,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=itinerary.title,
    )
    styles = _styles()
    story = _cover(itinerary, styles)

    day_sections = itinerary.days or [
        type("D", (), {"day": 1, "title": "Stops", "summary": "", "stops": itinerary.stops})()
    ]

    for day_idx, day in enumerate(day_sections):
        if day_idx:
            story.append(Spacer(1, 8 * mm))

        # Day badge
        badge = Table([[_p(f"DAY {day.day}", styles["DayBadge"])]],
                      colWidths=[16 * mm], rowHeights=[5.5 * mm])
        badge.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), GREEN),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(badge)
        story.append(Spacer(1, 2 * mm))
        story.append(_p(day.title or f"Day {day.day}", styles["DayTitle"]))
        if day.summary:
            story.append(_p(day.summary, styles["DaySummary"]))
        story.append(Spacer(1, 3 * mm))
        story.append(_day_table(day, styles))

    # Notes
    all_notes = [*(itinerary.avoidance_notes or []), *(itinerary.practical_notes or [])]
    if all_notes:
        story.append(Spacer(1, 6 * mm))
        story.append(HRFlowable(width="100%", thickness=0.4, color=LINE))
        story.append(Spacer(1, 3 * mm))
        story.append(_p("Notes & Tips", styles["SectionTitle"]))
        for note in all_notes:
            story.append(_p(f"· {note}", styles["NoteItem"]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer.read()
