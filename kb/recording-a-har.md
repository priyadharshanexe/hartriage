# How to record a useful HAR file

When the analysis finds no failed requests, the recording usually missed the problem. A good HAR file:

1. **Starts before the problem.** Open DevTools first, then reproduce.
2. **Keeps everything.** Turn on **Preserve log** (Chrome, Edge) or **Persist Logs** (Firefox), so a redirect or reload doesn't wipe the list.
3. **Turns off the cache.** Tick **Disable cache**, so every request is recorded.
4. **Includes the failure.** Reproduce until the error appears, then export.

## Chrome / Edge

1. Press `F12` (or `Ctrl+Shift+I`, `Cmd+Opt+I` on a Mac) and open the **Network** tab.
2. Tick **Preserve log** and **Disable cache**.
3. Reproduce the problem.
4. Click the download arrow ("Export HAR…") and save the file.

## Firefox

1. Press `F12` and open the **Network** tab.
2. Open the gear menu and tick **Persist Logs**; tick **Disable Cache**.
3. Reproduce the problem.
4. Right-click any request and choose **Save All As HAR**.

## Safari

1. Enable the Develop menu (Settings → Advanced → "Show features for web developers").
2. Develop → Show Web Inspector → **Network**, tick **Preserve Log**.
3. Reproduce, then click **Export**.

## Also send

- A screenshot of the **Console** tab: CORS and script errors show there, not in the HAR file.
- The time it happened and your timezone.

## About privacy

A HAR file contains your session cookies and tokens: anyone who has it may be able to sign in as you. HAR Triage removes them before the file is stored, but you can also run `hartriage redact file.har -o clean.har` yourself before sending it.
