"""End-to-end tour: build a document, edit through the canvas, then act as an
agent through the tool surface, and render what the agent would see."""
from pathlib import Path

from neeh import Canvas, Document, StrokeStyle
from neeh.tools import call_tool, tool_schemas

canvas = Canvas(Document(title="Quickstart"))

# --- user writes some ink -------------------------------------------------
zigzag = canvas.add_stroke(
    [(100, 100), (160, 180), (220, 100), (280, 180), (340, 100)],
    style=StrokeStyle(color="#2244aa", width=3.0),
)
dot = canvas.add_stroke([(500, 140)])
print(f"user drew {zigzag.id} and {dot.id}")

# --- select, move, undo ----------------------------------------------------
canvas.select(region=zigzag.bbox.expanded(10))
moved = canvas.move(0, 200)
print(f"moved {moved} stroke(s); undo -> {canvas.undo()!r}")

# --- now the agent takes a turn through the tool surface -------------------
view = call_tool(canvas, "view_page")
print(f"agent sees page {view['page_id']} as {len(view['data'])} bytes of SVG")

mark = call_tool(canvas, "add_stroke", {
    "points": [[120, 260], [200, 240], [280, 260]],
    "color": "#aa2222",
})
call_tool(canvas, "highlight", {"region": [90, 80, 350, 200]})
print(f"agent drew {mark['stroke_id']} and a highlight (both on the agent layer)")

erased = call_tool(canvas, "erase", {"stroke_ids": [dot.id]})
print(f"agent erased {erased['erased']}; undo -> {call_tool(canvas, 'undo')}")

# --- persistence + a look at the tool manifest ------------------------------
out = Path(__file__).parent
canvas.document.save(out / "quickstart.neeh")
(out / "quickstart.svg").write_text(call_tool(canvas, "view_page")["data"])
print(f"saved quickstart.neeh and quickstart.svg next to this script")
print(f"tool manifest: {[t['name'] for t in tool_schemas()]}")
