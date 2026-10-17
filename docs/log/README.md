# Feature logs

One file per person. **Append-only.** Your agent writes an entry after every feature and reads *all* files here at the start of every session and before every integration window. This is how four Claude sessions see each other's work without reading each other's code.

Template (copy exactly; keep it short):

```
## 2026-10-17 11:40 · <feature name> · branch <name>/<topic> · commit <7-char sha>
What: one or two sentences.
Files: path/one.py, path/two.tsx
Run: the exact command to see it work
Interfaces: consumes <contract>; produces <contract>; changed: none | <contract> vX.Y (see DECISIONS Dnn)
Status: done | partial (what's missing) | blocked by <person/thing>
Next: the next thing you'll do
```

Rules
- Log the *interface* consequences first; that's what others need.
- If you changed a contract or fixture, say the version and the decision number.
- Never edit someone else's log. Never delete entries. Rebase before push.
