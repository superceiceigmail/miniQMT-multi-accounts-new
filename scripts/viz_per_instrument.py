#!/usr/bin/env python3
"""
viz_per_instrument.py

Per-instrument symbolic comparer for reconcile reports.

Usage examples:
  # Read a reconcile JSON and print ASCII to console:
  py -3 .\scripts\viz_per_instrument.py --json reconcile_8886006288.json --blocks 30 --scale total --top 40

  # Also generate HTML:
  py -3 .\scripts\viz_per_instrument.py --json reconcile_8886006288.json --out viz_8886006288.html

  # Or (if running inside project and python can import gui.reconcile_report):
  py -3 .\scripts\viz_per_instrument.py --account 8886006288 --out viz_8886006288.html
"""
import argparse
import json
import os
import sys
from decimal import Decimal

ANSI_GREEN = '\033[92m'
ANSI_RED = '\033[91m'
ANSI_RESET = '\033[0m'


def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print("load_json error:", e, file=sys.stderr)
        return None


def load_report_from_account(account_id):
    try:
        from gui.reconcile_report import generate_reconcile_report
        return generate_reconcile_report(str(account_id))
    except Exception as e:
        print("Warning: cannot import generate_reconcile_report:", e, file=sys.stderr)
        return None


def normalize_rows(report):
    total = report.get('total_asset') or report.get('totalAsset') or 0
    try:
        total_asset = float(total)
    except Exception:
        total_asset = 0.0
    rows = []
    if 'rows' in report and isinstance(report['rows'], list):
        rows = report['rows']
    else:
        for k in ('both', 'yunfei_only', 'positions_only'):
            arr = report.get(k)
            if isinstance(arr, list):
                rows.extend(arr)
    out = []
    for r in rows:
        code = r.get('stock_code') or r.get('code') or ''
        name = r.get('stock_name') or r.get('stock') or code
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
        out.append({
            'code': str(code),
            'name': str(name),
            'expected': expv,
            'current': curv,
            'diff': expv - curv,
            'absdiff': abs(expv - curv)
        })
    return total_asset, out


def render_line(item, denom, blocks, color=False, scale_mode='total'):
    exp = item['expected']
    cur = item['current']

    if scale_mode == 'row':
        local_denom = max(exp, cur, 1.0)
    else:
        local_denom = denom if denom and denom > 0 else max(exp, cur, 1.0)

    exp_frac = min(1.0, exp / local_denom) if local_denom > 0 else 0.0
    cur_frac = min(1.0, cur / local_denom) if local_denom > 0 else 0.0

    exp_blocks = int(round(exp_frac * blocks))
    cur_blocks = int(round(cur_frac * blocks))

    bar_chars = []
    for i in range(blocks):
        if i < exp_blocks and i < cur_blocks:
            ch = '▓'  # overlap/current priority
        elif i < cur_blocks:
            ch = '▓'
        elif i < exp_blocks:
            ch = '▒'
        else:
            ch = '·'
        bar_chars.append(ch)
    bar = ''.join(bar_chars)

    pct_exp = (exp / denom * 100) if denom and denom > 0 else 0.0
    pct_cur = (cur / denom * 100) if denom and denom > 0 else 0.0

    label = f"{(item['code'] + ' ' + item['name'])[:36]:36}"
    if color:
        diff_colored = (ANSI_RED + f"{item['diff']:10.2f}" + ANSI_RESET) if item['diff'] > 0 else (ANSI_GREEN + f"{item['diff']:10.2f}" + ANSI_RESET)
        bar_colored = ''
        for ch in bar:
            if ch == '▓':
                bar_colored += ANSI_RED + ch + ANSI_RESET
            elif ch == '▒':
                bar_colored += ANSI_GREEN + ch + ANSI_RESET
            else:
                bar_colored += ch
        vals = f"E:{item['expected']:10.2f} ({pct_exp:5.2f}%)  C:{item['current']:10.2f} ({pct_cur:5.2f}%)  Δ:{diff_colored}"
        return f"{label} |{bar_colored}| {vals}"
    else:
        vals = f"E:{item['expected']:10.2f} ({pct_exp:5.2f}%)  C:{item['current']:10.2f} ({pct_cur:5.2f}%)  Δ:{item['diff']:10.2f}"
        return f"{label} |{bar}| {vals}"


def gen_html(rows, total_asset, outpath):
    rows = [r for r in rows if (r['expected'] > 0 or r['current'] > 0)]
    if not rows:
        html = "<html><body><p>No data to visualize.</p></body></html>"
        open(outpath, 'w', encoding='utf-8').write(html)
        return outpath

    rows = sorted(rows, key=lambda r: r['expected'], reverse=True)
    denom = total_asset if total_asset > 0 else sum(max(r['expected'], r['current']) for r in rows) or 1.0

    rows_html = []
    for r in rows:
        code_name = ((r['code'] + " " + r['name']).strip())[:80]
        e_pct = (r['expected'] / denom) * 100
        c_pct = (r['current'] / denom) * 100
        rows_html.append(f"<div class='line'><div class='label'>{code_name}</div>"
                         f"<div class='bar expected' style='width:{e_pct:.4f}%' title='Expected: {r['expected']:.2f} ({e_pct:.2f}%)'></div>"
                         f"<div class='bar current' style='width:{c_pct:.4f}%' title='Current: {r['current']:.2f} ({c_pct:.2f}%)'></div>"
                         f"<div class='vals'>E:{r['expected']:.2f} C:{r['current']:.2f} Δ:{r['diff']:.2f}</div></div>")
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Per-instrument Reconcile</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;padding:14px;background:#fafafa}}
.container{{max-width:1100px;margin:0 auto}}
.line{{display:flex;align-items:center;margin:6px 0;padding:6px;background:#fff;border-radius:6px;box-shadow:0 1px 2px rgba(0,0,0,0.04)}}
.label{{width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-right:8px}}
.bar{{height:28px;border-radius:4px;margin-right:2px;opacity:0.95}}
.expected{{background:#2b8a3e}}
.current{{background:#c0392b}}
.vals{{margin-left:8px;color:#333;font-size:13px;}}
.header{{margin-bottom:12px;font-weight:700}}
</style>
</head><body>
<div class="container">
  <div class="header">Per-instrument Reconcile (denom = {denom:.2f})</div>
  {"".join(rows_html)}
  <div style="margin-top:12px;color:#666;font-size:13px">Each bar width is percent of denom (account total asset by default).</div>
</div>
</body></html>
"""
    with open(outpath, 'w', encoding='utf-8') as f:
        f.write(html)
    return outpath


def main():
    parser = argparse.ArgumentParser(description="Per-instrument symbolic reconcile viewer")
    parser.add_argument('--json', help='reconcile JSON file (generate_reconcile_report output)')
    parser.add_argument('--account', help='account id to call generate_reconcile_report when running in repo', default=None)
    parser.add_argument('--blocks', type=int, default=24, help='number of character blocks for each bar')
    parser.add_argument('--scale', choices=('total', 'row', 'maxrow'), default='total',
                        help="scaling: 'total' uses total_asset; 'row' scale per row; 'maxrow' scale by max across rows")
    parser.add_argument('--color', action='store_true', help='enable ANSI color output')
    parser.add_argument('--filter', help='filter rows by code or name substring (case-insensitive)')
    parser.add_argument('--top', type=int, default=0, help='show top N by abs(diff); 0 = all')
    parser.add_argument('--out', help='emit simple HTML file (path)', default=None)
    args = parser.parse_args()

    report = None
    if args.json:
        report = load_json(args.json)
        if not report:
            print("Failed to load JSON:", args.json, file=sys.stderr)
            return
    elif args.account:
        report = load_report_from_account(args.account)
        if not report:
            print("Failed to generate report for account", args.account, file=sys.stderr)
            return
    else:
        print("Provide --json or --account", file=sys.stderr)
        return

    total_asset, rows = normalize_rows(report)
    if not rows:
        print("No rows found in report", file=sys.stderr)
        return

    if args.scale == 'total':
        denom = total_asset if total_asset > 0 else max(max(r['expected'], r['current']) for r in rows) or 1.0
    elif args.scale == 'maxrow':
        denom = max(max(r['expected'], r['current']) for r in rows) or 1.0
    else:
        denom = total_asset if total_asset > 0 else max(max(r['expected'], r['current']) for r in rows) or 1.0

    rows_sorted = sorted(rows, key=lambda r: r['absdiff'], reverse=True)
    if args.top and args.top > 0:
        rows_sorted = rows_sorted[:args.top]
    if args.filter:
        f = args.filter.lower()
        rows_sorted = [r for r in rows_sorted if f in (r['code'] + ' ' + r['name']).lower()]

    print("\nPer-instrument compare (symbolic bars)\n")
    print(f"Total asset (denom): {total_asset:.2f}    scale mode: {args.scale}    blocks: {args.blocks}\n")

    for r in rows_sorted:
        line_denom = denom if args.scale != 'row' else max(r['expected'], r['current'], 1.0)
        print(render_line(r, line_denom, args.blocks, color=args.color, scale_mode=args.scale))

    if args.out:
        outpath = gen_html(rows_sorted, total_asset if args.scale != 'row' else denom, args.out)
        print("\nHTML written to:", outpath)


if __name__ == '__main__':
    main()