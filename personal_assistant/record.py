"""Read the person's record: profile, machine-readable rules, entries, and
what is stale or due. Nothing here writes; only an approval does, through
proposals.resolve."""

import re
from datetime import date
from pathlib import Path

import yaml

FOLDERS = ("journal", "facts", "people", "precedents", "notes", "skills", "trackers", "reminders")
TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "record"


def as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


class Record:
    def __init__(self, root: Path, today: date | None = None):
        self.root = Path(root).resolve()
        self.today = today or date.today()

    # --- paths -----------------------------------------------------------

    def resolve(self, relative: str) -> Path:
        """Resolve a path inside the record, refusing anything outside it."""
        path = (self.root / relative).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError(f"{relative} is outside the record")
        return path

    # --- profile and rules ----------------------------------------------

    def person(self) -> dict:
        path = self.root / "person.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}

    def profile(self) -> str:
        return (self.root / "core_profile.md").read_text(encoding="utf-8")

    def rules(self) -> dict:
        """The hard_lines and thresholds block under "Machine-readable rules"."""
        match = re.search(r"## Machine-readable rules.*?```yaml\n(.*?)```", self.profile(), re.S)
        rules = (yaml.safe_load(match.group(1)) if match else None) or {}
        return {"hard_lines": rules.get("hard_lines") or [], "thresholds": rules.get("thresholds") or []}

    def currency(self) -> str:
        """The sign the person uses for money, from their threshold or their identity; empty if not recorded."""
        for t in self.rules()["thresholds"]:
            if t.get("currency"):
                return str(t["currency"])
        return str(self.person().get("currency") or "")

    def money_threshold(self) -> float | None:
        amounts = [t.get("amount") for t in self.rules()["thresholds"] if t.get("amount") is not None]  # 0 is a real threshold
        return float(min(amounts)) if amounts else None

    # --- entries ---------------------------------------------------------

    def files(self, folder: str) -> list[Path]:
        base = self.root / folder
        if not base.is_dir():
            return []
        return sorted(p for p in base.rglob("*") if p.is_file()
                      and not any(part.startswith(("_", ".")) for part in p.relative_to(base).parts))  # templates and caches

    def journal(self) -> list[dict]:
        entries = []
        for path in self.files("journal"):
            text = path.read_text(encoding="utf-8")
            front = {}
            match = re.match(r"---\n(.*?)\n---\n", text, re.S)
            if match:
                front = yaml.safe_load(match.group(1)) or {}
            entries.append({"path": path, "front": front, "text": text})
        return entries

    def yaml_entries(self, folder: str) -> list[dict]:
        entries = []
        for path in self.files(folder):
            if path.suffix in (".yaml", ".yml"):
                entries.append({"path": path, "data": yaml.safe_load(path.read_text(encoding="utf-8")) or {}})
        return entries

    def section(self, heading_prefix: str) -> str:
        match = re.search(rf"^## {re.escape(heading_prefix)}[^\n]*\n(.*?)(?=^## |\Z)", self.profile(), re.S | re.M)
        return match.group(1).strip() if match else ""

    def section_filled(self, heading_prefix: str) -> bool:
        """True once a profile section holds more than the empty template's text."""
        template = (TEMPLATES / "core_profile.md").read_text(encoding="utf-8")
        match = re.search(rf"^## {re.escape(heading_prefix)}[^\n]*\n(.*?)(?=^## |\Z)", template, re.S | re.M)
        empty = " ".join((match.group(1) if match else "").split())
        body = " ".join(self.section(heading_prefix).split())
        return bool(body) and body != empty

    @staticmethod
    def front_matter(text: str) -> dict:
        match = re.match(r"---\n(.*?)\n---\n", text, re.S)
        try:
            return (yaml.safe_load(match.group(1)) or {}) if match else {}
        except yaml.YAMLError:
            return {}

    def skills(self) -> list[dict]:
        """Each approved skill's name, description and file, so agents can find the one an area needs."""
        out = []
        for path in self.files("skills"):
            if path.name == "SKILL.md":
                front = self.front_matter(path.read_text(encoding="utf-8"))
                out.append({"name": front.get("name", path.parent.name), "description": front.get("description", ""),
                            "file": str(path.relative_to(self.root))})
        return out

    # --- what needs attention --------------------------------------------

    def stale_facts(self) -> list[dict]:
        stale = []
        for entry in self.yaml_entries("facts"):
            review_by = as_date(entry["data"].get("review_by"))
            if review_by and review_by < self.today:
                stale.append({**entry["data"], "days_overdue": (self.today - review_by).days})
        return stale

    def due_reviews(self) -> list[dict]:
        due = []
        for entry in self.journal():
            review_on = as_date(entry["front"].get("review_on"))
            outcome = re.search(r"## Outcome[^\n]*\n(.*?)(\n## |\Z)", entry["text"], re.S)
            outcome_text = outcome.group(1).strip() if outcome else ""
            empty = not outcome_text or outcome_text.lower().startswith(("not recorded", "not yet"))
            if review_on and review_on <= self.today and empty:
                due.append({"id": entry["front"].get("id", entry["path"].stem), "review_on": str(review_on)})
        return due

    def reminders_due(self, within_days: int = 7) -> list[dict]:
        """Reminders falling due between today and within_days from now, including those kept on trackers."""
        due = []
        for entry in self.yaml_entries("reminders"):
            on = as_date(entry["data"].get("date"))
            if on and 0 <= (on - self.today).days <= within_days:
                due.append({"on": str(on), "what": entry["data"].get("what", ""), "file": str(entry["path"].relative_to(self.root))})
        for path in self.files("trackers"):
            for item in self.front_matter(path.read_text(encoding="utf-8")).get("reminders") or []:
                on = as_date((item or {}).get("date"))
                if on and 0 <= (on - self.today).days <= within_days:
                    due.append({"on": str(on), "what": item.get("what", ""), "file": str(path.relative_to(self.root))})
        return sorted(due, key=lambda d: d["on"])

    def trackers_due(self) -> list[dict]:
        due = []
        for path in self.files("trackers"):
            front = self.front_matter(path.read_text(encoding="utf-8"))
            review_on = as_date(front.get("review_on"))
            if review_on and review_on <= self.today:
                due.append({"tracker": front.get("name", path.stem), "review_on": str(review_on), "file": str(path.relative_to(self.root))})
        return due

    # --- one text dump for the decision procedure -------------------------

    def dump(self) -> str:
        stale_keys = {f.get("key") for f in self.stale_facts()}
        parts = [f"# Record as of {self.today}", "## Core profile", self.profile()]
        parts.append("## Journal")
        parts += [e["text"] for e in self.journal()] or ["(empty)"]
        for folder in ("facts", "people", "precedents"):
            parts.append(f"## {folder.capitalize()}")
            entries = self.yaml_entries(folder)
            for e in entries:
                flag = "  # STALE: past its review date" if e["data"].get("key") in stale_keys and folder == "facts" else ""
                parts.append(yaml.safe_dump(e["data"], sort_keys=False, allow_unicode=True).strip() + flag)
            if not entries:
                parts.append("(empty)")
        skills = [p for p in self.files("skills") if p.name == "SKILL.md"]
        if skills:  # how the person approaches each area, approved by them
            parts.append("## Skills")
            parts += [p.read_text(encoding="utf-8") for p in skills]
        trackers = self.files("trackers")
        if trackers:
            parts.append("## Trackers")
            parts += [p.read_text(encoding="utf-8") for p in trackers]
        notes = self.files("notes")
        if notes:
            parts.append("## Notes")
            parts += [p.read_text(encoding="utf-8") for p in notes]
        return "\n\n".join(parts)
