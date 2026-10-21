# Dashboard

```
python dashboard/app.py
```

Open http://localhost:5000 while `brain/navigator.py` is running. It shows the newest run in `data/runs/`:
the latest camera frame, what the model saw and decided, the current search plan, a breadcrumb map
of the route from the entry (estimated from the moves sent), and the final report once a person is found.

It only reads files, so you can also open it after a run to replay the last one.
