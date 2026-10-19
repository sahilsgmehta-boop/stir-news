import subprocess, json
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
def get(url):
    p = subprocess.run(["curl","-sS","-L","--compressed","-m","30","-A",UA,"-w","\n@@%{http_code}",url],capture_output=True)
    b,_,c = p.stdout.decode("utf-8","replace").rpartition("\n@@"); return c,b
for s in ["SR3=F","ZQ=F","SR3Z26.CME","SR3H27.CME","ZQX26.CBT","ZQF27.CBT","SR1X26.CME","ZNZ26.CBT","FEIZ26.NYB","SONZ26.NYB","SO3Z26.NYB","IMZ26","FEI=F"]:
    c,b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=5m")
    try:
        m = json.loads(b)["chart"]["result"][0]["meta"]
        print(s, c, m.get("regularMarketPrice"), m.get("exchangeName"), m.get("regularMarketTime"), m.get("exchangeDataDelayedBy"))
    except Exception as e:
        print(s, c, b[:150].replace("\n"," "))
for s in ["@SR3.1","@ZQ.1","@SR3Z26","@FEI.1","@SO3.1"]:
    c,b = get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="+s+"&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
    print("cnbc", s, c, b[:250].replace("\n"," "))
