#!/usr/bin/env python3
"""Patch diagram(2).drawio layout: fix tier-title/card overlaps, unify card styling,
shorten text, and reroute clustered/through-card edges. ID-preserving patch, not a rebuild.
"""
import xml.etree.ElementTree as ET
import copy

SRC = "diagram(2).drawio"
DST = "diagram(2).fixed.drawio"

PAD = 12
GAP = 16
CARD_W = 230
CARD_H = 72
CARD_W_N = 210
TITLE_STRIP_H = 28
CONTENT_TOP = TITLE_STRIP_H + 8  # 36

TIER_ACCENT = {
    "edge_security": "#8593A3",
    "observability_tier": "#8593A3",
    "frontend_tier": "#0891B2",
    "api_gateway_tier": "#0D9488",
    "application_tier": "#7C3AED",
    "ai_ml_tier": "#4F46E5",
    "data_tier": "#059669",
    "messaging_tier": "#E11D48",
}

TIER_GEOM = {
    "edge_security": (40, 98, 240, 316),
    "observability_tier": (40, 440, 240, 502),
    "frontend_tier": (324, 98, 1019, 158),
    "api_gateway_tier": (324, 302, 1019, 158),
    "application_tier": (324, 506, 1019, 158),
    "ai_ml_tier": (324, 710, 1019, 158),
    "data_tier": (324, 914, 1019, 158),
    "messaging_tier": (324, 1118, 1019, 158),
}

WIDE_ROWS = {
    "frontend_tier": ["cloudfront", "s3_frontend"],
    "api_gateway_tier": ["cognito_user_pool", "api_gateway", "alb"],
    "application_tier": ["ecs_fargate_api", "ecs_fargate_ai", "ecs_fargate_scheduler", "lambda_webhook"],
    "ai_ml_tier": ["bedrock_claude", "transcribe", "comprehend"],
    "data_tier": ["aurora_postgres", "elasticache_redis", "s3_audio_store"],
    "messaging_tier": ["step_functions", "sqs_queue", "sns_topic"],
}

# (id, height) stacks for narrow single-column tiers
NARROW_COLUMNS = {
    "edge_security": [("hr_users", 44), ("store_managers", 44), ("candidates", 44), ("waf", 72)],
    "observability_tier": [("cloudtrail", 72), ("cloudwatch", 72), ("xray", 72), ("guardduty", 72), ("kms_cmk", 72)],
}

ACTOR_BOXES = {"hr_users", "store_managers", "candidates"}

TRIMMED_TEXT = {
    "aurora_postgres": ("Aurora PostgreSQL", "Serverless v2 &middot; Multi-AZ"),
    "elasticache_redis": ("ElastiCache Redis", "Sessions &amp; rate limiting"),
    "bedrock_claude": ("Bedrock Claude Sonnet", "LLM inference"),
    "comprehend": ("Amazon Comprehend", "Sentiment &amp; entities"),
    "ecs_fargate_api": ("ECS Fargate &mdash; API Service", "Node.js 20 &middot; REST backend"),
    "ecs_fargate_scheduler": ("ECS Fargate &mdash; Scheduler", "Python 3.12 &middot; cron jobs"),
    "cloudtrail": ("AWS CloudTrail", "API audit logging"),
    "xray": ("AWS X-Ray", "Distributed tracing"),
    "guardduty": ("Amazon GuardDuty", "Threat detection"),
    "s3_audio_store": ("S3 &mdash; Audio &amp; Resumes", "SSE-KMS encrypted"),
    "step_functions": ("AWS Step Functions", "AI pipeline orchestration"),
    "cloudfront": ("Amazon CloudFront", "CDN + HTTPS"),
    "cognito_user_pool": ("Cognito User Pool", "HR role-based auth"),
    "api_gateway": ("Amazon API Gateway", "REST API &middot; usage plans"),
    "alb": ("Application Load Balancer", "TLS 1.2 termination"),
    "transcribe": ("Amazon Transcribe", "Speech-to-text + diarization"),
    "sqs_queue": ("Amazon SQS", "Standard queue + DLQ"),
    "sns_topic": ("Amazon SNS", "Event notifications"),
}

# original icon-shape style string kept for the 18 already-bare nodes (verbatim from source)
ORIGINAL_ICON_STYLE = {}  # filled in from source tree

# new icon styles for the 6 previously-icon-less "polished" nodes
NEW_ICON_STYLE = {
    "waf": "sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor=#DD344C;strokeColor=#ffffff;dashed=0;html=1;fontSize=12;fontStyle=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.waf;",
    "cloudwatch": "sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor=#E7157B;strokeColor=#ffffff;dashed=0;html=1;fontSize=12;fontStyle=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.cloudwatch_2;",
    "kms_cmk": "sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor=#DD344C;strokeColor=#ffffff;dashed=0;html=1;fontSize=12;fontStyle=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.key_management_service;",
    "s3_frontend": "sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor=#7AA116;strokeColor=#ffffff;dashed=0;html=1;fontSize=12;fontStyle=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.simple_storage_service;",
    "ecs_fargate_ai": "sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor=#ED7100;strokeColor=#ffffff;dashed=0;html=1;fontSize=12;fontStyle=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.fargate;",
    "lambda_webhook": "sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor=#ED7100;strokeColor=#ffffff;dashed=0;html=1;fontSize=12;fontStyle=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;",
}

CARD_BG_STYLE = (
    "rounded=0;arcSize=12;whiteSpace=wrap;html=1;fillColor=light-dark(#ffffff,#0f1620);"
    "strokeColor=#AEB9C4;fontColor=light-dark(#1B2733,#CFE0F0);fontSize=12;align=left;"
    "spacingLeft=52;spacingRight=6;verticalAlign=middle;"
)
SHADOW_STYLE = "rounded=0;arcSize=12;whiteSpace=wrap;html=1;fillColor=#1F2A37;opacity=12;strokeColor=none;"
ACCENT_STYLE_TMPL = "rounded=0;arcSize=60;html=1;fillColor={color};strokeColor=none;"

# ---- edge routing overrides: explicit point lists (absolute canvas coords) ----
EDGE_POINTS = {
    "ed6": [(289, 362), (289, 264), (956, 264), (956, 381)],
    "ed7": [(1117, 288), (387, 288), (387, 561)],
    "ed11": [(464, 687), (464, 891), (833, 891)],
    "ed12": [(510, 687), (955, 687), (955, 998)],
    "ed13": [(522, 687), (706, 687), (706, 1173)],
    "ed14": [(714, 1202), (714, 687), (768, 687)],
    "ed15": [(653, 687), (400, 687), (400, 1160), (633, 1160)],
    "ed16": [(665, 1150), (430, 1150), (430, 891), (833, 891)],
    "ed17": [(587, 1150), (430, 1150), (430, 891), (587, 891)],
    "ed18": [(587, 1290), (1210, 1290), (1210, 891), (1079, 891)],
    "ed19": [(710, 687), (710, 891), (587, 891)],
    "ed20": [(918, 687), (959, 687), (959, 891), (645, 891)],
    "ed21": [(956, 687), (587, 687)],
    "ed22": [(994, 687), (1210, 687), (1210, 1150), (856, 1150)],
    "ed23": [(902, 1150), (1230, 1150), (1230, 687), (1163, 687)],
    "ed24": [(1360, 589), (1360, 1209)],
    "ed25": [(1039, 1312), (400, 1312), (400, 687), (541, 687)],
    "ed26": [(502, 687), (951, 687), (951, 1012)],
    "ed29": [(289, 687), (710, 687)],
    "ed30": [(200, 812), (289, 812), (289, 1334), (1127, 1334)],
    "ed31": [(160, 920), (289, 920), (289, 1356), (1210, 1356), (1210, 1090), (1148, 1090)],
}

# edges whose exit/entry side was changed for saner routing (id -> {attr: value})
EDGE_STYLE_OVERRIDES = {
    "ed21": {"exitY": "1"},          # was 0 (top); now exits bottom of scheduler
    "ed29": {"exitX": "1", "exitY": "0.5"},  # was 0.5,1 (bottom); now exits right of xray
}

AUTO_EDGES = {"ed1", "ed2", "ed3", "ed4", "ed5", "ed8", "ed9", "ed10", "ed27", "ed28"}


def wide_row_positions(tier_id, node_ids):
    x0, y0, w, h = TIER_GEOM[tier_id]
    n = len(node_ids)
    row_w = n * CARD_W + (n - 1) * GAP
    inner_w = w - 2 * PAD
    x_start = PAD + (inner_w - row_w) // 2
    content_top = CONTENT_TOP
    content_bottom = h - PAD
    avail_h = content_bottom - content_top
    card_y_rel = content_top + (avail_h - CARD_H) // 2
    out = {}
    for i, nid in enumerate(node_ids):
        x_rel = x_start + i * (CARD_W + GAP)
        out[nid] = (x0 + x_rel, y0 + card_y_rel, CARD_W, CARD_H)
    return out


def narrow_col_positions(tier_id, items):
    x0, y0, w, h = TIER_GEOM[tier_id]
    x_rel = (w - CARD_W_N) // 2
    y_rel = CONTENT_TOP
    out = {}
    for nid, ih in items:
        out[nid] = (x0 + x_rel, y0 + y_rel, CARD_W_N, ih)
        y_rel += ih + GAP
    return out


def build_new_boxes():
    boxes = {}
    for tier_id, node_ids in WIDE_ROWS.items():
        boxes.update(wide_row_positions(tier_id, node_ids))
    for tier_id, items in NARROW_COLUMNS.items():
        boxes.update(narrow_col_positions(tier_id, items))
    return boxes


def parent_of(node_id):
    for tier_id, node_ids in WIDE_ROWS.items():
        if node_id in node_ids:
            return tier_id
    for tier_id, items in NARROW_COLUMNS.items():
        if node_id in [i[0] for i in items]:
            return tier_id
    raise KeyError(node_id)


def make_cell(id_, value, style, parent, x, y, w, h, vertex=True):
    c = ET.Element("mxCell")
    c.set("id", id_)
    c.set("value", value)
    c.set("style", style)
    if vertex:
        c.set("vertex", "1")
    c.set("parent", parent)
    g = ET.SubElement(c, "mxGeometry")
    g.set("x", str(x))
    g.set("y", str(y))
    g.set("width", str(w))
    g.set("height", str(h))
    g.set("as", "geometry")
    return c


def main():
    tree = ET.parse(SRC)
    root = tree.getroot()
    diagram = root.find("diagram")
    model = diagram.find("mxGraphModel")
    old_root = model.find("root")
    old_cells = {c.get("id"): c for c in old_root if c.get("id")}

    for nid in list(WIDE_ROWS["application_tier"]) + list(WIDE_ROWS["api_gateway_tier"]) + \
            list(WIDE_ROWS["ai_ml_tier"]) + list(WIDE_ROWS["data_tier"]) + \
            list(WIDE_ROWS["messaging_tier"]) + list(WIDE_ROWS["frontend_tier"]) + \
            [i[0] for i in NARROW_COLUMNS["observability_tier"]]:
        cell = old_cells[nid]
        if cell.get("value") and cell.get("value").startswith("<b>"):
            continue  # already a card node (ecs_fargate_ai, lambda_webhook via later loop) - skip icon capture
        ORIGINAL_ICON_STYLE[nid] = cell.get("style")

    new_boxes = build_new_boxes()

    new_root = ET.Element("root")
    new_root.append(copy.deepcopy(old_cells["0"]))
    new_root.append(copy.deepcopy(old_cells["1"]))

    # 1) tier containers: clear title text, add separate title cell.
    # Width is a tight text-fit (not the full tier width) so the cell's bounding
    # box - used by the validator, and functionally identical to what a vertical
    # routing line must actually clear - doesn't span the whole zone.
    for tier_id, (x0, y0, w, h) in TIER_GEOM.items():
        tc = copy.deepcopy(old_cells[tier_id])
        title_text = tc.get("value")
        tc.set("value", "")
        new_root.append(tc)
        title_w = min(w - 24, int(len(title_text) * 7.5) + 16)
        title_cell = make_cell(
            f"{tier_id}_title", title_text,
            "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;"
            "whiteSpace=nowrap;fontFamily=Arial;fontSize=13;fontStyle=1;fontColor=#1A1A1A;",
            "1", x0 + 12, y0 + 6, title_w, 22,
        )
        new_root.append(title_cell)

    # 2) edges
    for cid, cell in old_cells.items():
        if cell.get("edge") != "1":
            continue
        e = copy.deepcopy(cell)
        geom = e.find("mxGeometry")
        arr = geom.find("Array")
        if cid in AUTO_EDGES:
            if arr is not None:
                geom.remove(arr)
        elif cid in EDGE_POINTS:
            if arr is None:
                arr = ET.SubElement(geom, "Array")
                arr.set("as", "points")
            else:
                for pt in list(arr):
                    arr.remove(pt)
            for (px, py) in EDGE_POINTS[cid]:
                p = ET.SubElement(arr, "mxPoint")
                p.set("x", str(px))
                p.set("y", str(py))
            if cid in EDGE_STYLE_OVERRIDES:
                style = e.get("style")
                for attr, val in EDGE_STYLE_OVERRIDES[cid].items():
                    import re
                    style = re.sub(rf"{attr}=[^;]*;", f"{attr}={val};", style)
                e.set("style", style)
        new_root.append(e)

    # 3) node cards / actor boxes
    all_narrow_items = []
    for tier_id, items in NARROW_COLUMNS.items():
        all_narrow_items.extend(items)
    all_node_ids = (
        [n for ids in WIDE_ROWS.values() for n in ids] +
        [n for n, _h in all_narrow_items]
    )

    for nid in all_node_ids:
        tier_id = parent_of(nid)
        tx0, ty0, _tw, _th = TIER_GEOM[tier_id]
        x_abs, y_abs, w, h = new_boxes[nid]
        # child geometry is relative to its parent container's origin
        x, y = x_abs - tx0, y_abs - ty0
        old_cell = old_cells[nid]

        if nid in ACTOR_BOXES:
            box = copy.deepcopy(old_cell)
            geom = box.find("mxGeometry")
            geom.set("x", str(x))
            geom.set("y", str(y))
            geom.set("width", str(w))
            geom.set("height", str(h))
            new_root.append(box)
            continue

        # shadow
        new_root.append(make_cell(f"{nid}__sh", "", SHADOW_STYLE, tier_id, x + 3, y + 4, w, h))

        # background card (id preserved)
        if nid in TRIMMED_TEXT:
            title, subtitle = TRIMMED_TEXT[nid]
        else:
            # already a short "<b>title</b><br>...subtitle" value - reuse verbatim
            title = subtitle = None
        bg = ET.Element("mxCell")
        bg.set("id", nid)
        if title is not None:
            bg.set(
                "value",
                f'<b>{title}</b><br><font style="font-size: 10px" color="#647687">{subtitle}</font>',
            )
        else:
            bg.set("value", old_cell.get("value"))
        bg.set("style", CARD_BG_STYLE)
        bg.set("vertex", "1")
        bg.set("parent", tier_id)
        g = ET.SubElement(bg, "mxGeometry")
        g.set("x", str(x))
        g.set("y", str(y))
        g.set("width", str(w))
        g.set("height", str(h))
        g.set("as", "geometry")
        new_root.append(bg)

        # icon
        icon_style = NEW_ICON_STYLE.get(nid, ORIGINAL_ICON_STYLE.get(nid))
        if icon_style:
            new_root.append(
                make_cell(f"{nid}_icon", "", icon_style, tier_id, x + 10, y + 20, 32, 32)
            )

        # accent bar
        color = TIER_ACCENT[tier_id]
        new_root.append(
            make_cell(f"{nid}__ac", "", ACCENT_STYLE_TMPL.format(color=color), tier_id,
                      x + 5, y - 1, w - 10, 4)
        )

    # 4) title + legend (unchanged)
    new_root.append(copy.deepcopy(old_cells["__title"]))
    legend = copy.deepcopy(old_cells["__legend"])
    new_root.append(legend)
    for cid, cell in old_cells.items():
        if cell.get("parent") == "__legend":
            new_root.append(copy.deepcopy(cell))

    model.remove(old_root)
    model.append(new_root)

    ET.indent(tree, space="  ")
    tree.write(DST, encoding="utf-8", xml_declaration=False)
    print(f"wrote {DST}")


if __name__ == "__main__":
    main()
