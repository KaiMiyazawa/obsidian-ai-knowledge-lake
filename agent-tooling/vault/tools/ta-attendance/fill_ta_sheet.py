#!/usr/bin/env python3
"""大学の TA 出勤表（事務から配布される Excel）に、1か月分の勤務実績を書き込む。

openpyxl で保存するとシート内の図形（drawings）が消えるため、xlsx の XML を直接書き換える。
手順と前提は 保管庫内の TA 業務のノート を参照。

使い方:
  python3 fill_ta_sheet.py OUT.xlsx --year 2026 --month 10 \
      --rate 1350 --student-number 3826C098 --faculty "牧野 遼作" \
      --work 7=10:40-12:40 --work 14=10:40-12:40

2026年10月以降専用。公式テンプレートを固定で使用し、前月の出勤表は流用しない。
"""

import argparse
import datetime as dt
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

SHEET = "xl/worksheets/sheet1.xml"  # 1枚目「TA出勤表」。2枚目は記入例なので触らない
LEFT_ROWS = [7 + 2 * k for k in range(16)]   # 1〜16日: B/D=日付, E=開始, G=終了, H=時間数
RIGHT_ROWS = [7 + 2 * k for k in range(15)]  # 17〜31日: I/K=日付, L=開始, N=終了, O=時間数
TEMPLATE = Path(__file__).resolve().parents[2] / "10_work/ta/documents/attendance-template.xlsx"


def excel_serial(d: dt.date) -> int:
    return (d - dt.date(1899, 12, 30)).days


def slot(day: int):
    """日付から (行, 開始列, 終了列, 時間数列) を返す。"""
    if 1 <= day <= 16:
        return LEFT_ROWS[day - 1], "E", "G", "H"
    if 17 <= day <= 31:
        return RIGHT_ROWS[day - 17], "L", "N", "O"
    raise ValueError(day)


def set_cell(xml: str, ref: str, inner: str, style: int | None = None, cell_type: str | None = None) -> str:
    pat = re.compile(rf'<c r="{ref}"(?P<attrs>[^>]*?)(?:/>|>.*?</c>)', re.S)
    m = pat.search(xml)
    if not m:
        raise KeyError(f"cell {ref} not found")
    attrs = re.sub(r'\s(t)="[^"]*"', "", m.group("attrs"))
    if style is not None:
        attrs = re.sub(r'\ss="\d+"', f' s="{style}"', attrs)
    if cell_type:
        attrs += f' t="{cell_type}"'
    new = f'<c r="{ref}"{attrs}/>' if not inner else f'<c r="{ref}"{attrs}>{inner}</c>'
    return xml[: m.start()] + new + xml[m.end():]


def set_cached(xml: str, ref: str, value) -> str:
    """数式セルのキャッシュ値だけ差し替える（数式は残す）。"""
    pat = re.compile(rf'(<c r="{ref}"[^>]*>(?:<f\b[^>]*?/>|<f\b[^>]*>.*?</f>))(?:<v>.*?</v>)?(</c>)', re.S)
    xml, n = pat.subn(rf"\g<1><v>{value}</v>\g<2>", xml)
    if n != 1:
        raise KeyError(f"formula cell {ref} not found")
    return xml


def parse_work(s: str):
    day, span = s.split("=")
    a, b = span.split("-")
    t0 = dt.datetime.strptime(a, "%H:%M")
    t1 = dt.datetime.strptime(b, "%H:%M")
    hours = (t1 - t0).seconds / 3600
    return int(day), t0, t1, hours


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--month", type=int, required=True)
    p.add_argument("--rate", type=int, required=True, help="時給（円）。2026-10-01以降は1350")
    p.add_argument("--student-number", default="3826C098")
    p.add_argument("--name", default="氏名")
    p.add_argument("--faculty", required=True, help='授業担当者氏名。例: "牧野 遼作"')
    p.add_argument("--work", action="append", default=[], help="DD=HH:MM-HH:MM。勤務した日だけ指定")
    args = p.parse_args()
    if (args.year, args.month) < (2026, 10) or args.rate != 1350:
        p.error("公式テンプレートは2026年10月以降・時給1350円専用です")
    if Path(args.out).resolve() == TEMPLATE.resolve():
        p.error("公式テンプレートは出力先に指定できません")

    works = [parse_work(w) for w in args.work]
    first = dt.date(args.year, args.month, 1)
    for day, *_ in works:
        dt.date(args.year, args.month, day)  # 存在しない日付ならここで落ちる

    with zipfile.ZipFile(TEMPLATE) as z:
        files = {n: z.read(n) for n in z.namelist()}
        order = z.namelist()
    xml = files[SHEET].decode("utf-8")

    xml = set_cell(xml, "E3", f"<v>{args.year}</v>")
    xml = set_cell(xml, "G3", f"<v>{args.month}</v>")
    xml = set_cell(xml, "M3", f"<is><t>{escape(args.name)}</t></is>", cell_type="inlineStr")
    xml = set_cell(xml, "M4", f"<is><t>{escape(args.student_number)}</t></is>", cell_type="inlineStr")
    xml = set_cell(xml, "E40", f"<is><t>{escape(args.faculty)}</t></is>", cell_type="inlineStr")

    # 既存の記入を消す
    for day in range(1, 32):
        r, cs, ce, ch = slot(day)
        xml = set_cell(xml, f"{cs}{r}", "")
        xml = set_cell(xml, f"{ce}{r}", "")
        xml = set_cell(xml, f"{ch}{r}", "")

    total = 0.0
    for day, t0, t1, hours in works:
        r, cs, ce, ch = slot(day)
        frac = lambda t: (t.hour * 60 + t.minute) / 1440
        xml = set_cell(xml, f"{cs}{r}", f"<v>{frac(t0)}</v>")
        xml = set_cell(xml, f"{ce}{r}", f"<v>{frac(t1)}</v>")
        xml = set_cell(xml, f"{ch}{r}", f"<v>{hours}</v>")
        total += hours

    # 時給は数式と注記の両方に直書きされているので差し替える
    xml = set_cell(xml, "N40", f"<f>N37*{args.rate}</f><v>{int(total * args.rate)}</v>")
    note = f" 日数(Number of working dates)：\n*時給{args.rate:,}円 ({args.rate:,} yen per hour)"
    xml = set_cell(xml, "I39", f'<is><t xml:space="preserve">{escape(note)}</t></is>', cell_type="inlineStr")

    # 日付などのキャッシュ値を対象月に合わせる（開いたとき再計算もさせる）
    for k, r in enumerate(LEFT_ROWS):
        v = excel_serial(first) + k
        xml = set_cached(set_cached(xml, f"B{r}", v), f"D{r}", v)
    for k, r in enumerate(RIGHT_ROWS):
        v = excel_serial(first) + 16 + k
        xml = set_cached(set_cached(xml, f"I{r}", v), f"K{r}", v)
    xml = set_cached(xml, "N37", total)
    xml = set_cached(xml, "N39", len(works))
    files[SHEET] = xml.encode("utf-8")

    wb = files["xl/workbook.xml"].decode("utf-8")
    wb = re.sub(r"<calcPr[^>]*/>", '<calcPr fullCalcOnLoad="1"/>', wb)
    files["xl/workbook.xml"] = wb.encode("utf-8")

    tmp = Path(tempfile.mkdtemp()) / "out.xlsx"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in order:
            z.writestr(n, files[n])
    shutil.move(tmp, args.out)

    print(f"{args.year}年{args.month}月: {len(works)}日, {total}時間, {int(total * args.rate):,}円 (時給{args.rate})")
    for day, t0, t1, hours in sorted(works):
        d = dt.date(args.year, args.month, day)
        print(f"  {d:%m/%d}({'月火水木金土日'[d.weekday()]}) {t0:%H:%M}-{t1:%H:%M} {hours}h")


if __name__ == "__main__":
    sys.exit(main())
