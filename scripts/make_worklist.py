"""
make_worklist.py
================
Builds a spreadsheet for checking listings by hand: every listing, sorted by
how soon its next deadline is likely to be, with columns for recording what
was found and where.

Usage:
    python scripts/make_worklist.py [--data data/fellowships_master.json] [--out worklists/worklist.xlsx]

Requirements:
    pip install openpyxl
"""
import argparse, json, datetime, calendar, re
from collections import Counter
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import FormulaRule
from openpyxl.utils import get_column_letter

ap = argparse.ArgumentParser()
ap.add_argument('--data', default='data/fellowships_master.json')
ap.add_argument('--out')
args = ap.parse_args()
TODAY = datetime.date.today()
STALE_DAYS = 550
recs = json.load(open(args.data))

def parse(s):
    try:
        d = datetime.date.fromisoformat(s or '')
        return None if d.year == 9999 else d
    except ValueError:
        return None

def same_day(d, y):
    return datetime.date(y, d.month, min(d.day, calendar.monthrange(y, d.month)[1]))

PRI = {
    1: ('1 - Check now', 'Deadline on file has passed; next one estimated within 90 days'),
    2: ('2 - Next', 'Deadline on file has passed; next one estimated in 3-6 months'),
    3: ('3 - Later', 'Deadline on file has passed; next one estimated 6+ months out'),
    4: ('4 - Find a date', 'No deadline on file, or last deadline over 18 months old (not rolling)'),
    5: ('5 - Rolling', 'Rolling / open program: confirm it is still running'),
    6: ('6 - Current', 'Deadline on file is still upcoming: quick spot check only'),
}

rows = []
for r in recs:
    last = parse(r.get('deadlineSort'))
    nxt, est = None, False
    if not last:
        p = 5 if r.get('season') == 'Open/Rolling' else 4
    elif last >= TODAY:
        nxt, p = last, 6
    elif (TODAY - last).days > STALE_DAYS:
        p = 4
    else:
        y = last.year
        while True:
            y += 1
            nxt = same_day(last, y)
            if nxt >= TODAY:
                break
        est = True
        days = (nxt - TODAY).days
        p = 1 if days <= 90 else 2 if days <= 180 else 3
    rows.append((p, nxt or datetime.date(9999, 1, 1), r['title'].lower(), r, last, nxt))
rows.sort(key=lambda x: x[:3])

wb = Workbook()
F = 'Arial'
base = Font(name=F, size=10)
bold = Font(name=F, size=10, bold=True)
hdr_font = Font(name=F, size=10, bold=True, color='FFFFFF')
hdr_fill = PatternFill('solid', fgColor='2D68C4')
in_hdr_fill = PatternFill('solid', fgColor='B7791F')
in_fill = PatternFill('solid', fgColor='FFF7D6')
thin = Side(style='thin', color='D0D0D0')
border = Border(bottom=thin)
link_font = Font(name=F, size=10, color='0563C1', underline='single')
STATUSES = ['Updated', 'No change needed', 'Not posted yet', 'Discontinued / paused', 'Link broken - new link found', 'Link broken - not found']

# A distinctive word from each title, since the backend searches by program
# name and works best with a single word: the word that appears in the
# fewest other titles.
GENERIC = {'fellowship', 'fellowships', 'program', 'programs', 'graduate', 'research', 'postdoctoral',
           'doctoral', 'predoctoral', 'award', 'awards', 'grant', 'grants', 'scholarship', 'scholarships',
           'dissertation', 'student', 'students', 'foundation', 'national', 'american', 'international',
           'center', 'institute', 'society', 'association', 'for', 'the', 'and', 'with', 'from', 'study',
           'studies', 'summer', 'travel', 'early', 'career', 'science', 'sciences', 'university', 'ucla'}
def words(t):
    # Apostrophes are left out ("Provost's" becomes "Provost") since the backend
    # may store a curly apostrophe that a typed one won't match
    return re.findall(r"[A-Za-z][A-Za-z&.-]*[A-Za-z]", t or '')
freq = Counter(w.lower() for r in recs for w in set(words(r['title'])))
def search_word(r):
    cands = [w for w in words(r['title']) if w.lower() not in GENERIC and len(w) >= 3]
    if not cands:
        cands = [w for w in words(r.get('agency1')) if w.lower() not in GENERIC and len(w) >= 3]
    if not cands:
        return ''
    return min(cands, key=lambda w: (freq.get(w.lower(), 0), -len(w)))

def backend_website(url):
    """The backend's Website field wants no http:// or https://."""
    return re.sub(r'^https?://', '', url or '')

# ---------------- How to use ----------------
ws0 = wb.active
ws0.title = 'How to use'
ws0.sheet_view.showGridLines = False
lines = [
    ('GRAPES manual update worklist', Font(name=F, size=14, bold=True)),
    (f'Built {TODAY:%B %d, %Y} from the GRAPES Search+ site data ({len(recs)} listings).', base),
    ('', base),
    ('How to use', bold),
    ('1. Work down the Worklist tab in order. It is sorted by priority, then by the soonest estimated deadline.', base),
    ('2. In the GRAPES Admin Update form, search for the Search word, and open the record with the matching Record Number.', base),
    ('3. Check that the backend record is the same program as the Title here, then fill in "Backend record matches?".', base),
    ('   If the search finds nothing, try another word from the title. If it is a different program, pick No,', base),
    ('   note the backend title in Notes, and skip to the next row.', base),
    ('4. Open the official link, find the current details, and update the record in the backend.', base),
    ('5. Fill in the yellow columns. Leave a cell blank if nothing changed. Always paste the page you used in Source link:', base),
    ('   these answers will be the test set for the AI agent pilot.', base),
    ('6. Pick a Status from the dropdown. The Summary tab tracks progress automatically.', base),
    ('', base),
    ('Columns', bold),
    ('Blue-header columns come from the site data. Do not edit them.', base),
    ('Yellow columns are yours to fill in.', base),
    ('"Website (backend format)" is the official link without http:// or https://, ready to paste into the backend Website field.', base),
    ('"Estimated next deadline" rolls the last known deadline forward a year. It is a guess to help prioritize, not a confirmed date.', base),
    ('"Days left" counts from today and updates when the file is opened.', base),
    ('', base),
    ('Priorities', bold),
]
for k, (name, desc) in PRI.items():
    lines.append((f'{name}: {desc}', base))
lines += [
    ('', base),
    ('Caveat', bold),
    ('This list comes from the public site, not the backend. The two can disagree: record 1049 is "Clark Predoctoral Fellowship" here', base),
    ('but "Ahmanson-Getty Postdoctoral Fellowship" in the backend. Always confirm the program before editing, and trust the backend.', base),
    ('', base),
    ('Example of a completed row (yellow columns)', bold),
]
for i, (t, f) in enumerate(lines, 1):
    c = ws0.cell(row=i, column=1, value=t)
    c.font = f
ex_r = len(lines) + 1
ex_hdr = ['Backend record matches?', 'New deadline', 'New amount', 'Source link', 'Status', 'Notes', 'Checked by', 'Date checked']
ex_val = ['Yes', datetime.date(2026, 11, 1), '$30,000 stipend', 'https://www.lbi.org/about/fellowships/lbi-daad-fellowships/',
          'Updated', 'Second deadline May 1 for spring cycle', 'DW', datetime.date(2026, 10, 13)]
for j, (h, v) in enumerate(zip(ex_hdr, ex_val), 1):
    hc = ws0.cell(row=ex_r, column=j, value=h); hc.font = hdr_font; hc.fill = in_hdr_fill
    hc.alignment = Alignment(wrap_text=True)
    vc = ws0.cell(row=ex_r + 1, column=j, value=v); vc.font = base; vc.fill = in_fill
    if isinstance(v, datetime.date):
        vc.number_format = 'mmm d, yyyy'
ws0.column_dimensions['A'].width = 16
for col, w in zip('BCDEFGH', [14, 18, 40, 16, 34, 12, 14]):
    ws0.column_dimensions[col].width = w

# ---------------- Worklist ----------------
ws = wb.create_sheet('Worklist')
cols = [
    ('Priority', 16), ('Record #', 9), ('Search word', 14), ('Title', 44), ('Sponsor', 30),
    ('Site status', 12), ('Season', 11), ('Deadline on file', 15), ('Estimated next deadline', 15),
    ('Days left', 9), ('Amount on file', 22), ('Official link', 12), ('Website (backend format)', 36),
    ('Backend record matches?', 13), ('New deadline', 14), ('New amount', 18), ('Source link', 30),
    ('Status', 24), ('Notes', 36), ('Checked by', 11), ('Date checked', 13),
]
C = {h: j for j, (h, _) in enumerate(cols, 1)}
L = {h: get_column_letter(j) for h, j in C.items()}
FIRST_INPUT = C['Backend record matches?']
for j, (h, w) in enumerate(cols, 1):
    c = ws.cell(row=1, column=j, value=h)
    c.font = hdr_font
    c.fill = in_hdr_fill if j >= FIRST_INPUT else hdr_fill
    c.alignment = Alignment(wrap_text=True, vertical='center')
    ws.column_dimensions[get_column_letter(j)].width = w
ws.row_dimensions[1].height = 30

wrap = {C['Title'], C['Sponsor'], C['Amount on file'], C['Source link'], C['Notes']}
for i, (p, _, _, r, last, nxt) in enumerate(rows, 2):
    est = L['Estimated next deadline']
    vals = {
        'Priority': PRI[p][0], 'Record #': r['id'], 'Search word': search_word(r), 'Title': r['title'],
        'Sponsor': r.get('agency1', ''),
        'Site status': 'Verified' if r.get('status') == 'Published' else 'Unverified',
        'Season': r.get('season', ''), 'Deadline on file': last,
        'Estimated next deadline': nxt if p in (1, 2, 3, 6) else None,
        'Days left': f'=IF({est}{i}="","",{est}{i}-TODAY())',
        'Amount on file': r.get('amount') or '',
        'Website (backend format)': backend_website(r.get('officialUrl')),
    }
    for h, j in C.items():
        c = ws.cell(row=i, column=j, value=vals.get(h))
        c.font = base
        c.border = border
        c.alignment = Alignment(vertical='top', wrap_text=j in wrap)
        if j >= FIRST_INPUT:
            c.fill = in_fill
    for h in ('Deadline on file', 'Estimated next deadline', 'New deadline', 'Date checked'):
        ws.cell(row=i, column=C[h]).number_format = 'mmm d, yyyy'
    ws.cell(row=i, column=C['Days left']).number_format = '0;-0;0'
    url = r.get('officialUrl') or ''
    if url:
        lc = ws.cell(row=i, column=C['Official link'], value='Open page')
        lc.hyperlink = url
        lc.font = link_font

n = len(rows) + 1
def col_range(h):
    return f'{L[h]}2:{L[h]}{n}'
dv = DataValidation(type='list', formula1='"' + ','.join(STATUSES) + '"', allow_blank=True)
dv.error = 'Pick a status from the list'
dv.errorTitle = 'Status'
ws.add_data_validation(dv)
dv.add(col_range('Status'))
dvm = DataValidation(type='list', formula1='"Yes,No"', allow_blank=True)
ws.add_data_validation(dvm)
dvm.add(col_range('Backend record matches?'))
dvd = DataValidation(type='date', operator='greaterThan', formula1='DATE(2020,1,1)', allow_blank=True)
dvd.error = 'Enter a date, e.g. 11/1/2026'
ws.add_data_validation(dvd)
dvd.add(col_range('New deadline')); dvd.add(col_range('Date checked'))
# Shade rows green once a status is picked, red when the backend record is a different program
last_data = get_column_letter(FIRST_INPUT - 1)
ws.conditional_formatting.add(f'A2:{last_data}{n}', FormulaRule(
    formula=[f'${L["Backend record matches?"]}2="No"'], fill=PatternFill('solid', fgColor='FBE3E3'), stopIfTrue=True))
ws.conditional_formatting.add(f'A2:{last_data}{n}', FormulaRule(
    formula=[f'${L["Status"]}2<>""'], fill=PatternFill('solid', fgColor='E8F3EA')))
ws.freeze_panes = 'E2'
ws.auto_filter.ref = f'A1:{get_column_letter(len(cols))}{n}'

# ---------------- Summary ----------------
ss = wb.create_sheet('Summary')
ss.sheet_view.showGridLines = False
ss['A1'] = 'Progress'; ss['A1'].font = Font(name=F, size=14, bold=True)
PCOL = f'Worklist!${L["Priority"]}$2:${L["Priority"]}${n}'
SCOL = f'Worklist!${L["Status"]}$2:${L["Status"]}${n}'
MCOL = f'Worklist!${L["Backend record matches?"]}$2:${L["Backend record matches?"]}${n}'
heads = ['Priority', 'Listings', 'Checked', 'Remaining', '% done']
for j, h in enumerate(heads, 1):
    c = ss.cell(row=3, column=j, value=h); c.font = hdr_font; c.fill = hdr_fill
for k, (p, (name, _)) in enumerate(PRI.items(), 4):
    ss.cell(row=k, column=1, value=name)
    ss.cell(row=k, column=2, value=f'=COUNTIF({PCOL},A{k})')
    ss.cell(row=k, column=3, value=f'=COUNTIFS({PCOL},A{k},{SCOL},"<>")')
    ss.cell(row=k, column=4, value=f'=B{k}-C{k}')
    ss.cell(row=k, column=5, value=f'=IF(B{k}=0,0,C{k}/B{k})')
tot = 4 + len(PRI)
ss.cell(row=tot, column=1, value='Total')
for col in 'BCD':
    ss[f'{col}{tot}'] = f'=SUM({col}4:{col}{tot-1})'
ss[f'E{tot}'] = f'=IF(B{tot}=0,0,C{tot}/B{tot})'
for rr in range(4, tot + 1):
    for cc in range(1, 6):
        c = ss.cell(row=rr, column=cc); c.font = bold if rr == tot else base
    ss.cell(row=rr, column=5).number_format = '0%'
sr = tot + 2
ss.cell(row=sr, column=1, value='By status').font = bold
for j, h in enumerate(['Status', 'Count'], 1):
    c = ss.cell(row=sr + 1, column=j, value=h); c.font = hdr_font; c.fill = hdr_fill
for k, s in enumerate(STATUSES, sr + 2):
    ss.cell(row=k, column=1, value=s).font = base
    c = ss.cell(row=k, column=2, value=f'=COUNTIF({SCOL},A{k})'); c.font = base
mr = sr + 3 + len(STATUSES)
ss.cell(row=mr, column=1, value='Site vs. backend').font = bold
for j, h in enumerate(['Backend record matches?', 'Count'], 1):
    c = ss.cell(row=mr + 1, column=j, value=h); c.font = hdr_font; c.fill = hdr_fill
for k, v in enumerate(['Yes', 'No'], mr + 2):
    ss.cell(row=k, column=1, value=v).font = base
    c = ss.cell(row=k, column=2, value=f'=COUNTIF({MCOL},A{k})'); c.font = base
ss.column_dimensions['A'].width = 30
for col in 'BCDE':
    ss.column_dimensions[col].width = 12

out = args.out or f'worklists/grapes_update_worklist_{TODAY:%Y-%m}.xlsx'
wb.save(out)
print(f'Saved {out}')
for name, count in sorted(Counter(PRI[x[0]][0] for x in rows).items()):
    print(f'  {name}: {count}')
