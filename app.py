"""NetPulse V3 - a small, single-file network monitor and diagnostics tool."""
import sys
import time
import socket
import subprocess
import platform
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QLineEdit, QTextEdit, QMessageBox
import psutil

APP_VERSION = "3.0.0"

class NetPulse(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(f"NetPulse v{APP_VERSION}"); self.resize(950,650)
        self.setStyleSheet("QMainWindow,QWidget{background:#101820;color:#e6edf3} QPushButton{background:#203747;padding:8px;border-radius:5px} QPushButton:hover{background:#31566c} QLineEdit,QTextEdit,QTableWidget{background:#17232d;border:1px solid #344956;padding:5px} QHeaderView::section{background:#203747;padding:5px}")
        tabs=QTabWidget(); self.setCentralWidget(tabs)
        tabs.addTab(self.traffic_tab(),"Traffic"); tabs.addTab(self.connections_tab(),"Connections"); tabs.addTab(self.diagnostics_tab(),"Diagnostics")
        self.previous=psutil.net_io_counters(); self.last=time.monotonic(); self.timer=QTimer(self); self.timer.timeout.connect(self.update_traffic); self.timer.start(1000)
        self.refresh_connections()

    def traffic_tab(self):
        w=QWidget(); l=QVBoxLayout(w); l.addWidget(QLabel("Live network throughput (sampled once per second)"))
        self.rate=QLabel("↓ 0 B/s     ↑ 0 B/s"); self.rate.setStyleSheet("font-size:24px;font-weight:bold;padding:20px"); l.addWidget(self.rate)
        self.totals=QLabel("Session totals: waiting for first sample"); l.addWidget(self.totals); l.addStretch(); return w
    def update_traffic(self):
        nowc=psutil.net_io_counters(); now=time.monotonic(); dt=max(now-self.last,.001)
        down=max(0,nowc.bytes_recv-self.previous.bytes_recv)/dt; up=max(0,nowc.bytes_sent-self.previous.bytes_sent)/dt
        self.rate.setText(f"↓ {self.fmt(down)}/s      ↑ {self.fmt(up)}/s")
        self.totals.setText(f"Received: {self.fmt(nowc.bytes_recv)}   •   Sent: {self.fmt(nowc.bytes_sent)}")
        self.previous=nowc; self.last=now
    @staticmethod
    def fmt(n):
        units=["B","KB","MB","GB","TB"]
        for u in units:
            if n<1024 or u==units[-1]: return f"{n:.1f} {u}"
            n/=1024
    def connections_tab(self):
        w=QWidget(); l=QVBoxLayout(w); self.filter=QLineEdit(); self.filter.setPlaceholderText("Filter by process, address, port or state")
        btn=QPushButton("Refresh connections"); btn.clicked.connect(self.refresh_connections); self.filter.textChanged.connect(self.refresh_connections)
        l.addWidget(self.filter); l.addWidget(btn); self.conn_table=QTableWidget(0,6); self.conn_table.setHorizontalHeaderLabels(["Process","Protocol","Local","Remote","State","PID"]); self.conn_table.horizontalHeader().setStretchLastSection(True); l.addWidget(self.conn_table); return w
    def refresh_connections(self):
        if not hasattr(self,"conn_table"): return
        needle=self.filter.text().lower() if hasattr(self,"filter") else ""; rows=[]
        try:
            for c in psutil.net_connections(kind="inet"):
                try: proc=psutil.Process(c.pid).name() if c.pid else "—"
                except (psutil.Error, OSError): proc="—"
                la=f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "—"; ra=f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "—"
                proto="TCP" if c.type==socket.SOCK_STREAM else "UDP"; state=c.status or "—"; pid=str(c.pid or "—")
                row=[proc,proto,la,ra,state,pid]
                if needle and needle not in " ".join(row).lower(): continue
                rows.append(row)
        except psutil.AccessDenied: pass
        self.conn_table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,val in enumerate(row): self.conn_table.setItem(i,j,QTableWidgetItem(val))
    def diagnostics_tab(self):
        w=QWidget(); l=QVBoxLayout(w); self.target=QLineEdit(); self.target.setPlaceholderText("Host or IP (example: example.com)")
        buttons=QHBoxLayout(); ping=QPushButton("Ping"); trace=QPushButton("Traceroute"); dns=QPushButton("DNS lookup")
        ping.clicked.connect(lambda:self.run_diag("ping")); trace.clicked.connect(lambda:self.run_diag("trace")); dns.clicked.connect(lambda:self.run_diag("dns")); buttons.addWidget(ping); buttons.addWidget(trace); buttons.addWidget(dns)
        l.addWidget(self.target); l.addLayout(buttons); self.output=QTextEdit(); self.output.setReadOnly(True); l.addWidget(self.output); l.addWidget(QLabel("Only diagnose systems and networks you own or have permission to test.")); return w
    def run_diag(self,kind):
        host=self.target.text().strip()
        if not host: QMessageBox.information(self,"NetPulse","Enter a host or IP first."); return
        self.output.setPlainText("Working…")
        try:
            if kind=="dns":
                results=socket.getaddrinfo(host,None); text="DNS results:\n"+"\n".join(sorted({r[4][0] for r in results}))
            else:
                windows=platform.system().lower()=="windows"; cmd=("ping", "-n" if windows else "-c", "4", host) if kind=="ping" else (("tracert" if windows else "traceroute"), host)
                if kind=="trace" and not windows: cmd=("traceroute","-m","15",host)
                result=subprocess.run(cmd,capture_output=True,text=True,timeout=35); text=result.stdout or result.stderr or "No output returned."
            self.output.setPlainText(text)
        except FileNotFoundError: self.output.setPlainText("This diagnostic command is not installed or available on this system.")
        except Exception as e: self.output.setPlainText(f"Could not complete diagnostic: {e}")

if __name__=="__main__":
    app=QApplication(sys.argv); window=NetPulse(); window.show(); sys.exit(app.exec())
