#!/usr/bin/env python3
"""Create and export a locally editable Toastmasters agenda HTML file."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
EXPORT_SCRIPT = SCRIPT_DIR / "export_a4.py"
EDITOR_MARKER = "agenda-editable-controls"
CONFIRMATION_META = '<meta name="agenda-edit-confirmed" content="false">'

EDITOR_STYLE = r"""
<style id="agenda-editable-style">
.agenda-editor-controls { position: fixed; right: 10px; bottom: 8px; z-index: 10000; display: flex; gap: 8px; font: 12px/1.2 system-ui, sans-serif; opacity: .34; }
.agenda-editor-controls:hover, .agenda-editor-controls:focus-within { opacity: 1; }
.agenda-editor-controls a { color: #475569; text-decoration: none; cursor: pointer; }
.agenda-editor-controls a:hover { text-decoration: underline; }
.agenda-editor-status { display: none; color: #475569; }
body.agenda-editing .agenda-page [contenteditable="true"] { outline: 1px dashed rgba(127, 29, 29, .55); outline-offset: 2px; background: rgba(255, 251, 235, .72); cursor: text; }
body.agenda-editing .agenda-editor-status { display: inline; }
@media print { .agenda-editor-controls { display: none !important; } body.agenda-editing .agenda-page [contenteditable="true"] { outline: none; background: transparent; } }
</style>
"""

EDITOR_SCRIPT = r"""
<nav class="agenda-editor-controls" id="agenda-editable-controls" aria-label="会单编辑控制">
  <a href="#" id="agenda-edit-link">编辑信息</a>
  <a href="#" id="agenda-confirm-link">确认保存</a>
  <span class="agenda-editor-status" id="agenda-editor-status" aria-live="polite"></span>
</nav>
<script id="agenda-editable-script">
(() => {
  const selector = [
    '.meta-value', '.agenda-row > div', '.stage-label > span', '.stage-label > small',
    '.support-card h3', '.support-card p', '.support-card li', '.support-card dt',
    '.support-card dd', '.timing-rule strong', '.timing-rule span', '.meeting-title span',
    '.eyebrow', '.theme-line strong', '.panel-heading h2', '.meeting-range', '.page-footer span'
  ].join(',');
  const editLink = document.getElementById('agenda-edit-link');
  const confirmLink = document.getElementById('agenda-confirm-link');
  const status = document.getElementById('agenda-editor-status');
  const confirmation = document.querySelector('meta[name="agenda-edit-confirmed"]');
  let editing = false;

  const setEditing = (value) => {
    editing = value;
    document.body.classList.toggle('agenda-editing', value);
    document.querySelectorAll(selector).forEach((node) => {
      node.contentEditable = value ? 'true' : 'false';
      node.spellcheck = value;
    });
    if (value) {
      if (confirmation) confirmation.content = 'false';
      document.documentElement.dataset.agendaEditConfirmed = 'false';
      status.textContent = '编辑中';
    }
  };

  const downloadConfirmedHtml = () => {
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('[contenteditable]').forEach((node) => node.removeAttribute('contenteditable'));
    const cloneMeta = clone.querySelector('meta[name="agenda-edit-confirmed"]');
    if (cloneMeta) cloneMeta.content = 'true';
    clone.dataset.agendaEditConfirmed = 'true';
    const blob = new Blob(['<!doctype html>\n', clone.outerHTML], {type: 'text/html;charset=utf-8'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = '会单-已确认.html';
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  };

  editLink.addEventListener('click', (event) => { event.preventDefault(); setEditing(true); });
  confirmLink.addEventListener('click', (event) => {
    event.preventDefault();
    setEditing(false);
    if (confirmation) confirmation.content = 'true';
    document.documentElement.dataset.agendaEditConfirmed = 'true';
    status.textContent = '已确认，已下载 HTML';
    downloadConfirmedHtml();
  });
  if (confirmation && confirmation.content === 'true') status.textContent = '已确认';
})();
</script>
"""


def emit(payload: dict[str, object], *, error: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr if error else sys.stdout)


def make_editable(source: Path, output: Path) -> None:
    html = source.read_text(encoding="utf-8")
    if EDITOR_MARKER in html:
        raise ValueError("HTML already contains the editable agenda controls")
    if "</head>" not in html or "</body>" not in html:
        raise ValueError("agenda HTML must be a complete document")
    html = html.replace("</head>", f"  {CONFIRMATION_META}\n{EDITOR_STYLE}</head>", 1)
    html = html.replace("</body>", f"{EDITOR_SCRIPT}</body>", 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")


def require_confirmed(source: Path) -> None:
    html = source.read_text(encoding="utf-8")
    if EDITOR_MARKER not in html:
        raise ValueError("HTML is not an editable agenda file")
    if '<meta name="agenda-edit-confirmed" content="true">' not in html:
        raise ValueError("please click 确认保存 in the editable HTML before exporting")


def export_confirmed(source: Path, output_dir: Path) -> dict[str, object]:
    require_confirmed(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agenda-edited-export-", dir=output_dir.parent) as temp:
        staging = Path(temp)
        result = subprocess.run(
            [sys.executable, str(EXPORT_SCRIPT), str(source), "--output-dir", str(staging)],
            check=False,
            capture_output=True,
            text=True,
        )
        raw = result.stdout if result.returncode == 0 else result.stderr
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("image export returned invalid output") from exc
        if result.returncode != 0 or payload.get("ok") is not True:
            raise ValueError("image export failed: " + "; ".join(payload.get("errors", [])))
        pdf = output_dir / "agenda.edited.pdf"
        png = output_dir / "agenda.edited.png"
        (staging / "agenda.pdf").replace(pdf)
        (staging / "agenda.png").replace(png)
    return {"ok": True, "stage": "edited_exported", "pdf": str(pdf), "png": str(png), "pages": 1}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("make", help="add WYSIWYG editing controls to an agenda HTML")
    make.add_argument("input_html", type=Path)
    make.add_argument("--output", type=Path, required=True)
    export = commands.add_parser("export", help="export a confirmed editable agenda as PDF and PNG")
    export.add_argument("input_html", type=Path)
    export.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args()
    try:
        source = args.input_html.expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"HTML does not exist: {source}")
        if args.command == "make":
            output = args.output.expanduser().resolve()
            make_editable(source, output)
            emit({"ok": True, "stage": "editable_ready", "html": str(output)})
        else:
            emit(export_confirmed(source, args.output_dir.expanduser().resolve()))
    except (OSError, ValueError) as exc:
        emit({"ok": False, "errors": [str(exc)]}, error=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
