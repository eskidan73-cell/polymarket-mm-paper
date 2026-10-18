import mm_paper as m
T=lambda side,p,s:{"asset":"X","side":side,"price":str(p),"size":str(s)}
tr=[T("SELL",0.49,30),T("SELL",0.50,40),T("BUY",0.52,10),T("BUY",0.51,100),T("SELL",0.30,5)]
# bid .50 ask .52 size 50
assert m.fills("strict",.50,.52,50,tr,"X")==(35,0), m.fills("strict",.50,.52,50,tr,"X")
assert m.fills("touch",.50,.52,50,tr,"X")==(50,10), m.fills("touch",.50,.52,50,tr,"X")
assert m.fills("strict",.50,.52,50,[{"asset":"Y","side":"SELL","price":"0.1","size":"9"}],"X")==(0,0)
print("fills OK")
