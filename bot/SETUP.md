# Running RYDER on your own computer

RYDER is **paper trading only**. It never uses real money, wallet keys or signing. Please keep it that way.

Your Mac comes first below. Windows is at the end.

---

## Mac (main option)

### 1. Install Python
1. Go to https://www.python.org/downloads/ and click the big yellow **Download Python** button.
2. Open the file you downloaded and click through the installer.
3. When it finishes, a Finder window may open. Double-click **Install Certificates.command** in it.

### 2. Download RYDER
1. Go to https://github.com/xBM710x/RYDER-AI
2. Easiest way: open **Terminal** (press Cmd+Space, type Terminal, press Enter), then paste this and press Enter:
   ```
   cd ~ && git clone https://github.com/xBM710x/RYDER-AI.git
   ```
   If the Mac asks to install "command line developer tools", click **Install**. When that's done, run the line again.
3. You now have a folder called **RYDER-AI** in your home folder. The bot lives in **RYDER-AI/bot**.

### 3. Install RYDER's add-ons
Paste this into Terminal:
```
cd ~/RYDER-AI/bot && python3 -m pip install -r requirements.txt
```

### 4. Bring over RYDER's memory (desk balances, trades, history)
1. Get **ryder_state_export.zip** from Grok Bot.
2. Double-click it to unzip it.
3. Move **everything inside** it, including `desk.db` and the `reports` folder, into `~/RYDER-AI/bot`.
4. The hidden file `.tg_chat` comes along too. To see hidden files in Finder, press Cmd+Shift+. (period).

Alternatively, paste this into Terminal:
```
cd ~/RYDER-AI/bot && unzip -o ~/Downloads/ryder_state_export.zip
```

### 5. Add your keys (.env)
Paste this into Terminal:
```
cd ~/RYDER-AI/bot && cp .env.example .env && open -e .env
```
TextEdit opens. Paste your values after the `=` signs:
- `RYDER_GITHUB_TOKEN=` keeps the app (xbm710x.github.io/RYDER-AI) updated. Leave it blank if you don't want the app updated.
- `RYDER_TELEGRAM_TOKEN=` turns on phone alerts. This one is optional.

Save and close the file. **Never share `.env`, and never send it to ChatGPT.** It's set up so it never gets uploaded to GitHub.

### 6. Start RYDER and keep it running 24/7
Paste this into Terminal:
```
cd ~/RYDER-AI/bot && bash install_mac.sh
```
That's it. RYDER now:
- starts by itself whenever you log in
- restarts itself if it crashes or freezes
- keeps the Mac awake while it's running (with `caffeinate`)
- runs its self-tests every time it starts

**Check that it's working:**
```
tail -f ~/RYDER-AI/bot/supervisor.log
```
You should see "self-tests: 17 pass, 0 fail" and "runner (re)started". `runner.log` shows the coins it's scanning. Press Ctrl+C to stop watching. RYDER keeps running.

**Stop RYDER:** `cd ~/RYDER-AI/bot && bash uninstall_mac.sh`

**Run it by hand instead, just this once:** `cd ~/RYDER-AI/bot && bash start.sh` (Ctrl+C to stop).

### 7. Mac energy settings (so it never sleeps)
`caffeinate` keeps the Mac awake while RYDER runs. Also set these:
1. Open the **Apple menu  > System Settings**.
2. **MacBook:**
   - Go to **Battery > Options...**
   - Turn ON **"Prevent automatic sleeping on power adapter when the display is off"**.
   - Keep it **plugged in**.
3. **iMac or Mac mini:**
   - Go to **Energy** (or **Energy Saver**).
   - Turn ON **"Prevent automatic sleeping when the display is off"**.
   - Turn ON **"Start up automatically after a power failure"**.
4. **Keep the lid open on a MacBook.** Closing it puts the Mac to sleep unless an external monitor is attached.
5. The screen turning off is fine. Only "sleep" stops RYDER.
6. Make sure you stay logged in. RYDER runs under your user account.

---

## Letting ChatGPT update RYDER
All of RYDER's code is in the GitHub repo, in the **bot/** folder.
1. Give ChatGPT access to the repo **xBM710x/RYDER-AI**, for example by connecting GitHub in ChatGPT's settings.
2. Tell it something like:
   > "Edit the files in the `bot/` folder of xBM710x/RYDER-AI and push the change to the main branch. Keep RYDER paper-only, don't loosen any safety or rug checks, and never put tokens in the files. Make sure `python3 test_breakers.py` still passes."
3. ChatGPT's changes go to GitHub. Your Mac picks them up the next time you update (see below).

## Updating RYDER (after ChatGPT or anyone changes it)
Paste this into Terminal:
```
cd ~/RYDER-AI/bot && git pull && launchctl kickstart -k gui/$(id -u)/com.ryder.bot
```
This downloads the new code and restarts RYDER. Your balances and history stay, because `desk.db` is never in GitHub.

If `git pull` complains about local changes:
1. Run `git stash`.
2. Run the update again.

---

## Windows (backup option)
1. **Install Python** from https://www.python.org/downloads/. On the first installer screen, **tick "Add python.exe to PATH"**.
2. **Download RYDER:**
   - Install Git from https://git-scm.com.
   - Open **Command Prompt** and run `cd %USERPROFILE% && git clone https://github.com/xBM710x/RYDER-AI.git`
3. **Install the add-ons:** `cd %USERPROFILE%\RYDER-AI\bot && py -m pip install -r requirements.txt`
4. **Bring over RYDER's memory:** unzip `ryder_state_export.zip` into the `RYDER-AI\bot` folder.
5. **Add your keys:**
   - Copy `.env.example` to `.env`.
   - Open `.env` in Notepad and fill it in.
6. **Start RYDER:**
   - Double-click **start.bat** and leave the window open.
   - To auto-start it, press Win+R, type `shell:startup`, and put a shortcut to start.bat in that folder.
7. **Keep the PC awake:** go to **Settings > System > Power** and set **Sleep** to **Never** when plugged in.
8. **Update RYDER:**
   - Close the start.bat window.
   - Run `git pull` in the `bot` folder.
   - Double-click start.bat again.

## Linux
Follow the same steps as the Mac, then run `bash start.sh`. To keep it running, use a systemd user service or tmux.

---

## Important
- **Run only ONE RYDER publisher at a time.** Only one computer should have `RYDER_GITHUB_TOKEN` set. Otherwise two bots fight over the app.
- To check the safety self-tests any time: `python3 test_breakers.py`
