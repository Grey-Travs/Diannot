"""Two-column layout: left/right runs flow in independent columns (no shared-row-height gaps)."""
from diannot.models import BannerBlock, BodyBlock, Note, TableBlock
from diannot.render import _layout_groups, render_note_html


def test_layout_groups_partitions_runs_and_breaks_on_full():
    n = Note(title="T", blocks=[
        BannerBlock(text="B"),
        BodyBlock(text="L1", layout="col1"), BodyBlock(text="L2", layout="col1"),
        BodyBlock(text="R1", layout="col2"),
        TableBlock(headers=["a"], rows=[["1"]]),  # forced full -> breaks the section
        BodyBlock(text="L3", layout="col1"), BodyBlock(text="R2", layout="col2"),
    ])
    g = _layout_groups(n.blocks)
    assert [x[0] for x in g] == ["full", "cols", "full", "cols"]
    assert ([b.text for b in g[1][1]], [b.text for b in g[1][2]]) == (["L1", "L2"], ["R1"])


def test_uneven_columns_each_pack_their_own_side():
    # a TALL left run + a SHORT right run must not pair into rows (which is what caused the gap)
    blocks = [BannerBlock(text="Errors")]
    blocks += [BodyBlock(text=f"L{i}", layout="col1") for i in range(6)]
    blocks += [BodyBlock(text=f"R{i}", layout="col2") for i in range(3)]
    html = render_note_html(Note(title="Errors", blocks=blocks))
    import re
    m = re.search(r'<div class="cols"><div class="col">(.*?)</div><div class="col">(.*?)</div></div>',
                  html, re.S)
    assert m
    assert m.group(1).count('class="body') == 6  # all left blocks in the left column
    assert m.group(2).count('class="body') == 3  # all right blocks in the right column
