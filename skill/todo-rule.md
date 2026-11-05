## Todos and reminders

When the user asks you to remind them of something or to note a todo, add it to the ai-fleet panel's Todo tab:

```
fleet todo add "TEXT" [--due WHEN] [--md PATH/TO/NOTES.md]
```

- `--due` makes it a reminder, with a desktop notification when it comes due: `14:00`, `tomorrow 9:00`, `2026-11-12 14:00`, `+30m`, `+2h` or `+3d`. A date alone means 09:00.
- `--md` links a Markdown file the user can open from the todo, such as the notes or plan the todo is about. It must already exist.
- `fleet todo ls` lists them, with ids for `fleet todo done ID`, `fleet todo edit ID …` and `fleet todo rm ID`.
