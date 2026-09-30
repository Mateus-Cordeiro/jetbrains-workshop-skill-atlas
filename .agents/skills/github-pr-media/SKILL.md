---
name: github-pr-media
description: Upload existing local videos or images to a GitHub pull request description or comment and verify the saved attachments. Use when attaching PR demos, screenshots, or recordings; recording and editing the media are separate workflows.
---

# GitHub PR media

Attach the requested files to the intended PR using GitHub's web editor. A CLI
that edits PR text may not upload binary attachments; that limitation alone does
not establish that uploading is unavailable.

## Establish the target

- Use the PR, files, and placement identified in the current task. Resolve missing
  details from context before asking. Prefer the existing Demo section when the
  repository uses one; do not create an extra comment unless that is the requested
  destination or the agreed fallback.
- Respect existing authorization and explicit deferrals. A request to explain or
  document uploading does not authorize an upload. Creating this skill does not
  authorize testing it against a live PR.
- Check that each local file exists and is the intended reviewed artifact. Keep
  the original until delivery is verified. Read the current PR text and look for
  an existing attachment before editing or retrying.

## Preferred route: browser file chooser

Use the available browser tools and an authenticated GitHub session with edit
access. Discover their current upload API before declaring the action blocked.
An available tool method is evidence of capability, not proof that the GitHub
upload or authentication has succeeded.

With Codex's `mcp__cua_repl` browser tools:

1. Initialize/select the browser and PR tab using the tool's documented entry
   points. After initialization, read the upload-specific documentation:

   ```javascript
   nodeRepl.write(await agent.documentation.get("file-uploads"));
   ```

2. Open the intended description/comment editor and inspect its current state.
   Preserve unrelated text and any unsaved user edits. Ground the upload control's
   locator in the observed page; use its file input or associated button/label.

3. Start waiting for the chooser **before** clicking the upload control. The
   currently documented API accepts absolute paths through the chooser:

   ```javascript
   // tab and uploadControl come from the observed PR editor;
   // absoluteMediaPath identifies the authorized local artifact.
   const chooserPromise = tab.playwright.waitForEvent("filechooser", {timeoutMs: 10000});
   await uploadControl.click();
   const chooser = await chooserPromise;
   await chooser.setFiles([absoluteMediaPath]);
   ```

   For multiple files, check `chooser.isMultiple()` first; otherwise attach them
   individually. Do not assume `locator.setInputFiles()` exists: this browser
   interface exposes uploads through `chooser.setFiles()`.

4. Inspect the editor after uploading. Wait for the upload indicator to finish
   and for GitHub to insert the attachment URL/Markdown. File selection alone is
   not completion. Retain the inserted syntax, add the intended caption, and place
   the media in the requested section. Use GitHub's generated URL, never a local
   filesystem path, in the PR.

5. Preview and save. Check the saved page, not just the editor buffer: the caption
   and attachment must be present, and unrelated PR text must remain intact.
   Open images at readable size and check video playback. Follow the browser
   tool's proof-of-work requirements when reporting the saved result.

## Fallbacks and bounded retries

- If the chooser flow fails, inspect the actual cause: control selection, file
  visibility, browser support, authentication, or a GitHub validation error.
  Reinspect the editor before retrying so a completed upload is not duplicated.
- Where native desktop controls are available, try the browser's OS file picker
  as a fallback. Select the known file by its absolute path, then return to the
  editor and perform the same upload/save checks. Use supported computer-use
  tools, not browser-cookie extraction or undocumented attachment endpoints.
- If GitHub rejects a format or size, read its displayed restriction. Convert or
  compress an appropriate copy when within scope, verify the resulting media,
  and retry. Renaming a file extension is not conversion.
- `gh pr edit --body-file` or the PR API can insert already-uploaded URLs. When
  using them, start from the latest body and preserve unrelated edits. They do
  not replace the binary upload step.
- Release assets and external hosting change where the media is published. Use
  them only when the user chose that destination; do not create a release or
  commit generated demos to the repository merely to obtain a URL.
- Stop when a concrete blocker requires user action, or further retries would
  repeat the same failure without new evidence. Preserve the artifact and any
  successful upload URL. Report the attempted method, observed blocker, current
  state, and the smallest handoff needed.

## Report accurately

Return the PR/comment link and the verified attachment outcome. Distinguish an
unattempted upload, a failed attempt, an upload not yet saved to the PR, and a
saved attachment whose rendering/playback was verified. State any remaining
verification limit explicitly. If blocked, provide clickable local file links
and captions for handoff; do not describe local recordings as attached to GitHub.
