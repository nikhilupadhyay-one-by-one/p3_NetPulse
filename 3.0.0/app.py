"""NetPulse — single-file, cross-platform network monitor and diagnostics.

Run: python app.py | python app.py --cli <command>
Dependencies: psutil, PySide6 (desktop), dnspython (optional)
"""
from __future__ import annotations
import argparse, csv, json, os, re, socket, subprocess, sys, threading, time, ipaddress
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

VERSION = "3.1.0"
APP_NAME = "NetPulse"

# ---------- Shared utility / system layer ----------
def run_command(args, timeout=30):
    kwargs = dict(capture_output=True, text=True, errors="replace", timeout=timeout)
    if os.name == "nt": kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(args, **kwargs); return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e: return -1, str(e)

def interfaces():
    import psutil
    stats = psutil.net_if_stats(); addrs = psutil.net_if_addrs()
    out=[]
    for name, rows in addrs.items():
        ips=[]; mac=""
        for a in rows:
            if a.family in (socket.AF_INET, socket.AF_INET6):
                ip=a.address.split("%",1)[0]
                if ip and not ip.startswith("127.") and ip != "::1": ips.append(ip)
            elif getattr(a.family,"name","") in ("AF_LINK","AF_PACKET") or str(a.family).endswith("17"):
                mac=a.address
        out.append({"name":name,"up":stats.get(name).isup if name in stats else False,"speed":stats.get(name).speed if name in stats else 0,"ips":ips,"mac":mac})
    return out

def primary_ip():
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(("1.1.1.1",80)); ip=s.getsockname()[0]; s.close(); return ip
    except Exception: return None

def byte_rate(previous, current, elapsed):
    if elapsed<=0: return 0,0
    return max(0,current.bytes_recv-previous.bytes_recv)/elapsed, max(0,current.bytes_sent-previous.bytes_sent)/elapsed

def connection_rows(resolve=False):
    import psutil
    names={p.pid:p.info.get("name") or "?" for p in psutil.process_iter(["pid","name"])}
    result=[]
    try: raw=psutil.net_connections(kind="inet")
    except Exception: raw=[]
    for c in raw:
        l=c.laddr; r=c.raddr
        local=f"{l.ip}:{l.port}" if l else ""
        remote=f"{r.ip}:{r.port}" if r else ""
        if resolve and r:
            try: remote=f"{socket.gethostbyaddr(r.ip)[0]} ({remote})"
            except Exception: pass
        result.append({"pid":c.pid or "", "process":names.get(c.pid,"?") if c.pid else "?", "protocol":"TCP" if c.type==socket.SOCK_STREAM else "UDP", "local":local,"remote":remote,"state":c.status or ""})
    return result

def ping_command(host, count=4):
    return ["ping","-n",str(count),host] if os.name=="nt" else ["ping","-c",str(count),host]

def ping(host, count=4, timeout=20):
    code,out=run_command(ping_command(host,count),timeout)
    samples=[]
    for m in re.finditer(r"(?:time[=<]|time\s*=\s*)([\d.,]+)\s*ms",out,re.I):
        try:samples.append(float(m.group(1).replace(",",".")))
        except ValueError:pass
    sent=count; received=len(samples)
    loss=max(0,(sent-received)/sent*100) if sent else 0
    jitter=sum(abs(samples[i]-samples[i-1]) for i in range(1,len(samples)))/(len(samples)-1) if len(samples)>1 else 0
    return {"host":host,"sent":sent,"received":received,"loss_percent":loss,"min_ms":min(samples) if samples else None,"avg_ms":sum(samples)/len(samples) if samples else None,"max_ms":max(samples) if samples else None,"jitter_ms":jitter,"output":out,"success":bool(samples)}

def trace_command(host,max_hops=25):
    cmd=["tracert","-d","-h",str(max_hops),host] if os.name=="nt" else ["traceroute","-n","-m",str(max_hops),host]
    code,out=run_command(cmd,timeout=max_hops*3+10)
    hops=[]
    for line in out.splitlines():
        m=re.match(r"\s*(\d+)\s+(.*)",line)
        if not m:continue
        n=int(m.group(1)); tail=m.group(2); ips=re.findall(r"(?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F:]{3,}",tail)
        times=[]
        for t in re.findall(r"([\d.,]+)\s*ms",tail,re.I):
            try:times.append(float(t.replace(",",".")))
            except ValueError:pass
        hops.append({"hop":n,"address":ips[-1] if ips else "*","latencies_ms":times,"line":line.strip()})
    return hops,out

def dns_lookup(name, kind="A", timeout=4):
    try:
        import dns.resolver
        r=dns.resolver.Resolver(); r.timeout=timeout;r.lifetime=timeout
        ans=r.resolve(name,kind); return [{"name":name,"type":kind,"value":str(x),"ttl":ans.rrset.ttl} for x in ans]
    except ImportError:
        if kind not in ("A","AAAA"): return [{"error":"Install dnspython for advanced record types."}]
        try:
            vals=socket.getaddrinfo(name,None,socket.AF_INET if kind=="A" else socket.AF_INET6)
            return [{"name":name,"type":kind,"value":v[4][0],"ttl":None} for v in vals]
        except Exception as e:return [{"error":str(e)}]
    except Exception as e:return [{"error":str(e)}]

def ports_from_text(text):
    ports=set()
    for part in text.split(","):
        part=part.strip()
        if not part:continue
        if "-" in part:
            a,b=map(int,part.split("-",1));
            if a>b:a,b=b,a
            if a<1 or b>65535:raise ValueError("Port values must be between 1 and 65535.")
            if b-a>10000:raise ValueError("A single range cannot exceed 10,000 ports.")
            ports.update(range(a,b+1))
        else:
            p=int(part)
            if p<1 or p>65535:raise ValueError("Port values must be between 1 and 65535.")
            ports.add(p)
    return sorted(ports)

COMMON={20:"FTP-data",21:"FTP",22:"SSH",23:"Telnet",25:"SMTP",53:"DNS",80:"HTTP",110:"POP3",123:"NTP",135:"RPC",139:"NetBIOS",143:"IMAP",443:"HTTPS",445:"SMB",587:"SMTP",631:"IPP",993:"IMAPS",995:"POP3S",1433:"MSSQL",3306:"MySQL",3389:"RDP",5432:"PostgreSQL",5900:"VNC",8080:"HTTP-alt",8443:"HTTPS-alt"}
def scan_port(host,port,timeout=.55):
    try:
        with socket.create_connection((host,port),timeout=timeout):return {"host":host,"port":port,"service":COMMON.get(port,"unknown"),"state":"open"}
    except Exception:return None

def port_scan(host,ports,timeout=.55,workers=100,cancel=None,progress=None):
    found=[]; total=len(ports)
    with ThreadPoolExecutor(max_workers=min(workers,100)) as pool:
        futures={pool.submit(scan_port,host,p,timeout):p for p in ports}
        for i,f in enumerate(as_completed(futures),1):
            if cancel and cancel.is_set():
                for q in futures:q.cancel()
                break
            r=f.result()
            if r:found.append(r)
            if progress:progress(i,total)
    return sorted(found,key=lambda r:r["port"])

def subnet_guess():
    ip=primary_ip()
    if not ip:return None
    for nic in interfaces():
        for addr in nic["ips"]:
            if addr==ip:
                try:
                    import psutil
                    for a in psutil.net_if_addrs().get(nic["name"],[]):
                        if a.family==socket.AF_INET and a.address==ip and a.netmask:return str(ipaddress.ip_network(f"{ip}/{a.netmask}",strict=False))
                except Exception:pass
    return None

def device_discovery(subnet=None,timeout=.35,limit=512,progress=None):
    subnet=subnet or subnet_guess()
    if not subnet:return [],"Could not detect a local IPv4 subnet."
    net=ipaddress.ip_network(subnet,strict=False)
    if net.num_addresses>limit+2:return [],f"Subnet contains {net.num_addresses} addresses; limit is {limit}. Narrow the subnet before scanning."
    targets=[str(ip) for ip in net.hosts()]
    arp={}
    code,out=run_command(["arp","-a"],timeout=5)
    for line in out.splitlines():
        m=re.search(r"(?:\d{1,3}\.){3}\d{1,3}.*?([0-9a-fA-F:-]{17})",line)
        if m:
            ip=re.search(r"(?:\d{1,3}\.){3}\d{1,3}",line)
            if ip:arp[ip.group()]=m.group(1)
    def probe(ip):
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.settimeout(timeout);s.connect((ip,80));s.close();return ip
        except Exception:
            try:
                s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.settimeout(timeout);s.connect((ip,443));s.close();return ip
            except Exception:return None
    alive=set()
    with ThreadPoolExecutor(max_workers=64) as ex:
        fs=[ex.submit(probe,ip) for ip in targets]
        for i,f in enumerate(as_completed(fs),1):
            ip=f.result()
            if ip:alive.add(ip)
            if progress:progress(i,len(targets))
    # ARP-cache hits are included as devices, even if TCP probes did not respond.
    alive.update(ip for ip in arp if ip in net)
    rows=[]
    for ip in sorted(alive,key=lambda x:int(ipaddress.ip_address(x))):
        try:host=socket.gethostbyaddr(ip)[0]
        except Exception:host=""
        rows.append({"ip":ip,"hostname":host,"mac":arp.get(ip,""),"vendor":"Offline OUI data not bundled in single-file build"})
    return rows,subnet

def export_rows(path,rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix.lower()==".json":path.write_text(json.dumps(rows,indent=2,default=str),encoding="utf-8")
    else:
        rows=list(rows); keys=list(rows[0]) if rows else ["empty"]
        with path.open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
    return path

# ---------- GUI layer ----------
def desktop():
    try:
        from PySide6.QtCore import Qt,QThread,Signal,QTimer
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QLineEdit,QComboBox,QSpinBox,QTableWidget,QTableWidgetItem,QTabWidget,QPlainTextEdit,QFileDialog,QMessageBox,QProgressBar
    except ImportError:
        print("Desktop mode requires PySide6. Install dependencies using: pip install -r requirements.txt");return 1
    import psutil
    class Worker(QThread):
        result=Signal(object); error=Signal(str); progress=Signal(int,int)
        def __init__(self,fn):super().__init__();self.fn=fn;self.cancel=threading.Event()
        def run(self):
            try:self.result.emit(self.fn(self.cancel,self.progress.emit))
            except Exception as e:self.error.emit(str(e))
    class Main(QMainWindow):
        def __init__(self):
            super().__init__();self.setWindowTitle(f"NetPulse {VERSION}");self.resize(1200,780);self.setStyleSheet("QMainWindow,QWidget{background:#10151d;color:#dbe5ef} QLineEdit,QComboBox,QSpinBox,QPlainTextEdit,QTableWidget{background:#171f2b;border:1px solid #334154;padding:5px} QPushButton{background:#24364b;padding:8px;border:1px solid #47617b;border-radius:5px} QPushButton:hover{background:#304e69} QHeaderView::section{background:#202b38;padding:5px}")
            self.tabs=QTabWidget();self.setCentralWidget(self.tabs);self.workers=[];self.samples=deque(maxlen=120);self.last=psutil.net_io_counters();self.started=time.monotonic();self.total_recv=0;self.total_sent=0
            self.traffic_tab();self.connections_tab();self.diagnostics_tab();self.devices_tab();self.timer=QTimer(self);self.timer.timeout.connect(self.refresh_traffic);self.timer.start(1000)
        def table(self,columns):
            t=QTableWidget(0,len(columns));t.setHorizontalHeaderLabels(columns);t.horizontalHeader().setStretchLastSection(True);return t
        def fill(self,t,rows):
            t.setRowCount(len(rows));
            for i,row in enumerate(rows):
                for j,v in enumerate(row.values()):t.setItem(i,j,QTableWidgetItem(str(v)))
        def export_button(self,table,keys,label):
            b=QPushButton("Export CSV / JSON")
            def go():
                if not table.rowCount():return
                path,_=QFileDialog.getSaveFileName(self,label,"netpulse-export.csv","CSV (*.csv);;JSON (*.json)")
                if path:
                    data=[{k:table.item(i,j).text() if table.item(i,j) else "" for j,k in enumerate(keys)} for i in range(table.rowCount())]
                    try:export_rows(path,data);QMessageBox.information(self,"Export",f"Saved {path}")
                    except Exception as e:QMessageBox.warning(self,"Export failed",str(e))
            b.clicked.connect(go);return b
        def traffic_tab(self):
            w=QWidget();l=QVBoxLayout(w);self.rate=QLabel("Receiving: 0 B/s   Sending: 0 B/s");self.rate.setFont(QFont("Segoe UI",18));l.addWidget(self.rate);self.totals=QLabel();l.addWidget(self.totals);self.traffic_table=self.table(["Time","Receive (B/s)","Send (B/s)"]);l.addWidget(self.traffic_table);l.addWidget(self.export_button(self.traffic_table,["time","receive","send"],"Export traffic"));self.tabs.addTab(w,"Traffic")
        def refresh_traffic(self):
            now=psutil.net_io_counters();dt=1;rx=max(0,now.bytes_recv-self.last.bytes_recv);tx=max(0,now.bytes_sent-self.last.bytes_sent);self.last=now;self.total_recv+=rx;self.total_sent+=tx;self.samples.append((datetime.now().strftime("%H:%M:%S"),rx/dt,tx/dt));self.rate.setText(f"Receiving: {format_rate(rx/dt)}   Sending: {format_rate(tx/dt)}");self.totals.setText(f"Session received {format_bytes(self.total_recv)} · sent {format_bytes(self.total_sent)} · elapsed {int(time.monotonic()-self.started)} s");self.fill(self.traffic_table,[{"time":x[0],"receive":round(x[1]),"send":round(x[2])} for x in self.samples])
        def connections_tab(self):
            w=QWidget();l=QVBoxLayout(w);self.conn_filter=QLineEdit();self.conn_filter.setPlaceholderText("Filter by process, PID, endpoint, state…");b=QPushButton("Refresh connections");l.addWidget(self.conn_filter);l.addWidget(b);self.conn_table=self.table(["PID","Process","Protocol","Local","Remote","State"]);l.addWidget(self.conn_table);l.addWidget(self.export_button(self.conn_table,["pid","process","protocol","local","remote","state"],"Export connections"));b.clicked.connect(self.refresh_connections);self.conn_filter.textChanged.connect(self.refresh_connections);self.tabs.addTab(w,"Connections");self.refresh_connections()
        def refresh_connections(self):
            try:rows=connection_rows();q=self.conn_filter.text().lower();rows=[r for r in rows if q in " ".join(map(str,r.values())).lower()];self.fill(self.conn_table,rows)
            except Exception as e:QMessageBox.warning(self,"Connections",str(e))
        def diagnostics_tab(self):
            w=QWidget();l=QVBoxLayout(w);grid=QGridLayout();self.host=QLineEdit("example.com");self.count=QSpinBox();self.count.setRange(1,100);self.count.setValue(4);self.dns_type=QComboBox();self.dns_type.addItems(["A","AAAA","CNAME","MX","NS","TXT","SOA","PTR"]);self.port_input=QLineEdit("22,80,443,8000-8100");
            for i,(lab,widget) in enumerate([("Host",self.host),("Ping count",self.count),("DNS type",self.dns_type),("Ports",self.port_input)]):grid.addWidget(QLabel(lab),i,0);grid.addWidget(widget,i,1)
            l.addLayout(grid);buttons=QHBoxLayout();self.output=QPlainTextEdit();self.output.setReadOnly(True)
            for label,fn in [("Ping",lambda:ping(self.host.text(),self.count.value())),("Trace",lambda:trace_command(self.host.text())[0]),("DNS",lambda:dns_lookup(self.host.text(),self.dns_type.currentText())),("Port scan",lambda:port_scan(self.host.text(),ports_from_text(self.port_input.text())))]:
                b=QPushButton(label);b.clicked.connect(lambda _,f=fn:self.diagnostic(f));buttons.addWidget(b)
            l.addLayout(buttons);l.addWidget(self.output);self.tabs.addTab(w,"Diagnostics")
        def diagnostic(self,fn):
            self.output.setPlainText("Working…")
            worker=Worker(lambda cancel,progress:fn());worker.result.connect(lambda r:self.output.setPlainText(json.dumps(r,indent=2,default=str)));worker.error.connect(self.output.setPlainText);worker.finished.connect(lambda:self.workers.remove(worker) if worker in self.workers else None);self.workers.append(worker);worker.start()
        def devices_tab(self):
            w=QWidget();l=QVBoxLayout(w);self.subnet=QLineEdit(subnet_guess() or "");self.subnet.setPlaceholderText("CIDR, e.g. 192.168.1.0/24");b=QPushButton("Discover devices");self.dev_table=self.table(["IP","Hostname","MAC","Vendor"]);l.addWidget(self.subnet);l.addWidget(b);l.addWidget(self.dev_table);l.addWidget(self.export_button(self.dev_table,["ip","hostname","mac","vendor"],"Export devices"));b.clicked.connect(lambda:self.diagnostic_devices());self.tabs.addTab(w,"Devices")
        def diagnostic_devices(self):
            self.output.setPlainText("Discovering…")
            worker=Worker(lambda cancel,progress:device_discovery(self.subnet.text().strip() or None,progress=lambda a,b:progress(a,b)));worker.result.connect(lambda r:self.fill(self.dev_table,r[0]) if isinstance(r,tuple) and r[0] else self.output.setPlainText(str(r)));worker.finished.connect(lambda:self.workers.remove(worker) if worker in self.workers else None);self.workers.append(worker);worker.start()
    app=QApplication(sys.argv);win=Main();win.show();return app.exec()

# ---------- CLI ----------
def format_bytes(n):
    units=["B","KB","MB","GB","TB"]
    for u in units:
        if n<1024:return f"{n:.1f} {u}"
        n/=1024
    return f"{n:.1f} PB"
def format_rate(n):return format_bytes(n)+"/s"
def cli(argv=None):
    p=argparse.ArgumentParser(prog="netpulse",description="NetPulse network monitor and diagnostics (single-file build)");sub=p.add_subparsers(dest="command")
    sub.add_parser("interfaces");q=sub.add_parser("ping");q.add_argument("host");q.add_argument("-c","--count",type=int,default=4)
    q=sub.add_parser("trace");q.add_argument("host");q.add_argument("--hops",type=int,default=25)
    q=sub.add_parser("dns");q.add_argument("host");q.add_argument("-t","--type",default="A")
    q=sub.add_parser("scan");q.add_argument("host");q.add_argument("ports",nargs="?",default="1-1024")
    q=sub.add_parser("connections");q=sub.add_parser("devices");q.add_argument("subnet",nargs="?")
    args=p.parse_args(argv)
    if not args.command:return desktop()
    try:
        if args.command=="interfaces":result=interfaces()
        elif args.command=="ping":result=ping(args.host,args.count)
        elif args.command=="trace":result=trace_command(args.host,args.hops)[0]
        elif args.command=="dns":result=dns_lookup(args.host,args.type)
        elif args.command=="scan":result=port_scan(args.host,ports_from_text(args.ports))
        elif args.command=="connections":result=connection_rows()
        elif args.command=="devices":result=device_discovery(args.subnet)
        print(json.dumps(result,indent=2,default=str));return 0
    except Exception as e:print(f"NetPulse: {e}",file=sys.stderr);return 2
if __name__=="__main__":sys.exit(cli())
