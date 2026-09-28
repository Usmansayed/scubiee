import json,sys
def send(msg):
    body=json.dumps(msg,separators=(',',':'))
    sys.stdout.write(f'Content-Length: {len(body.encode())}\r\n\r\n{body}')
    sys.stdout.flush()
def read():
    headers={}
    while True:
        line=sys.stdin.buffer.readline()
        if not line or line in (b'\r\n', b'\n'):
            break
        if b':' in line:
            k,v=line.decode().split(':',1)
            headers[k.strip().lower()]=v.strip()
    n=int(headers.get('content-length','0'))
    raw=sys.stdin.buffer.read(n) if n else b''
    return json.loads(raw) if raw else None
while True:
    msg=read()
    if not msg: break
    mid=msg.get('id')
    method=msg.get('method')
    if method=='initialize':
        send({'jsonrpc':'2.0','id':mid,'result':{'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'mock','version':'0.0.1'}}})
    elif method=='notifications/initialized':
        pass
    elif method=='tools/list':
        send({'jsonrpc':'2.0','id':mid,'result':{'tools':[{'name':'ping','description':'ping','inputSchema':{'type':'object','properties':{}}}]}})
    elif method=='tools/call':
        send({'jsonrpc':'2.0','id':mid,'result':{'content':[{'type':'text','text':'PONG'}]}})
    elif method=='prompts/list':
        send({'jsonrpc':'2.0','id':mid,'result':{'prompts':[]}})
    else:
        if mid is not None:
            send({'jsonrpc':'2.0','id':mid,'error':{'code':-32601,'message':f'unknown {method}'}})
