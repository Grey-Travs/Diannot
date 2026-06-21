"""Client-side glue for the Editor.js document editor (vendored, offline).

``note.py`` loads the vendored scripts, injects ``EDITOR_CSS`` and runs ``editor_init_js(seed,
token)`` once. The init defines two custom pieces:

* **dn tune** — the "fold the paper" column control (Left / Right / Full / Auto) that ALSO carries
  the preserved block ``meta`` (a block-tune survives ``editor.save()``; an unknown data key would
  not). Maps to/from :mod:`diannot.studio.docedit`.
* **DnRaw** — a read-only passthrough for callout/diagram blocks so they survive untouched.

The editor emits ``doc_changed`` (debounced) carrying ``editor.save()``; the server turns that back
into ``note.blocks`` via ``docedit.editor_to_blocks`` and reuses the existing preview/autosave.
"""
from __future__ import annotations

# Vendored under assets/vendor/editorjs/, served at /dnvendor/editorjs/. Core first, then tools.
VENDOR_SCRIPTS = [
    "editorjs.umd.js",
    "header.umd.min.js",
    "nested-list.umd.min.js",
    "table.umd.min.js",
    "image.umd.min.js",
    "quote.umd.min.js",
]

# Make Editor.js fill the (narrow) left pane and read like a clean sheet of paper.
EDITOR_CSS = """
<style>
#editorjs{background:#fff;border:1px solid #e6e0ef;border-radius:14px;
  padding:10px 6px;min-height:74vh;color:#2b2540;}
#editorjs .ce-block__content,#editorjs .ce-toolbar__content{max-width:none;margin:0 38px;}
#editorjs .codex-editor__redactor{padding-bottom:140px !important;}
.body--dark #editorjs{box-shadow:0 6px 24px rgba(0,0,0,.35);}
</style>
"""

_INIT_TEMPLATE = r"""
(function start(){
  var deps = window.EditorJS && window.Header && window.NestedList
             && window.Table && window.ImageTool && window.Quote;
  if(!deps){ return setTimeout(start, 60); }
  if(window._dnEditor){ try{ window._dnEditor.destroy(); }catch(e){} window._dnEditor=null; }
  window._dnReady = false;
  var TOKEN = "__TOKEN__";
  var SEED = __SEED__;

  // "Fold the paper" column control + carrier for preserved block meta (survives save()).
  class DnTune {
    static get isTune(){ return true; }
    constructor(args){ var d=(args&&args.data)||{}; this.layout=d.layout||'auto';
                       this.meta=(d.meta!==undefined)?d.meta:null; }
    render(){
      var self=this;
      var opts=[['col1','Left column','L'],['col2','Right column','R'],
                ['full','Full width','▭'],['auto','Auto (flow)','A']];
      return opts.map(function(o){
        return { icon:'<b style="font-size:13px">'+o[2]+'</b>', title:o[1], toggle:'dn-col',
                 isActive:self.layout===o[0], closeOnActivate:true,
                 onActivate:function(){ self.layout=o[0]; } };
      });
    }
    save(){ return { layout:this.layout, meta:this.meta }; }
  }

  // Read-only passthrough for callout/diagram (editable in Classic mode for now).
  class DnRaw {
    constructor(args){ this.data=(args&&args.data)||{}; }
    static get contentless(){ return true; }
    render(){
      var el=document.createElement('div'); el.contentEditable='false';
      el.innerHTML='<div style="margin:6px 0;padding:10px 12px;border:1px dashed #c9b8e0;'
        +'border-radius:10px;background:#faf6ff;color:#6b5b85;font-size:13px">'
        +'<b>'+((this.data&&this.data.summary)||'Diannot block')+'</b>'
        +'<div style="opacity:.65;font-size:12px;margin-top:2px">Special block — '
        +'edit it in Classic mode.</div></div>';
      return el;
    }
    save(){ return this.data; }
  }

  var editor = new EditorJS({
    holder:'editorjs', autofocus:false, minHeight:160,
    placeholder:'Type here…  press "/" to add a heading, list, table or image',
    data: SEED,
    tools:{
      header:{ class:Header, inlineToolbar:true, config:{ levels:[1,2,3], defaultLevel:2 } },
      list:{ class:NestedList, inlineToolbar:true },
      table:{ class:Table, inlineToolbar:true },
      quote:{ class:Quote, inlineToolbar:true },
      image:{ class:ImageTool, config:{ uploader:{
        uploadByFile:function(file){ var fd=new FormData(); fd.append('image',file);
          return fetch('/preview/upload?token='+encodeURIComponent(TOKEN),
            {method:'POST',body:fd}).then(function(r){return r.json();}); } } } },
      diannotRaw:{ class:DnRaw },
      dn:{ class:DnTune },
    },
    tunes:['dn'],
    onChange:function(){
      if(!window._dnReady) return;
      clearTimeout(window._dnDebounce);
      window._dnDebounce=setTimeout(function(){
        editor.save().then(function(out){ emitEvent('doc_changed', out); })
                     .catch(function(e){ console.error(e); });
      }, 700);
    },
  });
  window._dnEditor = editor;
  editor.isReady.then(function(){ setTimeout(function(){ window._dnReady=true; }, 250); })
               .catch(function(e){ console.error('Editor.js init failed', e); });
})();
"""


def editor_init_js(seed_json: str, token: str) -> str:
    """Build the one-shot init script for a note: seed data + upload token baked in."""
    return _INIT_TEMPLATE.replace("__SEED__", seed_json).replace("__TOKEN__", token)
