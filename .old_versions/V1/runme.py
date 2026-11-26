def banner():
    print("\n" * 2)
    print("=" * 40)
    print("NetPulse - Network Diagnostics Toolkit")
    print("=" * 40)
    print("\n" * 2)
banner()

print("Hello, welcome to NetPulse!")
print("Following Commands will be run on your system - Make sure you have the Internet Connection!!\n")

print("Command 1 - ping\nCommand 2 - ipconfig /all\nCommand 3 - hostname\nCommand 4 - getmac\nCommand 5 - arp -a\nCommand 6 - tracert\nCommand 7 - nslookup\nCommand 8 - netstat -a\nCommand 9 - route print\n")

import subprocess

def ping():
    a=input("Enter the IP address or domain to ping: ")
    subprocess.run(["ping", a])

def ipconfig():
    subprocess.run(["ipconfig", "/all"])

def hostname():
    subprocess.run(["hostname"])

def getmac():
    subprocess.run(["getmac"])

def arp():
    subprocess.run(["arp", "-a"])

def tracert():
    a=input("Enter the IP address or domain to trace: ")
    subprocess.run(["tracert", a])

def nslookup():
    a=input("Enter the IP address or domain to look up: ")
    subprocess.run(["nslookup", a])

def netstat():
    subprocess.run(["netstat", "-a"])

def route_print():
    subprocess.run(["route", "print"])

def mainfun():
    while True:
        
        while True:
            try:
                n = int(input("\nEnter the command number to run (or 0 to exit): "))
                break
            except ValueError:
                print("Please enter a valid integer.")

        if n==0:
            print("Exiting NetPulse. Goodbye!")
            break
        elif n==1:
            ping()
        elif n==2:
            ipconfig()
        elif n==3:
            hostname()
        elif n==4:
            getmac()
        elif n==5:
            arp()
        elif n==6:
            tracert()
        elif n==7:
            nslookup()
        elif n==8:
            netstat()
        elif n==9:
            route_print()
        else:
            print("Invalid command number. Please try again.")
mainfun()