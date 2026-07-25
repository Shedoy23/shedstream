# -*- coding: utf-8 -*-
# Byte-exact mover: cut [start..end] (1-based inclusive) from src, append to dst
# under a header, leave a pointer in src. Boundary asserts guard against wrong ranges.
# Job JSON (utf-8): {src,dst,start,end,assert_first,assert_last,assert_after,header[],pointer[]}
import io, json, sys

job = json.load(io.open(sys.argv[1], encoding='utf-8'))
src, dst = job['src'], job['dst']
start, end = int(job['start']), int(job['end'])

with io.open(src, encoding='utf-8', newline='') as f:
    lines = f.readlines()

nl = '\r\n' if lines and lines[0].endswith('\r\n') else '\n'

def bare(s):
    return s.rstrip('\r\n')

first = bare(lines[start - 1])
last = bare(lines[end - 1])
after = ''.join(lines[end:end + 4])

if job['assert_first'] not in first:
    print('FAIL assert_first: start=%d got=%r want=%r' % (start, first, job['assert_first'])); sys.exit(1)
if job['assert_last'] not in last:
    print('FAIL assert_last: end=%d got=%r want=%r' % (end, last, job['assert_last'])); sys.exit(1)
if job.get('assert_after') and job['assert_after'] not in after:
    print('FAIL assert_after: want=%r in %r' % (job['assert_after'], after)); sys.exit(1)

block = lines[start - 1:end]

header = nl.join(job['header'])
pointer_lines = [p + nl for p in job['pointer']]

# append block to dst
with io.open(dst, encoding='utf-8', newline='') as f:
    dtext = f.read()
if dtext and not dtext.endswith(nl):
    dtext += nl
dtext += nl + header + nl + ''.join(block)
if not dtext.endswith(nl):
    dtext += nl
with io.open(dst, 'w', encoding='utf-8', newline='') as f:
    f.write(dtext)

# remove block from src, leave pointer
new_lines = lines[:start - 1] + pointer_lines + lines[end:]
with io.open(src, 'w', encoding='utf-8', newline='') as f:
    f.writelines(new_lines)

print('OK moved %d lines (%d-%d)' % (end - start + 1, start, end))
print('  first=%r' % first)
print('  last =%r' % last)
print('  src now %d lines (was %d)' % (len(new_lines), len(lines)))
