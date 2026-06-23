"""Client-side glue for the canvas (free-positioning) editor — vanilla JS, no vendored library.

``note.py`` injects ``CANVAS_CSS`` and runs ``canvas_init_js(seed, token)`` once. The surface is a
lightweight A4-aspect page of draggable/resizable boxes that MIRROR ``note.blocks`` — the authoritative
content + styling stays in Python and is shown faithfully in the live-preview iframe beside it.

Boxes report geometry as PERCENTAGES of the page (so the editor and the fixed-A4 export agree):
* ``canvas_changed {id,x,y,w,h,z}`` — after a drag/resize (debounced)
* ``canvas_edit {id}``             — double-click, to edit the block's content server-side
* ``canvas_delete {id}``           — the box's × button

``window.dnCanvasRender(boxes)`` re-renders the whole surface (after add/delete/edit), mirroring how
the document editor re-renders via ``ed.blocks.render``.
"""
from __future__ import annotations

CANVAS_CSS = """
<style>
#dncanvas-wrap{background:#ececec;border-radius:8px;padding:16px;overflow:auto;max-height:80vh;}
#dncanvas{position:relative;width:100%;aspect-ratio:210/297;background:#fff;margin:0 auto;
  box-shadow:0 6px 24px rgba(0,0,0,.18);border-radius:4px;}
.dn-box{position:absolute;border:1.5px solid #c9b8e0;border-radius:8px;background:rgba(255,255,255,.92);
  box-shadow:0 1px 5px rgba(0,0,0,.08);padding:5px 7px;overflow:hidden;cursor:move;touch-action:none;
  font:12px/1.35 'Nunito Sans',system-ui,sans-serif;color:#4a4360;user-select:none;box-sizing:border-box;}
.dn-box .dn-tag{display:block;font-size:8.5px;text-transform:uppercase;letter-spacing:.5px;color:#9a8fb5;margin-bottom:1px;}
.dn-box.sel{border-color:#7c4dff;box-shadow:0 0 0 2px rgba(124,77,255,.30);}
.dn-h{position:absolute;right:-6px;bottom:-6px;width:14px;height:14px;background:#7c4dff;border:2px solid #fff;
  border-radius:50%;cursor:nwse-resize;touch-action:none;}
.dn-del{position:absolute;right:-8px;top:-8px;width:17px;height:17px;background:#e0566f;color:#fff;border:none;
  border-radius:50%;font:12px/1 sans-serif;cursor:pointer;display:none;padding:0;}
.dn-box.sel .dn-del{display:block;}
</style>
"""

_INIT_TEMPLATE = r"""
(function start(){
  var page = document.getElementById('dncanvas');
  if(!page){ return setTimeout(start, 60); }
  var TOKEN = "__TOKEN__";
  var sel = null, emitTimer = null;

  function clamp(v, lo, hi){ return Math.max(lo, Math.min(hi, v)); }

  function select(el){
    if(sel && sel!==el) sel.classList.remove('sel');
    sel = el; if(el) el.classList.add('sel');
  }

  function emitChange(el){
    clearTimeout(emitTimer);
    emitTimer = setTimeout(function(){
      var r = page.getBoundingClientRect(), b = el.getBoundingClientRect();
      emitEvent('canvas_changed', {
        id: el.dataset.id,
        x: clamp((b.left - r.left) / r.width * 100, 0, 100),
        y: clamp((b.top - r.top) / r.height * 100, 0, 100),
        w: clamp(b.width / r.width * 100, 4, 100),
        h: clamp(b.height / r.height * 100, 3, 100),
        z: parseInt(el.style.zIndex || '0', 10) || 0
      });
    }, 250);
  }

  function dragMove(el, handle, ev, resizing){
    var r = page.getBoundingClientRect();
    var sx = ev.clientX, sy = ev.clientY;
    var ox = el.offsetLeft, oy = el.offsetTop, ow = el.offsetWidth, oh = el.offsetHeight;
    var target = resizing ? handle : el;
    target.setPointerCapture(ev.pointerId);
    function mv(e){
      if(resizing){
        var nw = clamp(ow + (e.clientX - sx), 44, r.width);
        var nh = clamp(oh + (e.clientY - sy), 26, r.height);
        el.style.width = nw / r.width * 100 + '%';
        el.style.height = nh / r.height * 100 + '%';
      } else {
        var nx = clamp(ox + (e.clientX - sx), 0, r.width - el.offsetWidth);
        var ny = clamp(oy + (e.clientY - sy), 0, r.height - el.offsetHeight);
        el.style.left = nx / r.width * 100 + '%';
        el.style.top = ny / r.height * 100 + '%';
      }
    }
    function up(){
      try{ target.releasePointerCapture(ev.pointerId); }catch(e){}
      target.removeEventListener('pointermove', mv);
      target.removeEventListener('pointerup', up);
      emitChange(el);
    }
    target.addEventListener('pointermove', mv);
    target.addEventListener('pointerup', up);
    ev.preventDefault();
  }

  function makeBox(d){
    var el = document.createElement('div');
    el.className = 'dn-box'; el.dataset.id = d.id;
    el.style.left = d.x + '%'; el.style.top = d.y + '%';
    el.style.width = d.w + '%'; el.style.height = d.h + '%'; el.style.zIndex = d.z || 0;
    el.innerHTML = '<span class="dn-tag"></span><span class="dn-lbl"></span>';
    el.querySelector('.dn-tag').textContent = (d.type || '').replace(/_/g, ' ');
    el.querySelector('.dn-lbl').textContent = d.label || '';
    var h = document.createElement('div'); h.className = 'dn-h'; el.appendChild(h);
    var del = document.createElement('button'); del.className = 'dn-del'; del.innerHTML = '&times;'; el.appendChild(del);
    el.addEventListener('pointerdown', function(ev){
      if(ev.target === h || ev.target === del) return;
      select(el); dragMove(el, h, ev, false);
    });
    h.addEventListener('pointerdown', function(ev){ ev.stopPropagation(); select(el); dragMove(el, h, ev, true); });
    del.addEventListener('click', function(ev){ ev.stopPropagation(); emitEvent('canvas_delete', {id: el.dataset.id}); });
    el.addEventListener('dblclick', function(ev){ ev.stopPropagation(); emitEvent('canvas_edit', {id: el.dataset.id}); });
    page.appendChild(el);
  }

  window.dnCanvasRender = function(boxes){
    Array.prototype.slice.call(page.querySelectorAll('.dn-box')).forEach(function(n){ n.remove(); });
    sel = null;
    (boxes || []).forEach(makeBox);
  };

  page.addEventListener('pointerdown', function(ev){ if(ev.target === page) select(null); });
  window.dnCanvasRender(__SEED__);
})();
"""


def canvas_init_js(seed_json: str, token: str) -> str:
    """Build the one-shot canvas init script: seed boxes + upload token baked in (token first, so
    note content can't clobber the placeholder)."""
    return _INIT_TEMPLATE.replace("__TOKEN__", token).replace("__SEED__", seed_json)
