# Core profile

TEMPLATE: this profile is empty. It is filled during onboarding and every entry is approved by the person before it is used.

## Who they are

A few lines: role, current situation, what they are working towards this season.

## Values, in priority order

Each value with the reason it matters to them, highest first.

1. (value) because (reason)

## Tie-breakers

When two of their values collide, which one wins, under what conditions, and the past decision this came from.

- (value A) wins over (value B) unless (condition). Source: (journal entry id)

## Blind spots

Where they tend to go wrong, and what usually triggers it.

- (blind spot), usually when (trigger)

## How they want answers

- (preference)

## Topics not to guess about

- (topic)

## Machine-readable rules

The policy engine reads this block. The agents read the same entries. Every change goes through their approval and is committed to git.

```yaml
hard_lines: []
# - id: HL-01
#   rule: Never personally guarantee a loan
#   why: Keeps every option open
#   enforce: block action category "financial_commitment"
thresholds: []
# - id: TH-01
#   rule: Any decision involving more than a set amount counts as high stakes
#   amount: 0
#   enforce: stakes floor = high
```
