# Installing qPilot

qPilot is a Python program. It runs on **Windows, macOS and Linux**, needs **Python 3.11, 3.12 or 3.13** (64-bit), about **600 MB** of disk for its libraries, and **no compiler and no Node**: the page is already built into the package. After the install it works offline; the only things that use the network are `qpilot fetch-demo` (a 7 MB public dataset, SHA-256 checked) and a language model, if you choose to configure one.

The installers below give qPilot its own private Python environment, so it cannot disturb, or be disturbed by, anything else on the computer. Use **pipx** or **uv**; use plain `pip` only inside a virtual environment you made.

> **Status.** qPilot is research software (version 0.x). Research use only; not for clinical or diagnostic use. Until the first release is on PyPI, install from GitHub (the "today" lines); when it is published the PyPI lines work too.

## 1. The short way

| | pipx | uv |
|---|---|---|
| Install from GitHub (today) | `pipx install git+https://github.com/ShivaTeja05/Qpilot.git` | `uv tool install git+https://github.com/ShivaTeja05/Qpilot.git` |
| Install from PyPI (once published) | `pipx install qpilot` | `uv tool install qpilot` |
| With a model provider (optional) | `pipx install "qpilot[ai] @ git+https://github.com/ShivaTeja05/Qpilot.git"` | `uv tool install "qpilot[ai] @ git+https://github.com/ShivaTeja05/Qpilot.git"` |
| Upgrade | `pipx upgrade qpilot` | `uv tool upgrade qpilot` |
| Remove | `pipx uninstall qpilot` | `uv tool uninstall qpilot` |

Then:

```bash
qpilot --version          # qpilot 0.x.y
qpilot doctor             # versions, where your data is, what could leave this computer; ends with OK
qpilot fetch-demo         # optional: the 64-plate demo study (7 MB, once)
qpilot app                # the page: prints a link, opens it; Ctrl-C stops it
```

Use the link `qpilot app` prints: it carries the key of this launch (see the [user guide](user-guide.md#1-start-the-page)).

`qpilot` and `qsim` (the Decision Simulator, which the page's Audit uses) are installed together. Excel files (`.xlsx`) are read and written without extras.

**Don't have pipx or uv?**

| | macOS | Linux | Windows (PowerShell) |
|---|---|---|---|
| uv | `brew install uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `winget install --id astral-sh.uv -e` |
| pipx | `brew install pipx && pipx ensurepath` | `sudo apt install pipx && pipx ensurepath` (Debian/Ubuntu) | `py -m pip install --user pipx` then `py -m pipx ensurepath` |

`ensurepath` adds the folder that holds `qpilot` to your PATH: **close the terminal and open a new one** afterwards. `uv` can also fetch Python itself (`uv tool install --python 3.12 …`), which is the easiest route on a computer with an old or no Python.

## 2. Windows, step by step

Most instrument computers run Windows, so here is the whole path. Everything is typed into **PowerShell** (Start, type "PowerShell"). You do not need administrator rights.

1. **Python 3.11 or newer.** Check with `py -0p`. If none is listed: install it from <https://www.python.org/downloads/windows/> (tick **Add python.exe to PATH**) or run `winget install Python.Python.3.12`. If typing `python` opens the Microsoft Store instead, use `py` as in the lines below, or switch off "App execution aliases" for Python in Windows Settings.
2. **pipx.**
   ```powershell
   py -3.12 -m pip install --user pipx
   py -3.12 -m pipx ensurepath
   ```
   Close PowerShell and open it again.
3. **qPilot.**
   ```powershell
   pipx install git+https://github.com/ShivaTeja05/Qpilot.git
   qpilot --version
   qpilot doctor
   qpilot app
   ```
   (Or, with uv: `uv tool install git+https://github.com/ShivaTeja05/Qpilot.git`.)
4. Open the link `qpilot app` prints. Windows normally asks nothing; if it asks whether Python may accept network connections, **Cancel** (or Don't allow) is right: qPilot listens on `127.0.0.1` only, which is this computer and needs no firewall rule.

Things to know on Windows:

* **Where files go.** `C:\Users\<you>\.cache\qpilot` (see [section 5](#5-where-your-data-lives)). Long paths: Windows stops at 260 characters unless long paths are enabled. qPilot's own paths stay below about 160 characters under a typical user name, but a deep export folder you choose plus a long user name can pass it; if a file cannot be created, set `QPILOT_STUDIES_DIR` to a short folder, for example `C:\qpilot\studies`.
* **Quotes in PowerShell.** Put a path with spaces in double quotes: `qpilot check sheet "C:\Lab Data\my sheet.xlsx"`.
* **Setting a variable** for this window: `$env:QPILOT_STUDIES_DIR = "C:\qpilot\studies"`; for good: `setx QPILOT_STUDIES_DIR "C:\qpilot\studies"` (then open a new window).
* **Antivirus / OneDrive.** A program that scans or syncs a file the moment it is written can make Windows refuse a rename for a moment; qPilot retries for about two seconds. Keep the store out of a synced folder if you can (see section 5).
* **This is new ground.** The code is written to run on Windows and the test suite and the installed-package check run on Windows in CI, but no maintainer has yet used it on a real instrument PC. If something misbehaves, `qpilot doctor` output and the message are what we need.

## 3. macOS and Linux notes

* **macOS first run.** `brew install pipx` (or uv) is the shortest path; the Python that comes with the Xcode tools may be older than 3.11. The first `qpilot` command after an install can take up to a minute (macOS checks the new native libraries once, and Python compiles the rest); later commands start in seconds. The first time qPilot reads a file in **Documents, Desktop or Downloads** from the Terminal, macOS asks whether the Terminal (or Python) may access that folder: allow it, or put the file somewhere else. Files you drop onto the page need no permission. If a browser does not open by itself, copy the link from the terminal.
* **Linux.** Debian and Ubuntu: `sudo apt install pipx python3-venv` (Python 3.11 or newer; Ubuntu 22.04 has 3.10, so use uv or the deadsnakes/pyenv Python there). If `qpilot` is "command not found" after `pipx ensurepath`, open a new terminal.
* **A server or a container** with no browser: `qpilot app --no-open --port 7860` prints the link; reach it with an SSH tunnel (`ssh -L 7860:127.0.0.1:7860 host`), never by binding another address (qPilot refuses other hosts on purpose).

## 4. Other ways to install

* **pip in a virtual environment** (for scripting, or where you manage environments yourself):
  ```bash
  python3 -m venv qpilot-env
  source qpilot-env/bin/activate            # Windows: qpilot-env\Scripts\Activate.ps1
  pip install qpilot                        # or: pip install git+https://github.com/ShivaTeja05/Qpilot.git
  ```
* **From a clone** (to work on qPilot): `git clone https://github.com/ShivaTeja05/Qpilot && cd Qpilot`, then `pip install -e ".[dev,ai]"`. The page can be rebuilt with Node 22 (`cd frontend && npm ci && npm run build`); installing and using qPilot never needs it. `qsim validate` and `qsim external` need the clone (they score against `sim/data`, which the package does not carry) and say so otherwise.
* **Extras.** `qpilot[ai]` adds the libraries for a hosted or local language model (optional; with no model the fixed rules do the work and nothing leaves the computer). `studio`, `xlsx`, `sim` and `parquet` still work in an install line (`qpilot[studio,sim]`) but add nothing: everything they once added is included.
* **An AI agent (MCP).** `claude mcp add qpilot -- qpilot serve` (the same command in other MCP clients). `QPILOT_DATA_ROOTS` lists the folders an agent may read, separated by `;` on Windows and `:` elsewhere. See [agents.md](agents.md).

## 5. Where your data lives

`qpilot doctor` prints the exact folders in use on your computer (the `studies:` line, and the demo dataset's path).

| What | Default place | Change it with |
|---|---|---|
| **Your studies**: decisions, Studio sessions, instrument registry, audits | `~/.cache/qpilot/studies` | `QPILOT_STUDIES_DIR` |
| Copies of the files you opened, names, earlier demo work | next to the studies folder (`studio-inputs`, `studio-input-names`, `studies-archive`) | moves with `QPILOT_STUDIES_DIR` |
| The demo dataset, the published benchmark tables, cached curve analyses, imports | `~/.cache/qpilot` | `QPILOT_CACHE_DIR` |
| A lab profile (wording only) | none unless set | `QPILOT_PROFILE` |

`~` is `C:\Users\<you>` on Windows, `/Users/<you>` on macOS and `/home/<you>` on Linux, so a study store is `C:\Users\<you>\.cache\qpilot\studies` on Windows. Analysis Records and Prism bundles are written where you ask for them.

**The default is inside a cache folder, and the studies are your decision record.** Cleaning tools (CleanMyMac, Windows Storage Sense, `rm -rf ~/.cache`) treat that folder as disposable, and a synced folder (OneDrive, Dropbox, iCloud Drive) can corrupt a store that two programs write at once. For real work, point `QPILOT_STUDIES_DIR` at an ordinary local folder that you back up, once, before the first study (`setx` on Windows; a line in `~/.zshrc` or `~/.bashrc` elsewhere), and export an Analysis Record (the page's Record section, or `qpilot record`) of anything you must keep: a record is a self-contained folder or zip that `qpilot verify` and `qpilot rerun` check on any computer, on any system.

The cached curve analyses can be large (166 MB on the build laptop after eleven days of heavy use) and are safe to delete: qPilot recomputes them. Do not delete `studies`.

## 6. Upgrading and uninstalling

* **Upgrade**: `pipx upgrade qpilot` or `uv tool upgrade qpilot` (from GitHub: `pipx install --force git+https://github.com/ShivaTeja05/Qpilot.git`). Back up your studies folder first when a result matters, and read the [CHANGELOG](../CHANGELOG.md): an Analysis Record carries the version that wrote it, and `qpilot rerun` re-runs a record and compares the numbers.
* **Uninstall**: `pipx uninstall qpilot` or `uv tool uninstall qpilot`, or `pip uninstall qpilot` in the environment you used. This removes the program only. **Your studies and the cache stay** in the folders of section 5; delete them yourself when you are sure, by removing the `qpilot` folder inside `.cache` (and your `QPILOT_STUDIES_DIR`, if you set one). Remove the `QPILOT_*` variables you set, and the MCP entry (`claude mcp remove qpilot`).

## 7. Offline or locked-down computers

Prepare on a computer **with the same operating system, CPU type and Python version** that has internet:

```bash
pip download qpilot -d wheelhouse         # or: pip download git+https://github.com/ShivaTeja05/Qpilot.git -d wheelhouse
```

(about 50 files, around 120 MB). Copy `wheelhouse` to the offline computer and install:

```bash
python -m venv qpilot-env && source qpilot-env/bin/activate     # Windows: qpilot-env\Scripts\Activate.ps1
pip install --no-index --find-links wheelhouse qpilot
```

A release's `qpilot-X.Y.Z-py3-none-any.whl` (from the GitHub Release or PyPI) can stand in for `qpilot` above. To use the demo offline, copy the four files that `qpilot fetch-demo` stores in `~/.cache/qpilot` (`data_vermeulen_raw.rdml`, `RDML_Tools_bias.tsv`, `data_vermeulen_methods_cq.tsv`, `data_vermeulen_methods_results.tsv`) into the same folder on the other computer, or set `QPILOT_CACHE_DIR`. Your own data needs none of them.

## 8. If something does not work

| You see | Do this |
|---|---|
| `qpilot: command not found` / "not recognized" | Open a new terminal (PATH changes need it). Still missing: run `pipx ensurepath` (or `uv tool update-shell`) and open another. |
| "requires a different Python" | The Python that pip/pipx used is older than 3.11. `pipx install --python python3.12 …` or `uv tool install --python 3.12 …`. |
| The link opens but the page says to open the link again | Use the newest link from the terminal: each launch has its own key. |
| `Address already in use` | Another program has port 7860 (or another qPilot): `qpilot app --port 7861`. |
| `UnicodeEncodeError` | Update; qPilot writes UTF-8 to a pipe or file on every system since 0.2. |
| Anything else | Run `qpilot doctor` and keep its output with the message. |

How qPilot is built and published: [release.md](release.md).
