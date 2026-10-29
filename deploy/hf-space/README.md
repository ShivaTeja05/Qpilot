---
title: qPilot
emoji: 🧬
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: 6.30.0
app_file: app.py
python_version: "3.12"
short_description: qPCR analysis that shows which choices change a result
license: apache-2.0
startup_duration_timeout: 1h
---

# qPilot — public sandbox

qPilot reads a qPCR instrument's raw amplification curves, analyses every plate with one
published method, and shows which of your analysis choices could change your conclusion. Those
choices stay with a person. **Research use only. Not for clinical or diagnostic use.**

This Space runs qPilot's own server as a **public sandbox**: shared by every visitor, reset when
the Space restarts, no language model, uploads up to 25 MB, a fair-use limit per visitor (a page
that says the sandbox is busy gives the wait). Don't upload confidential data. To
keep your data on your computer, install qPilot and run `qpilot app`
([source](https://github.com/ShivaTeja05/Qpilot)).

The demo study is the public Vermeulen 2009 / Ruijter 2013 neuroblastoma dataset (CC BY 4.0),
downloaded at start (SHA-256 pinned), walked through Studio and audited.
