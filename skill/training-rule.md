## AI training

Whenever you launch model training (here or over ssh), make it visible in the ai-fleet panel:

1. Make the training log to TensorBoard, installing `tensorboard` in its environment and enabling it if needed. Ultralytics needs `yolo settings tensorboard=True`; mmdetection needs `TensorboardVisBackend` in `vis_backends`.
2. Right after launching, register it. For a queue script, register once with the directory all its runs log under.

```
fleet train watch [--host SSH_ALIAS] --dir LOGDIR --tensorboard PATH/TO/tensorboard --epochs N \
  --stop 'pkill -f "[o]utput-dir .*/{run}"' --train-loss TAG --map TAG \
  [--val-loss TAG] [--map50 TAG] [--class-map 'REGEX(CLASS)']
```

- Leave out `--host` for this machine.
- Tags are what the framework actually writes; read its logger if unsure. `--train-loss` and `--val-loss` may be globs whose matches get summed (`train/*`) for frameworks with no total. `--map` must be logged once per validation with the epoch as its step.
- Pass `--class-map` only if the training already logs per-class mAP. Never add per-class logging just for this.
- `--stop` runs on the training machine with `{run}` replaced by the TensorBoard run name, which is the run's path under `--dir`. It must stop that run only, including its workers, and let a queue carry on. Match on something unique to the run, and bracket the first letter of a `pkill -f` pattern so it can't match its own shell.
- Don't run this for training the user started themselves.
