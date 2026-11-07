# Personal assistant

A multi-agent "second you" for one person, built on Omnigent with Claude Code. It learns how the person judges and decides, through an onboarding interview grounded in their own real decisions, and then helps them the way they would decide, inside the hard lines they set. Nothing enters their record without their approval, and it never sends, pays, books or posts anything itself.

Everything in the pack is generic. Everything about the person lives only in their record, which starts empty and is filled by their own onboarding.

## Use it

```bash
./pa onboard          # start onboarding, or continue it where it stopped
./pa chat             # talk to your chief of staff
./pa review           # the weekly review of your record
./pa changes          # changes to your record waiting for your yes
./pa approve ID|all   # approve them (or click the card in the chat)
./pa reject ID|all    # reject them
./pa check            # check the code: no AI, a few seconds
./pa stop             # stop Omnigent
```

The agents run inside Omnigent. `pa` starts it in the background whenever a command needs it, with this folder's safeguards loaded, and writes the Omnigent configs for the machine it runs on first.

**Needs:** Python 3.11 or later with `pyyaml` and `mcp`; the `claude` command signed in to a Claude subscription (no API keys are used); Omnigent; and `tmux`, which Omnigent uses to run the native agents.

## How it fits together

The person talks to three agents:

- **Onboarding** (`pa onboard`): the interviewer, in one chat, from the first hello to the last session. It sends the native **case finder** to discover what it can reach and, once the person approves a scope, to find real decisions in their sources; the **preparer** turns those into an interview guide built on eleven dimensions of the person; the interviewer then runs short sessions, walking through real decisions moment by moment. Every entry reaches the record only through an approval card the person clicks.
- **Chief of staff** (`pa chat`): everyday use. It answers first, from their record; runs the fixed decision procedure for any real decision; records new decisions; and hands anything outside the record (their apps, the web) to the native **worker**.
- **Curator** (`pa review`): the weekly review. Code finds what is stale, due, conflicting or overtaken, and the curator brings the person a short list with proposed fixes.

Behind them, run by code and never talked to: the **analyst**, **advisor**, **challenger** and **tester** (the decision procedure), the **builder** (skills, trackers, rules and reminders, on the person's yes), the **policy** and **precedent checkers**, and the **quarantine reader**, which reads every outside message so that no agent ever sees its raw text.

The person's own area know-how is kept as skills in their record (`record/skills/`), written by the builder from their real decisions; a fresh record has only the template.

## Layout

```
pa                 the one command
kit/               the same for every person
  constitution.md  what every agent follows
  charters/        each agent's instructions
  METHODS.md       the method behind each agent, and what code enforces
  templates/record the empty record a person's own record starts from
system/            the code: tools, decision procedure, policy engine, guards
scripts/
  build_agents.py  writes agents/ for this machine (pa runs it)
  selftest.py      the code checks behind pa check
  check_onboarding_live.py   a developer check of onboarding in Omnigent
record/            the person's own record, created on first run; never uploaded
workspace/         the only place the native agents may write, apart from the inbox
agents/            Omnigent configs, generated on each machine; not shipped
```

## Safeguards

They are enforced in code, not left to the agents' instructions:

- The agents the person talks to have no shell, files or web. Their only tools are in `system/tools_server.py`, and none of them sends, pays, books or posts.
- The record changes only through proposals the person approves. Journal entries are never rewritten. Requests such as "don't ask me again" are never stored as rules.
- Hard lines remove options before anything is weighed, and a money threshold in the person's own currency marks high stakes.
- Outside messages are read by a model with no tools, and secrets and identity numbers are redacted before any agent sees them.
- The native worker and case finder run under a guard (`system/omnigent_policies.py`) that checks every action. They may write only in `workspace/` and the record's inbox. They may read only there, in the person's Claude and Codex conversation stores, and in folders the person allows (`PA_READABLE`). Secret stores are never read. Deleting is denied, sending asks the person first, and once a session has read private data it cannot reach the web.

See `kit/METHODS.md` for the method behind each agent and the full list of what code enforces.

## Where things live

Every location is worked out from where the pack sits, so it runs from any folder on any machine. Set these to move things:

| Variable | What it moves | Default |
|---|---|---|
| `PA_RECORD` | the person's record (created from `kit/templates/record` if missing) | `record/` |
| `PA_WORKSPACE` | the native agents' working folder | `workspace/` |
| `PA_STATE` | session state and traces | `state/` |
| `PA_READABLE` | extra folders the native agents may read, joined by `:` | none |
| `OMNIGENT_SERVER` | an Omnigent server other than the local one | `http://127.0.0.1:6767` |

When an approved change touches the person's name, profile, rules or skills, the configs are rebuilt so new sessions start from the approved record. Nothing runs on a schedule unless the person sets one up.
