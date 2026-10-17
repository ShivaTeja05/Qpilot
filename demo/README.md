# Demo

- `demo_study.yaml`: the study, the clicks and the question used in the pitch.
- `demo.mp4`: the backup recording (1 min 50 s, no sound, captions on screen), for when the live demo cannot run.

The recording was made from the frozen app (`qpilot app --fresh-demo`, commit on `main` at the time of recording) in an 800×500 browser window. One frame was captured per step of the demo path, a caption was added under each, and the frames were joined with ffmpeg. Every number visible in it was produced by the engine on that run.

To re-record live instead, run `qpilot app --fresh-demo`, follow `demo_study.yaml` with a screen recorder (on macOS: QuickTime Player, File, New Screen Recording) and keep it under 2 minutes and 20 MB.
