#!/usr/bin/env python3
"""
扫描仓库内可能可删除或需 review 的测试文件（启发式）。
输出 JSON 与可读表格，包含每个候选的判断依据与 git 最后修改信息。

用法：
  python scripts/find_candidate_tests.py

（脚本不会删除任何文件，仅生成建议）
"""
import os, re, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 要搜索的测试文件 glob 模式
TEST_PATTERNS = ["**/test_*.py", "**/*_test.py", "**/tests/**/*.py", "**/test/**/*.py"]

def git_last_change_info(path: Path):
    try:
        # author|date|timestamp
        out = subprocess.check_output(
            ["git", "log", "-1", "--pretty=format:%an|%ad|%H", "--", str(path)],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
        if out:
            author, date, sha = out.split("|", 2)
            return {"author": author, "date": date, "sha": sha}
    except Exception:
        pass
    return {}

def analyze_test_file(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = [l.rstrip() for l in text.splitlines()]
    s = "\n".join(lines)[:10000]

    reasons = []
    score = 0

    # empty or only comments/whitespace
    nonblank = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    if not nonblank:
        reasons.append("文件仅包含注释或空行（可能占位）")
        score += 5

    # only trivial asserts or pass
    nontrivial = [l for l in nonblank if not re.match(r'^(pass|assert\s+True\b|assert\s+1\b|#)', l)]
    if not nontrivial:
        reasons.append("仅包含 pass 或 永真断言，测试可能未实现")
        score += 4

    # contains TODO markers
    if re.search(r'\bTODO\b|\b待实现\b|\bFIXME\b', s, re.I):
        reasons.append("包含 TODO/FIXME/待实现 标记")
        score += 1

    # skip/xfail markers at file or function level
    if re.search(r'@pytest\.mark\.(skip|skipif|xfail)|pytest\.skip\(', s):
        reasons.append("包含 skip/xfail 标记（可能已弃用或临时禁用）")
        score += 2

    # imports that might fail (module no longer present)
    imported = re.findall(r'^\s*(?:import|from)\s+([A-Za-z0-9_.]+)', s, flags=re.M)
    missing_imports = []
    for im in set(imported):
        # ignore stdlib likely modules heuristically by checking file exists in repo (module path)
        mod_path = im.replace(".", "/") + ".py"
        if (ROOT / mod_path).exists():
            continue
        # quick heuristic: if no top-level package folder that matches import name, mark as possibly missing
        top = im.split(".")[0]
        if not (ROOT / top).exists():
            missing_imports.append(im)
    if missing_imports:
        reasons.append(f"导入潜在缺失模块: {', '.join(missing_imports)}")
        score += 3

    # no asserts in file (may be utility only)
    if not re.search(r'\bassert\b', s):
        reasons.append("文件中未发现 assert（可能是工具/辅助脚本而非测试）")
        score += 2

    # file age via git
    gitinfo = git_last_change_info(path)
    # score bonus if file not modified in > 12 months
    try:
        if gitinfo.get("date"):
            # rough check: if date string contains year and older than 1 year from now
            import datetime
            year_match = re.search(r'(\d{4})', gitinfo["date"])
            if year_match:
                year = int(year_match.group(1))
                if year <= (datetime.datetime.now().year - 1):
                    reasons.append("长时间未修改（>1年）")
                    score += 1
    except Exception:
        pass

    return {
        "path": str(path.relative_to(ROOT)),
        "score": score,
        "reasons": reasons,
        "git": gitinfo,
    }

def main():
    candidates = []
    seen = set()
    for pat in TEST_PATTERNS:
        for p in ROOT.glob(pat):
            if p.is_file():
                candidates.append(p)
                seen.add(p)

    results = []
    for p in sorted(list(seen)):
        res = analyze_test_file(p)
        results.append(res)

    # sort by descending score (higher likely to be removable)
    results.sort(key=lambda r: r["score"], reverse=True)

    out_json = {"generated_by": "find_candidate_tests.py", "root": str(ROOT), "candidates": results}
    out_path = ROOT / "reports" / "candidate_tests_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已生成报告:", out_path)
    # also print top candidates
    for r in results[:40]:
        print(f"{r['score']:>2}  {r['path']}")
        for reason in r["reasons"]:
            print("     -", reason)
        if r.get("git"):
            print("     git:", r["git"])
        print()

if __name__ == "__main__":
    main()