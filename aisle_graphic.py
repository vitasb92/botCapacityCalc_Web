from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from brand_palette import (
    BLUE,
    BLUE_DARK,
    BLUE_LIGHT,
    LOCUS_BLUE,
    NEUTRAL_LIGHT,
    NEUTRAL_MEDIUM,
    NEUTRAL_PALE,
    WHITE,
)


_TRAFFIC_SCENARIOS = (
    ("No-Pass (1-Way)", 1),
    ("Pass (2-Way)", 2),
    ("High-Density (3-Way)", 3),
)


def _font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _draw_wrapped(draw, text, xy, font, max_width, fill, line_gap=7):
    words = str(text).split()
    lines = []
    current_line = ""
    for word in words:
        candidate = f"{current_line} {word}".strip()
        if current_line and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current_line)
            current_line = word
        else:
            current_line = candidate
    if current_line:
        lines.append(current_line)

    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += draw.textbbox((x, y), line, font=font)[3] - y + line_gap
    return y


def _format_width(width_mm, metric):
    if metric:
        return f"{width_mm:,.1f} mm"
    return f"{width_mm / 25.4:,.2f} in"


def _draw_arrow(draw, x, y, width, direction, color):
    if direction > 0:
        draw.line((x, y, x + width - 18, y), fill=color, width=8)
        draw.polygon(
            [
                (x + width - 18, y - 11),
                (x + width, y),
                (x + width - 18, y + 11),
            ],
            fill=color,
        )
    else:
        draw.line((x + 18, y, x + width, y), fill=color, width=8)
        draw.polygon(
            [(x + 18, y - 11), (x, y), (x + 18, y + 11)],
            fill=color,
        )


def create_aisle_requirements_png(
    configuration_label,
    profile_label,
    robot_width_mm,
    scenarios,
    metric=False,
):
    scenario_by_label = {scenario["traffic_pattern"]: scenario for scenario in scenarios}
    expected_labels = {label for label, _ in _TRAFFIC_SCENARIOS}
    if set(scenario_by_label) != expected_labels:
        raise ValueError("Aisle graphic requires one result for each traffic pattern.")

    width, height = 1800, 990
    image = Image.new("RGB", (width, height), NEUTRAL_PALE)
    draw = ImageDraw.Draw(image)
    title_font = _font(42)
    heading_font = _font(28)
    body_font = _font(22)
    small_font = _font(18)
    label_font = _font(16)
    ink = BLUE_DARK
    muted = NEUTRAL_MEDIUM

    draw.rounded_rectangle(
        (36, 28, width - 36, height - 28),
        radius=28,
        fill=WHITE,
        outline=NEUTRAL_LIGHT,
        width=2,
    )
    draw.text((76, 62), "Aisle Width Requirements", font=title_font, fill=ink)

    panel_top, panel_bottom = 132, 292
    draw.rounded_rectangle(
        (76, panel_top, width - 76, panel_bottom),
        radius=20,
        fill=NEUTRAL_PALE,
    )
    draw.text((108, 158), "SELECTED BOT CONFIGURATION", font=label_font, fill=muted)
    _draw_wrapped(
        draw,
        configuration_label,
        (108, 188),
        heading_font,
        750,
        ink,
        line_gap=3,
    )
    _draw_wrapped(
        draw,
        profile_label,
        (900, 164),
        body_font,
        760,
        muted,
        line_gap=5,
    )
    draw.text(
        (900, 235),
        f"Robot / hardware width: {_format_width(robot_width_mm, True)}",
        font=small_font,
        fill=muted,
    )

    margin, gap = 76, 24
    card_top, card_bottom = 326, 886
    card_width = (width - 2 * margin - 2 * gap) // 3
    scenario_colors = (NEUTRAL_PALE, BLUE_LIGHT, NEUTRAL_LIGHT)
    for card_index, (traffic_label, lane_count) in enumerate(_TRAFFIC_SCENARIOS):
        x0 = margin + card_index * (card_width + gap)
        x1 = x0 + card_width
        scenario = scenario_by_label[traffic_label]
        draw.rounded_rectangle(
            (x0, card_top, x1, card_bottom),
            radius=20,
            fill=WHITE,
            outline=NEUTRAL_LIGHT,
            width=2,
        )
        draw.rounded_rectangle(
            (x0 + 1, card_top + 1, x1 - 1, card_top + 74),
            radius=20,
            fill=scenario_colors[card_index],
        )
        draw.text(
            (x0 + 24, card_top + 20),
            traffic_label,
            font=heading_font,
            fill=ink,
        )

        aisle_x0, aisle_x1 = x0 + 32, x1 - 32
        aisle_top, aisle_bottom = card_top + 112, card_top + 240
        draw.rounded_rectangle(
            (aisle_x0, aisle_top, aisle_x1, aisle_bottom),
            radius=14,
            fill=WHITE,
            outline=NEUTRAL_LIGHT,
            width=2,
        )
        lane_height = (aisle_bottom - aisle_top - 16) / lane_count
        for lane in range(lane_count):
            center_y = int(aisle_top + 8 + lane_height * (lane + 0.5))
            direction = 1 if lane % 2 == 0 else -1
            arrow_color = LOCUS_BLUE if direction > 0 else BLUE
            _draw_arrow(
                draw,
                aisle_x0 + 92,
                center_y,
                aisle_x1 - aisle_x0 - 120,
                direction,
                arrow_color,
            )
        draw.text(
            (aisle_x0 + 14, aisle_top + 10),
            "BOT",
            font=label_font,
            fill=muted,
        )
        draw.text(
            (aisle_x1 - 60, aisle_bottom - 30),
            "BOT",
            font=label_font,
            fill=muted,
        )

        draw.text(
            (x0 + 28, card_top + 266),
            "MINIMUM",
            font=label_font,
            fill=muted,
        )
        draw.text(
            (x0 + 28, card_top + 292),
            _format_width(scenario["minimum_width_mm"], metric),
            font=heading_font,
            fill=ink,
        )
        minimum_y = _draw_wrapped(
            draw,
            f"Limiting carton: {scenario['minimum_carton']}",
            (x0 + 28, card_top + 335),
            small_font,
            card_width - 56,
            muted,
            line_gap=5,
        )
        optimal_label_y = max(card_top + 410, minimum_y + 12)
        draw.text(
            (x0 + 28, optimal_label_y),
            "OPTIMAL",
            font=label_font,
            fill=BLUE_DARK,
        )
        draw.text(
            (x0 + 28, optimal_label_y + 26),
            _format_width(scenario["optimal_width_mm"], metric),
            font=heading_font,
            fill=ink,
        )
        _draw_wrapped(
            draw,
            f"Limiting carton: {scenario['optimal_carton']}",
            (x0 + 28, optimal_label_y + 69),
            small_font,
            card_width - 56,
            muted,
            line_gap=5,
        )

    footer = (
        "Planning estimate only. Confirm aisle dimensions with the robot manufacturer "
        "and facility safety/design teams."
    )
    draw.text((76, 914), footer, font=small_font, fill=muted)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
