# Contract: Universal Attention-Aware Voice

## Goal

Aloud must speak whenever Claude Code or Codex needs the user, becomes blocked, or finishes.

The behavior must work in Plan Mode, Default Mode, and any current or future skill. Aloud must react to universal lifecycle events and must never contain special handling for Grill Me or any other named skill.

Questions and choices must be spoken accurately. Completed replies must receive a short deterministic local summary, with the complete reply available separately.

## Examples

- Success: An unknown Codex skill calls `request_user_input`. Aloud says which project needs attention, reads the question, and reads every option.
- Important failure: Claude Code and its transcript watcher report the same permission request. Aloud speaks it once, not twice.
- Not included: Aloud does not listen to the user, answer questions, approve permissions, or narrate every routine tool call.

## Scope: what may change

The builder may change only:

- `src/aloud/**`
- `tests/**`

The milestone contract is frozen and read-only after attempt 1 starts.

`README.md` is out of scope because the primary worktree contains an existing user edit. Documentation for new commands should be recorded as later work.

Everything else is out of bounds.

## Required behavior

### Universal events

Add one normalized event model covering:

- question;
- plan approval;
- permission;
- blocked;
- completed.

The normalized event must include enough information for:

- source platform;
- session and turn;
- project or working directory;
- event type;
- original text;
- questions and options;
- explicit recommendation, when supplied;
- whether the user must respond;
- priority;
- stable deduplication identity.

Do not inspect skill names. A skill name must not be required anywhere in event detection or speech rendering.

### Claude Code

Capture supported Claude Code events through:

- `PreToolUse` for `AskUserQuestion` and `ExitPlanMode`;
- `PermissionRequest`;
- `Elicitation`;
- `Notification` as a fallback attention signal;
- `StopFailure`;
- `Stop`.

Ordinary final-text questions must also be recognized when Claude does not use `AskUserQuestion`.

### Codex

Capture supported permission and completion events through lifecycle hooks.

For Plan Mode questions and other missing hook events, monitor only the armed Codex session’s transcript. Detect:

- `request_user_input`;
- MCP elicitation requests;
- blocking errors and non-user aborts.

Record the exact transcript path for each session. Never fall back to the globally newest Claude or Codex transcript.

A user interrupt is not a blocked failure and must remain quiet.

### Spoken output

For questions:

- identify the platform and project;
- read every question;
- read every option label and description;
- never truncate an attention event;
- announce a recommendation only when explicitly supplied;
- never invent a recommendation.

For permissions:

- identify the requesting platform and project;
- describe the tool and supplied reason;
- speak only a sanitized command or action preview;
- redact tokens, passwords, keys, authorization headers, and similar secrets;
- tell the user to approve or deny on screen.

For completed replies:

- create a deterministic local summary;
- prefer sections named Outcome, Summary, Result, Primary finding, or Done;
- otherwise use the first meaningful non-code paragraph;
- include up to three important bullets;
- include the next action or final question when present;
- keep the automatic summary near the existing `gist_chars` target;
- do not call a remote service or add another language model.

Preserve inline filenames, command names, and identifiers. Replace code-block bodies with a short spoken marker.

Full-reply playback must be chunked and complete instead of being cut off after one global character limit.

Treat the existing `max_chars` setting as the speech-chunk size for backward compatibility. Keep `gist_chars` as the automatic-summary target.

### Priority and session behavior

Priority order:

1. question or plan approval;
2. permission;
3. blocked;
4. completed.

A higher-priority event interrupts lower-priority speech.

Duplicate events from hooks, notifications, or transcripts must be spoken once.

Multiple armed sessions must remain isolated. Every replay and full-response action must target the correct session.

Routine searches, file reads, commands, and successful tool calls must remain silent.

`aloud off` must stop current playback and prevent later events from that session from speaking.

### Public commands and controls

Preserve:

- `aloud on`;
- `aloud off`;
- `aloud full`;
- `aloud stop`;
- `Cmd+Ctrl+H`;
- `Cmd+Ctrl+.`;

Add:

- `aloud repeat` to repeat the most recent attention event;
- `Cmd+Ctrl+J` for the same action;
- `aloud hook event` as the common lifecycle-event entry point;
- `aloud self-test --attention --no-audio`.

Update install, uninstall, and doctor behavior for every required hook. Installation must remain idempotent and preserve unrelated hooks.

## Acceptance command

Run this exact command from the repository root:

```sh
aloud self-test --attention --no-audio
```

Expected result: exits 0 and reports that the attention self-test exercised completion, structured question, ordinary text question, plan approval, permission, blocked event, deduplication, priority, and multiple sessions without playing audio.

Baseline before implementation:

```text
exit code: 2
usage: aloud [-h] [--version]
             {install,uninstall,doctor,daemon,hook,full,stop,voices,self-test}
             ...
aloud: error: unrecognized arguments: --attention
```

## Definition of Done

Automated tests must prove:

- Claude `AskUserQuestion` is spoken correctly.
- Claude `ExitPlanMode` produces a plan-approval alert.
- Codex `request_user_input` is spoken correctly.
- Plain-text questions work without a structured question tool.
- Arbitrary and previously unseen skill names require no code changes.
- Multiple questions, options, recommendations, and free-form choices work.
- Permissions, elicitations, failures, and completed replies work.
- Question and option text is not truncated.
- Secret values are not spoken.
- Priority and interruption work.
- Duplicate events are spoken once.
- Two sessions cannot steal each other’s speech or replay target.
- Routine tool calls remain silent.
- `aloud off` prevents later speech.
- Full replies are complete.
- Automatic summaries remain short and outcome-first.
- Existing commands and configuration remain compatible.
- Installer changes are idempotent and preserve unrelated hooks.

The attention self-test must exercise:

- completion;
- structured question;
- ordinary text question;
- plan approval;
- permission;
- blocked event;
- deduplication;
- priority;
- multiple sessions.

Live verification must also pass on the installed versions:

- Claude Code `2.1.212`: Plan Mode question, plan approval, permission, failure, and completion.
- Codex `0.144.0` CLI: Plan Mode `request_user_input`, permission, and completion.
- Codex desktop: structured question and completion.
- One question-producing Claude skill.
- One different question-producing Codex skill.
- One previously unseen temporary skill name.
- Two simultaneously armed sessions.
- One real audio alert confirmed by the user on the current output device.

Warm-start attention events must be dispatched within two seconds and begin audio within five seconds.

If live verification cannot run because a client, credential, session, or human audio confirmation is unavailable, classify it as ENVIRONMENT and stop without merging.

## Non-goals: what must stay unchanged

Do not add:

- skill-specific integrations or allowlists;
- speech recognition;
- Whisper Flow integration;
- automatic answers;
- automatic permission approval;
- remote summarization;
- another local AI model;
- non-macOS support;
- agent or skill prompt changes;
