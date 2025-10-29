#!/usr/bin/env python3
# Lightweight symbolic visualization for reconcile report
# Usage:
#   python viz_blocks.py --json reconcile_report.json --out report_blocks.html --top 20
#   python viz_blocks.py --account 8886006288 --out report_blocks.html
#
# If --account is provided and this script runs inside project env, it will try to call
# gui.reconcile_report.generate_reconcile_report(account).
#
# Output:
#  - prints an ASCII symbolic visualization to stdout
#  - writes a simple HTML file with colored boxes to --out (default: viz_report.html)

import json
import argparse
import math
from decimal import Decimal

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print("load_json error:", e)
        return None

def load_report_from_account(account_id):
    # try to import generate_reconcile_report from repo if available
    try:
        from gui.reconcile_report import generate_reconcile_report
        rep = generate_reconcile_report(str(account_id))
        # convert Decimal to floats (if present)
        return rep
    except Exception as e:
        print("Warning: cannot import generate_reconcile_report (running outside project or import error):", e)
        return None

def normalize_rows(report):
    # expect report: dict with 'total_asset' and 'rows' OR three groups both/yunfei_only/positions_only
    total = report.get('total_asset') or report.get('totalAsset') or 0
    try:
        total_asset = float(total)
    except Exception:
        total_asset = 0.0
    rows = []
    if 'rows' in report and isinstance(report['rows'], list):
        rows = report['rows']
    else:
        # merge both + yunfei_only + positions_only
        for k in ('both','yunfei_only','positions_only'):
            for r in report.get(k, []):
                rows.append(r)
    # ensure numeric fields
    final = []
    for r in rows:
        code = r.get('stock_code') or r.get('code') or None
        name = r.get('stock_name') or r.get('stock') or (code or '')
        exp = r.get('expected_money') or r.get('expected') or 0
        cur = r.get('current_market_value') or r.get('current') or 0
        try:
            expv = float(exp)
        except Exception:
            expv = 0.0
        try:
            curv = float(cur)
        except Exception:
            curv = 0.0
        final.append({
            'code': str(code or '')[:12],
            'name': str(name),
            'expected': expv,
            'current': curv
        })
    return total_asset, final

def ascii_visual(rows, total_asset, top=20, width=50):
    """
    Print simple ascii boxes: each row shows expected and current as bars (█ / ░)
    width: max width characters for the bigger of expected/current relative to total_asset (or max)
    """
    if not rows:
        print("no rows")
        return
    # sort by abs diff desc
    rows_sorted = sorted(rows, key=lambda r: abs(r['expected'] - r['current']), reverse=True)
    rows_sorted = rows_sorted[:top]

    denom = total_asset if total_asset and total_asset > 0 else max(max(r['expected'], r['current']) for r in rows_sorted) or 1.0

    print("\nASCII SYMBOLIC VISUALIZATION (top {})".format(top))
    print("Legend: [E]=Expected  [C]=Current  (width={} chars, denom = {:.2f})".format(width, denom))
    print("-" * (width + 60))
    for r in rows_sorted:
        label = (r['code'] + " " + r['name'])[:30].ljust(30)
        e_pct = r['expected'] / denom
        c_pct = r['current'] / denom
        e_w = int(round(min(1.0, e_pct) * width))
        c_w = int(round(min(1.0, c_pct) * width))
        # build bar: expected uses '=', current uses '#', overlap shows '#'
        bar_chars = []
        for i in range(width):
            ch = ' '
            if i < e_w:
                ch = '='
            if i < c_w:
                ch = '#'
            bar_chars.append(ch)
        bar = ''.join(bar_chars)
        print(f"{label} |{bar}| E:{r['expected']:.0f} C:{r['current']:.0f} Δ:{(r['expected']-r['current']):+.0f}")
    print("-" * (width + 60))
    print()

def gen_html(report_rows, total_asset, outpath):
    """
    Produce a simple HTML file with two horizontal rows:
     - Expected: a series of inline-block colored boxes whose widths are percentage of total_asset
     - Current: same
    Boxes are labeled and clickable (show title tooltip)
    """
    # only include rows with positive expected or current
    rows = [r for r in report_rows if (r['expected'] > 0 or r['current'] > 0)]
    if not rows:
        html = "<html><body><p>No data to visualize.</p></body></html>"
        open(outpath, 'w', encoding='utf-8').write(html)
        return outpath

    # sort by expected desc for consistent layout
    rows = sorted(rows, key=lambda r: r['expected'], reverse=True)

    denom = total_asset if total_asset and total_asset > 0 else sum(max(r['expected'], r['current']) for r in rows) or 1.0

    # build divs
    expected_divs = []
    current_divs = []
    for r in rows:
        pname = (r['code'] + " " + r['name']).strip()
        e_pct = (r['expected'] / denom) * 100
        c_pct = (r['current'] / denom) * 100
        e_width = max(0.1, e_pct) if r['expected']>0 else 0.1  # ensure visible minimal
        c_width = max(0.1, c_pct) if r['current']>0 else 0.1
        # clamp small values visually
        expected_divs.append(f'<div class="box exp" title="{pname} — expected {r["expected"]:.2f} ({e_pct:.2f}%)" style="width:{e_pct:.2f}%">{pname}</div>')
        current_divs.append(f'<div class="box cur" title="{pname} — current {r["current"]:.2f} ({c_pct:.2f}%)" style="width:{c_pct:.2f}%">{pname}</div>')

    html_tpl = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Reconcile Blocks</title>
<style>
body{{font-family: Arial, Helvetica, sans-serif; padding:16px; background:#f7f9fc; color:#222}}
.container{{max-width:1100px;margin:0 auto}}
.row-title{{margin-top:12px;font-weight:700}}
.row{{display:flex;align-items:center;height:48px;gap:4px; margin-bottom:8px;}}
.box{{height:40px;line-height:40px;color:#fff;padding:0 6px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:12px;border-radius:4px}}
.exp{{background:#2b8a3e}}
.cur{{background:#c0392b}}
.legend{{margin:8px 0 18px 0}}
.legend span{{display:inline-block;padding:6px 10px;border-radius:4px;color:#fff;margin-right:8px}}
.legend .e{{background:#2b8a3e}} .legend .c{{background:#c0392b}}
.small{{font-size:12px;color:#666;margin-top:6px}}
.tooltip{{font-size:12px;color:#333}}
.note{{margin-top:18px;color:#666;font-size:13px}}
</style>
</head>
<body>
<div class="container">
  <h2>对账符号化可视化</h2>
  <div class="note">每个方块宽度表示该标的占账户总资产的比例（Expected 与 Current 行分别显示）。鼠标移动到方块上可查看具体金额与比例。</div>
  <div class="legend"><span class="e">应配置（Expected）</span> <span class="c">当前持仓（Current）</span></div>

  <div class="row-title">Expected (按账户总资产比例)</div>
  <div class="row" id="expected-row">
    {"".join(expected_divs)}
  </div>

  <div class="row-title">Current (按账户总资产比例)</div>
  <div class="row" id="current-row">
    {"".join(current_divs)}
  </div>

  <div class="small">Denominator used: {denom:.2f} (账户总资产或总和)</div>

  <div style="margin-top:18px;">
    <details><summary>导出数据（JSON）</summary>
    <pre>{json.dumps(rows, ensure_ascii=False, indent=2)}</pre>
    </details>
  </div>
</div>
</body>
</html>
"""
    with open(outpath, 'w', encoding='utf-8') as f:
        f.write(html_tpl)
    return outpath

def main():
    p = argparse.ArgumentParser(description="Simple symbolic reconcile visualization")
    p.add_argument('--json', help='reconcile JSON file (export of generate_reconcile_report or reconcile_for_account)')
    p.add_argument('--account', help='account id to call generate_reconcile_report (if running inside project)', default=None)
    p.add_argument('--out', help='html output path', default='viz_report.html')
    p.add_argument('--top', help='top N rows to show in ASCII', type=int, default=20)
    args = p.parse_args()

    report = None
    if args.json:
        report = load_json(args.json)
        if not report:
            print("Failed to load JSON from", args.json)
            return
    elif args.account:
        report = load_report_from_account(args.account)
        if not report:
            print("Failed to load report for account", args.account)
            return
    else:
        print("Please provide --json path or --account id")
        return

    total_asset, rows = normalize_rows(report)
    ascii_visual(rows, total_asset, top=args.top)
    out = gen_html(rows, total_asset, args.out)
    print("Wrote HTML visualization to", out)
    print("Open it in a browser to view colored boxes.")

if __name__ == '__main__':
    main()