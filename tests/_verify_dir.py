import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import timeparse as t
from datetime import datetime
ref = datetime(2026, 8, 3)

tests = [
    ('活动时间:8月15日~', 'date~ -> [start,None]', (('08-15',), (None,))),
    ('活动时间:~8月15日', '~date -> [ref,end]', (('08-03',), ('08-15',))),
    ('版本更新后~8月15日', 'ver~date -> [ref,end]', (('08-03',), ('08-15',))),
    ('活动时间:8月10日 ~ 8月20日', 'range -> [s,e]', (('08-10',), ('08-20',))),
    ('活动时间:8月10日', 'single -> [s,None]', (('08-10',), (None,))),
    ('本次嘉年华将于7月10日开启，至7月20日结束', 'natural -> [s,e]', (('07-10',), ('07-20',))),
]

all_ok = True
for text, desc, expect in tests:
    s, e = t.extract_range(text, ref)
    sf = s.strftime('%m-%d') if s else None
    ef = e.strftime('%m-%d') if e else None
    sexp = expect[0][0] if expect[0][0] else None
    eexp = expect[1][0] if expect[1][0] else None
    ok = sf == sexp and ef == eexp
    all_ok = all_ok and ok
    status = 'PASS' if ok else 'FAIL'
    print(f"{status} {desc}: got=({sf}, {ef}) expect=({sexp}, {eexp})")

print('\nALL PASS' if all_ok else '\nSOME FAILED')
