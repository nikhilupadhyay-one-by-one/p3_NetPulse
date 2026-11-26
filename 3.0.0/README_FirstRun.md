### If you are running for the first time - likely since you clone repo often - use these steps :

Bro, running **NetPulse 3.1.0** is pretty straightforward! 😄 Since it's a Python desktop app, here's how to launch it on Windows.

### **1. Open the project folder**

Extract `NetPulse-3.1.0-SingleFile.zip`, then open the extracted `NetPulse-SingleFile` folder.

Open a terminal inside that folder:

- File Explorer → click the address bar.
- Type `cmd` and press Enter.

### **2. Install dependencies (first time only)**

Run:

```
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

This creates a separate Python environment for NetPulse and installs its dependencies.

### **3. Launch NetPulse**

```
.venv\Scripts\python.exe app.py
```



Desktop GUI

&#x20;NetPulse should launch.



### **4. Running it next time**

You don't need to reinstall anything. Just open the project folder and run:

```
.venv\Scripts\python.exe app.py
```

### **Bonus: Run individual commands**

You can also use NetPulse through the terminal:

```
.venv\Scripts\python.exe app.py interfaces
.venv\Scripts\python.exe app.py ping google.com -c 5
.venv\Scripts\python.exe app.py trace google.com
.venv\Scripts\python.exe app.py connections
```

**Important:** Keep `app.py`, `requirements.txt`, and the `.venv` folder together. The application code itself is all in `app.py`.


## Credits : AI - ChatGPT for Guiding for cold start