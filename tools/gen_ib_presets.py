import re, sys, shutil
# 用法: python3 gen_ib_presets.py <addons/sourcemod/data/l4dinfectedbots>
# 重写 coop.cfg/realism.cfg 为“按存活人数 4→16 特感”的 auto 表，并生成 te8/te12/te16 固定预设（sipreset 插件使用）
d = sys.argv[1].rstrip('/')
auto = {1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8,9:10,10:12,11:14}          # >=12 -> 16
def spawn_for(n): return (40,60) if n<=4 else (35,55) if n<=6 else (30,50) if n<=8 else (25,45) if n<=10 else (20,40)
def set_key(block, key, val):
    return re.sub(r'("%s"\s+")[^"]*(")' % re.escape(key), lambda m: m.group(1)+str(val)+m.group(2), block, count=1)
def patch(text, fixed=None, spawn=None):
    def repl(m):
        sec = int(m.group(1)); b = m.group(2)
        n = fixed if fixed else auto.get(sec, 16)
        per = 3 if n > 12 else 2 if n <= 8 else 3
        for t in ('smoker','boomer','hunter','spitter','jockey','charger'):
            b = set_key(b, t+'_limit', per)
        b = set_key(b, 'max_specials', n)
        smin, smax = spawn if spawn else spawn_for(sec)
        b = set_key(b, 'spawn_time_min', '%.1f' % smin); b = set_key(b, 'spawn_time_max', '%.1f' % smax)
        b = set_key(b, 'tank_limit', 1 if sec >= 4 else 0)
        return '"%d"%s' % (sec, b)
    return re.sub(r'"(\d+)"(\s*\{.*?\n\s*\})', repl, text, flags=re.S)
for mode in ('coop','realism'):
    p = f'{d}/{mode}.cfg'; s = open(p, encoding='utf-8').read()
    open(p,'w',encoding='utf-8').write(patch(s)); print(mode, 'auto table written')
base = open(f'{d}/coop.cfg', encoding='utf-8').read()
for name, n, sp in (('te8',8,(30,50)),('te12',12,(25,45)),('te16',16,(20,40))):
    open(f'{d}/{name}.cfg','w',encoding='utf-8').write(patch(base, fixed=n, spawn=sp)); print(name, 'preset written')
# verify
s = open(f'{d}/coop.cfg', encoding='utf-8').read()
out=[]
for sec in (4,6,8,10,12,31):
    m = re.search(r'"%d"\s*\{(.*?)\n\s*\}' % sec, s, re.S); b = m.group(1)
    g = lambda k: re.search(r'"%s"\s+"([^"]+)"' % k, b).group(1)
    out.append(f"{sec}人:特{g('max_specials')} 每种{g('hunter_limit')} 刷{g('spawn_time_min')}-{g('spawn_time_max')}s Tank{g('tank_limit')}x{g('tank_health')}")
print('\n'.join(out))
