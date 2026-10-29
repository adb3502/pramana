s=open('template.html').read()
snap=open('snapshot.json').read().replace('</','<\\/'); cur=open('receipts_curated.json').read().replace('</','<\\/')
s=s.replace('/*SNAP*/',snap,1).replace('/*CUR*/',cur,1)
open('pramana.html','w').write(s); print(len(s))
