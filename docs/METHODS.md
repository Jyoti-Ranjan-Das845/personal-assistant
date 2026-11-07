# Methods behind each agent

Every agent's charter is built around a named method from the research or professional practice that does the same job for people. The method is chosen for what an AI does well and badly: a model is fluent, tireless and good at following a well-described procedure, but it anchors on the first framing it sees, reports confidence it does not have, loses track of state across a long conversation, drops whatever competes with the most salient instruction, and does arithmetic unreliably in prose. So each method is paired with what the code enforces, because an instruction that keeps being ignored is not fixed by rewording it; it has to move into a tool, a schema or a calculation.

## The people model: what the record captures

The record is organised around eleven dimensions of how a person decides. Each rests on a validated framework from decision and personality research, used as a lens for the interviewer and preparer, never as a questionnaire put to the person, because a form gets a person's self-image and a walk through a real case gets their judgement.

| Dimension | Framework |
|---|---|
| Hard limits and money threshold | Protected values (Baron and Spranca, 1997; Tetlock's taboo trade-offs) |
| What they are optimising for | Personal projects (Brian Little, 1983) |
| Values in conflict | Schwartz's theory of basic human values |
| How they decide | Decision-making styles (Scott and Bruce, 1995); maximisers and satisficers (Barry Schwartz, 2002) |
| Yardsticks they judge by | Personal construct theory and the repertory grid (George Kelly, 1955) |
| Risk by area of life | Domain-specific risk-taking scale (Weber, Blais and Betz, 2002) |
| What they reject | Negative case analysis (qualitative research) |
| People and roles | Who they consult and whose view moves them |
| Blind spots | Documented heuristics and biases (Kahneman and Tversky): sunk cost, anchoring, status quo |
| Turning points | The life story interview (Dan McAdams) |
| How they want help | Their own stated preferences |

## The agents

| Agent | Method | Why it suits an AI | Enforced in code |
|---|---|---|---|
| Interviewer | Critical Decision Method (Klein); cognitive interview (Fisher and Geiselman); repertory grid, laddering and member checking | People cannot report why they chose (Nisbett and Wilson) but can report what they noticed, and a model is good at patient, specific follow-up questions | The next step is computed from the record, the waiting proposals and the ledger (`personal_assistant/interview.py`), so stories offered are walked through before the checklist; a threshold needs one amount and their words choosing it; a hard line needs their words |
| Case finder | Purposeful, maximum-variation sampling (Patton); information foraging (Pirolli and Card); unobtrusive measures (Webb); grounded theory; triangulation | A model can read far more than a person but drifts into one rich corner; sampling rules keep the picture broad | Secrets and identity numbers are redacted from every digest (`personal_assistant/redact.py`); it cannot act in any app |
| Preparer | Interview-guide design (Kvale and Brinkmann); the eleven dimensions above | Turns raw digests into a short guide so the interview stays anchored on real cases | It can write only the guide and the ledger |
| Chief of staff | The honest broker (Pielke); pyramid principle (Minto); intelligence briefing standards (ICD 203) | A model asked to summarise a long result paraphrases it differently each time | The decision report comes with `say_in_order`, built by code, so the same result is always told the same way; reminders and record changes are proposals only |
| Analyst | Structured analysis (Heuer); ICD 203; reference-class forecasting (Kahneman and Lovallo); Mill's method of difference | Models anchor on the first lean they see, so the brief carries none | It must end with its table's features as JSON, and each becomes a rule that is tested; for someone else's decision it sets out only what lands on the person |
| Advisor | Substituted judgment (clinical ethics); revealed over stated preference | Asks the model to reason from the person's record, not from what people in general do | Its reading is one input to the matrix, not the answer |
| Challenger | Analysis of competing hypotheses (Heuer); pre-mortem (Klein); red teaming | A second model, run separately and on a different model, so it cannot be anchored by the first | Its rival rules are tested like every other rule |
| Tester | Heuer's competing-hypotheses matrix; Mill's method and qualitative comparative analysis (Ragin) | Small, factual judgements per cell, with the arithmetic shown, are what a model does reliably | Code weighs the matrix: the rule with the fewest cases against it gives the read, only cases that could have broken a rule count as tests, an equally supported rival makes it contested, and the confidence follows from the counts (`personal_assistant/decide.py`) |
| Policy checker | Compliance review by the plain-meaning rule | A model can be talked round; a narrow question with one rule and one option cannot | It may block only by quoting words that are really in the option |
| Precedent checker | Review of standing orders for over-wide wording and conflict | Rulings are applied to cases nobody imagined, so their literal reach is checked | Quoted words must really be in the ruling; only real record ids are kept |
| Curator | Periodic records review (records management practice) | A model reviewing a whole record misses what it did not open | Due reviews, related entries, reminders, trackers, rulings that reach past a hard line and conflicting rulings are all found by code and handed over |
| Builder | Building to a template | Templates stop a model inventing structure | It may propose only skills, trackers, reminders, rules and notes, and only after the person agreed in their own words |
| Worker | Newsroom fact-checking; SIFT for the web (Caulfield) | A native agent with the person's own connections, used for anything outside the record | Its Omnigent guard denies deletes, asks before sending, and cuts the web once private data has been read |
| Quarantine reader | Dual-model pattern for prompt injection (Willison; CaMeL) | The agents that can act never see untrusted text | It has no tools; only its extracted fields reach other agents |

## Testing

`tests/selftest.py` checks the code itself, every guard and calculation above, without calling any model, and `tests/check_onboarding_live.py` checks onboarding live in Omnigent on an empty copy of the record. A test bench that runs the whole system against cases built from the person's own decisions, with an actor playing them and a judge grading, is left for later, once there is a proper way to judge it. The fictional person and scenarios used while the system was being built are kept in `archive/` and are not part of the pack.
