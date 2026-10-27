"""
format_v4.py — Fixed position tracking: re-syncs from document after every write.
"""
import json, urllib.request, urllib.error, subprocess, re, sys, time

def get_token():
    r = subprocess.run(['bash', '/root/nanoclaw/scripts/google-refresh.sh'],
                       capture_output=True, text=True)
    return r.stdout.strip()

TOKEN = get_token()

def api(method, url, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', f'Bearer {TOKEN}')
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())

def doc_end(doc_id):
    """Return current end_index of document body."""
    doc = api('GET', f'https://docs.googleapis.com/v1/documents/{doc_id}')
    body = doc.get('body', {}).get('content', [])
    return max((el.get('endIndex', 1) for el in body), default=2), doc

def safe_batch(doc_id, requests):
    """Execute batch, retrying on quota. Returns True on success."""
    if not requests:
        return True
    CHUNK = 50
    for i in range(0, len(requests), CHUNK):
        chunk = requests[i:i+CHUNK]
        for attempt in range(8):
            r = api('POST', f'https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate',
                    {'requests': chunk})
            if 'error' in r:
                msg = r['error'].get('message','')
                if 'Quota' in msg:
                    wait = 30 * (2 ** attempt)
                    print(f'  [quota] waiting {wait}s...', flush=True)
                    time.sleep(min(wait, 120))
                    continue
                print(f'  [err] {msg[:100]}', flush=True)
                return False
            break
        else:
            print('  [fail] max retries hit', flush=True)
            return False
        time.sleep(2)
    return True

# ── Inline markdown ───────────────────────────────────────────────────────────
def process_inline(text):
    segs, out, i = [], [], 0
    while i < len(text):
        if text[i:i+3] == '***':
            end = text.find('***', i+3)
            if end != -1:
                s = len(''.join(out)); inner = text[i+3:end]
                out.append(inner); segs.append((s, s+len(inner), 'bold_italic'))
                i = end+3; continue
        if text[i:i+2] == '**':
            end = text.find('**', i+2)
            if end != -1:
                s = len(''.join(out)); inner = text[i+2:end]
                out.append(inner); segs.append((s, s+len(inner), 'bold'))
                i = end+2; continue
        if text[i] == '`':
            end = text.find('`', i+1)
            if end != -1:
                s = len(''.join(out)); inner = text[i+1:end]
                out.append(inner); segs.append((s, s+len(inner), 'code'))
                i = end+1; continue
        m = re.match(r'\[([^\]]+)\]\([^\)]+\)', text[i:])
        if m:
            out.append(m.group(1)); i += len(m.group(0)); continue
        out.append(text[i]); i += 1
    return ''.join(out), segs

# ── Parser ────────────────────────────────────────────────────────────────────
def parse_markdown(content):
    lines = content.split('\n')
    blocks = []
    i = 0
    if lines and lines[0].strip() == '---':
        i = 1
        while i < len(lines) and lines[i].strip() != '---':
            i += 1
        i += 1
    in_code, code_buf = False, []
    while i < len(lines):
        line = lines[i]; stripped = line.strip()
        if stripped.startswith('```'):
            if not in_code: in_code = True; code_buf = []
            else:
                in_code = False
                blocks.append({'type':'code_block','text':'\n'.join(code_buf)})
            i += 1; continue
        if in_code: code_buf.append(line); i += 1; continue
        if not stripped or re.match(r'^[-=]{3,}$', stripped):
            if blocks and blocks[-1]['type'] != 'blank':
                blocks.append({'type':'blank'})
            i += 1; continue
        if stripped.startswith('|') and stripped.endswith('|'):
            tlines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                tlines.append(lines[i].strip()); i += 1
            headers, rows = None, []
            for tl in tlines:
                cells = [c.strip() for c in tl.strip('|').split('|')]
                if all(re.match(r'^[-: ]+$', c) for c in cells if c): continue
                clean = [process_inline(c)[0] for c in cells]
                if headers is None: headers = clean
                else: rows.append(clean)
            if headers: blocks.append({'type':'table','headers':headers,'rows':rows})
            continue
        m = re.match(r'^(#{1,3})\s+(.+)$', stripped)
        if m:
            clean,segs = process_inline(m.group(2))
            blocks.append({'type':f'h{len(m.group(1))}','text':clean,'segments':segs})
            i+=1; continue
        m = re.match(r'^>\s+(.+)$', stripped)
        if m:
            clean,segs = process_inline(m.group(1))
            blocks.append({'type':'blockquote','text':clean,'segments':segs})
            i+=1; continue
        m = re.match(r'^-\s+\[([ xX])\]\s+(.+)$', stripped)
        if m:
            tick = '☑ ' if m.group(1).lower()=='x' else '☐ '
            clean,segs = process_inline(m.group(2))
            segs = [(s+len(tick),e+len(tick),t) for s,e,t in segs]
            blocks.append({'type':'bullet','text':tick+clean,'segments':segs,'level':0})
            i+=1; continue
        m = re.match(r'^(\s*)[•*\-]\s+(.+)$', line)
        if m:
            clean,segs = process_inline(m.group(2))
            blocks.append({'type':'bullet','text':clean,'segments':segs,'level':len(m.group(1))//2})
            i+=1; continue
        m = re.match(r'^(\s*)\d+\.\s+(.+)$', line)
        if m:
            clean,segs = process_inline(m.group(2))
            blocks.append({'type':'numbered','text':clean,'segments':segs,'level':len(m.group(1))//2})
            i+=1; continue
        clean,segs = process_inline(stripped)
        if clean: blocks.append({'type':'paragraph','text':clean,'segments':segs})
        i+=1
    return blocks

# ── Style helpers ─────────────────────────────────────────────────────────────
MONO = 'Courier New'
def ps(s,e,ns): return {'updateParagraphStyle':{'range':{'startIndex':s,'endIndex':e},'paragraphStyle':{'namedStyleType':ns},'fields':'namedStyleType'}}
def ts(s,e,**kw):
    st,fields={},[]
    if 'bold' in kw: st['bold']=kw['bold']; fields.append('bold')
    if 'italic' in kw: st['italic']=kw['italic']; fields.append('italic')
    if 'font' in kw: st['weightedFontFamily']={'fontFamily':kw['font']}; fields.append('weightedFontFamily')
    if 'size' in kw: st['fontSize']={'magnitude':kw['size'],'unit':'PT'}; fields.append('fontSize')
    if 'color' in kw:
        r,g,b=kw['color']; st['foregroundColor']={'color':{'rgbColor':{'red':r,'green':g,'blue':b}}}; fields.append('foregroundColor')
    return {'updateTextStyle':{'range':{'startIndex':s,'endIndex':e},'textStyle':st,'fields':','.join(fields)}}
def inline_style(segs, base):
    r=[]
    for s,e,style in segs:
        a,b=base+s,base+e
        if style=='bold': r.append(ts(a,b,bold=True))
        elif style=='italic': r.append(ts(a,b,italic=True))
        elif style=='bold_italic': r.append(ts(a,b,bold=True,italic=True))
        elif style=='code': r.append(ts(a,b,font=MONO,size=9))
    return r

# ── Table ─────────────────────────────────────────────────────────────────────
def insert_table_block(doc_id, tblock, insert_at):
    """Insert table at insert_at; fill cells; return new end of document."""
    headers, rows = tblock['headers'], tblock['rows']
    ncols = len(headers)
    all_data = [headers] + rows
    for row in all_data:
        while len(row) < ncols: row.append('')
    nrows = len(all_data)

    # Insert table
    ok = safe_batch(doc_id, [{'insertTable':{'rows':nrows,'columns':ncols,'location':{'index':insert_at}}}])
    if not ok: return insert_at + 5
    time.sleep(3)

    # Read to find table and cells
    end, doc = doc_end(doc_id)
    tbl = None
    for el in doc.get('body',{}).get('content',[]):
        if 'table' in el and el.get('startIndex',0) >= insert_at-2:
            tbl = el; break
    if not tbl:
        print('  [warn] table not found', flush=True)
        return end - 1

    # Collect cells
    cells = []
    for r,row in enumerate(tbl['table'].get('tableRows',[])):
        for c,cell in enumerate(row.get('tableCells',[])):
            para_start = cell['content'][0]['startIndex']
            cells.append((r,c,para_start))

    # Fill BACKWARDS to preserve indices
    fills = []
    for (r,c,pstart) in reversed(cells):
        text = all_data[r][c] if r<len(all_data) and c<len(all_data[r]) else ''
        if text:
            fills.append({'insertText':{'location':{'index':pstart},'text':text}})
    if fills:
        safe_batch(doc_id, fills)
        time.sleep(3)

    # Re-read for styling
    end, doc = doc_end(doc_id)
    tbl = None
    for el in doc.get('body',{}).get('content',[]):
        if 'table' in el and el.get('startIndex',0) >= insert_at-2:
            tbl = el; break
    if tbl:
        style_reqs = []
        for r,row in enumerate(tbl['table'].get('tableRows',[])):
            for c,cell in enumerate(row.get('tableCells',[])):
                para = cell['content'][0]
                ts_start = para['startIndex']
                ts_end = para['endIndex']-1
                if ts_start < ts_end:
                    if r==0:
                        style_reqs.append(ts(ts_start,ts_end,bold=True))
                        style_reqs.append({'updateTableCellStyle':{
                            'tableRange':{'tableCellLocation':{
                                'tableStartLocation':{'index':tbl['startIndex']},
                                'rowIndex':0,'columnIndex':c},
                                'rowSpan':1,'columnSpan':1},
                            'tableCellStyle':{'backgroundColor':{'color':{'rgbColor':{
                                'red':0.878,'green':0.914,'blue':0.996}}}},
                            'fields':'backgroundColor'}})
        if style_reqs:
            safe_batch(doc_id, style_reqs)
        return tbl['endIndex']
    return end - 1

# ── Core formatter ────────────────────────────────────────────────────────────
def reformat(doc_id, md_content, title):
    print(f'\n▶ {title}', flush=True)
    blocks = parse_markdown(md_content)

    # Delete all content
    end, _ = doc_end(doc_id)
    if end > 2:
        safe_batch(doc_id, [{'deleteContentRange':{'range':{'startIndex':1,'endIndex':end-1}}}])
        time.sleep(3)

    # Verify delete worked
    pos, _ = doc_end(doc_id)
    pos = 1  # start inserting at index 1

    tbuf = []  # (text, para_style, segs, btype)

    def flush():
        nonlocal pos
        if not tbuf: return
        full = ''.join(t for t,_,_,_ in tbuf)
        reqs = [{'insertText':{'location':{'index':pos},'text':full}}]
        p = pos
        for (text,pstyle,segs,btype) in tbuf:
            end_p = p+len(text)
            if pstyle and pstyle!='NORMAL_TEXT':
                reqs.append(ps(p,end_p,pstyle))
            if btype=='code_block':
                reqs.append(ts(p,end_p-1,font=MONO,size=9,color=(0.1,0.1,0.55)))
            if btype=='blockquote':
                reqs.append(ts(p,end_p-1,italic=True,color=(0.4,0.4,0.4)))
                reqs.append({'updateParagraphStyle':{'range':{'startIndex':p,'endIndex':end_p},
                    'paragraphStyle':{'indentStart':{'magnitude':36,'unit':'PT'},
                                      'indentFirstLine':{'magnitude':0,'unit':'PT'}},
                    'fields':'indentStart,indentFirstLine'}})
            if btype=='bullet':
                reqs.append({'createParagraphBullets':{'range':{'startIndex':p,'endIndex':end_p},
                             'bulletPreset':'BULLET_DISC_CIRCLE_SQUARE'}})
            if btype=='numbered':
                reqs.append({'createParagraphBullets':{'range':{'startIndex':p,'endIndex':end_p},
                             'bulletPreset':'NUMBERED_DECIMAL_ALPHA_ROMAN'}})
            reqs.extend(inline_style(segs,p))
            p += len(text)

        ok = safe_batch(doc_id, reqs)
        if ok:
            # Re-sync pos from actual document state
            actual_end, _ = doc_end(doc_id)
            pos = actual_end - 1
        tbuf.clear()

    for block in blocks:
        bt = block.get('type')
        if bt == 'table':
            flush()
            # Add separator before table
            safe_batch(doc_id, [{'insertText':{'location':{'index':pos},'text':'\n'}}])
            pos += 1
            pos = insert_table_block(doc_id, block, pos)
            # Add separator after table
            safe_batch(doc_id, [{'insertText':{'location':{'index':pos},'text':'\n'}}])
            pos += 1
        elif bt=='blank':
            tbuf.append(('\n','NORMAL_TEXT',[],'blank'))
        elif bt in ('h1','h2','h3'):
            ps_name={'h1':'HEADING_1','h2':'HEADING_2','h3':'HEADING_3'}[bt]
            tbuf.append((block['text']+'\n',ps_name,block.get('segments',[]),bt))
        elif bt=='blockquote':
            tbuf.append((block['text']+'\n','NORMAL_TEXT',block.get('segments',[]),'blockquote'))
        elif bt=='bullet':
            tbuf.append((block['text']+'\n','NORMAL_TEXT',block.get('segments',[]),'bullet'))
        elif bt=='numbered':
            tbuf.append((block['text']+'\n','NORMAL_TEXT',block.get('segments',[]),'numbered'))
        elif bt=='code_block':
            tbuf.append((block['text']+'\n','NORMAL_TEXT',[],'code_block'))
        else:
            tbuf.append((block.get('text','')+'\n','NORMAL_TEXT',block.get('segments',[]),'paragraph'))

    flush()
    print(f'  ✓ Done', flush=True)

# ── Entry point ───────────────────────────────────────────────────────────────
BASE = '/opt/obsidian/vault/projects/music-data'
DOCS = [
    ('1FuD_hYwLTJ5AZiI6fW6TnrwXxfvbiG1bxEmGVQZ8Yoo','00-index.md',          'Master Index'),
    ('1ZRhSO-2mAdsCstn4ho9jmHaN2Hoea01t41upASwtSfA','01-mental-model.md',    '01 Mental Model'),
    ('1r2IO0MFRFFvsDxF0gGZ16ubp9RbvjT8VEGeZXVc65cc','02-market-analysis.md', '02 Market Analysis'),
    ('1eU0lKzzVpx2PiqlaPnjTyfX-ATZ_GrmcJ_PaMYWvZvw','03-personal-brand.md',  '03 Personal Brand'),
    ('1LJIsogrUBtDsTeICC1gxThWgrIY0ySWK21w1AgRCZZU','04-gtm-plan.md',        '04 GTM Plan'),
    ('1TN_oo-ylowYb3bSwq1goocUUwIgo_HLkQ6wEo-JUENw','05-execution-plan.md',  '05 Execution Plan'),
    ('1C6eH7zSLPE9FJBlZSsnBsy1b56MR-x-VRgGJ1SxE8ks','06-social-strategy.md', '06 Social Strategy'),
    ('1ZU-sblSsvTd9eu2wGr8XzTWtqwDMGmy93L6yQNCTCVY','07-bigsound-roadmap.md','07 BigSound Roadmap'),
    ('1Wmyy4zZ9Ol9NjoQI13WpovTQcVzor-Ex6ubMu8GZR_0','08-poc-build.md',       '08 POC Build Spec'),
]

import sys
# Allow running single doc by index: python3 format_v4.py 0
if len(sys.argv) > 1:
    idx = int(sys.argv[1])
    doc_id, fname, title = DOCS[idx]
    with open(f'{BASE}/{fname}') as f: content = f.read()
    reformat(doc_id, content, title)
else:
    for doc_id, fname, title in DOCS:
        with open(f'{BASE}/{fname}') as f: content = f.read()
        reformat(doc_id, content, title)
        print('  Waiting 60s for quota reset...', flush=True)
        time.sleep(60)

print('\nDone. https://drive.google.com/drive/folders/1A7QRyqubqBOHdcIOqCNmHFJMZR_SlZrU')
