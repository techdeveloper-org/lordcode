"""M6b: the replaced routing path is gone, and its capabilities survived it.

Deleting 543 lines is easy to get wrong in two directions: leaving a dangling
import, or quietly dropping a capability with the module that provided it.
These tests cover the second, which is the one a green suite would otherwise
hide -- `--skill` forced a real library skill before M6b, and the CLI's event
echo is the only place a user sees what selection decided.

Windows-safe: ASCII only.
"""

from __future__ import annotations

import pathlib

import pytest

from vishwakarma.cli import _echo_event
from vishwakarma.engine import knowledge


class TestTheModulesAreGone:
    def test_neither_file_exists(self):
        assert not pathlib.Path("vishwakarma/plugins.py").exists()
        assert not pathlib.Path("vishwakarma/engine/kg_routing.py").exists()

    def test_nothing_imports_them(self):
        offenders = []
        for path in pathlib.Path("vishwakarma").rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")) and (
                    "plugins" in stripped or "kg_routing" in stripped
                ):
                    offenders.append(f"{path}: {stripped}")
        assert offenders == [], offenders

    def test_the_skill_prompt_fragment_mechanism_is_gone(self):
        """plugins.Skill carried a prompt_addition appended to the system
        prompt -- a second, weaker channel for library knowledge alongside the
        assembled context. Forcing a skill goes through the closure now."""
        from vishwakarma.engine import personas

        assert not hasattr(personas, "Skill")
        assert hasattr(personas, "SubAgent")


class TestTheCatalogueStillLists:
    """plugins.load_all_skills/load_all_agents had two real consumers."""

    def test_skills_come_from_the_graph(self):
        skills = knowledge.list_skills()
        assert len(skills) == 1034
        assert all(skill.name for skill in skills)

    def test_agents_come_from_the_graph_with_a_derived_role(self):
        agents = knowledge.list_agents()
        assert len(agents) == 528
        assert {agent.role for agent in agents} <= {"primary_coder", "reasoner"}

    def test_listings_are_sorted_by_name(self):
        names = [skill.name for skill in knowledge.list_skills()]
        assert names == sorted(names)

    def test_skill_listings_report_no_domain(self):
        """Skill.domain is a display name on 175 of 1034 records -- the defect
        M1 fixed by reading membership from edges. Reporting it here would put
        it straight back."""
        assert all(skill.domain == "" for skill in knowledge.list_skills())

    def test_an_absent_description_is_empty_not_a_failure(self):
        """134 skills and 147 agents carry none."""
        assert sum(1 for skill in knowledge.list_skills() if not skill.description) == 134
        assert sum(1 for agent in knowledge.list_agents() if not agent.description) == 147


class TestForcingASkill:
    """--skill forced a real library skill before M6b; it still does."""

    AGENT = "spring-boot-microservices"

    def test_a_forced_skill_goes_to_the_front_of_the_closure(self):
        """Front, not back: context assembly spends budget in order and drops
        from the end, so appending would make a forced skill the first thing
        dropped."""
        unforced = knowledge.resolve("x", forced_agent=self.AGENT, budget_tokens=2000)
        outsider = next(
            skill.name
            for skill in knowledge.list_skills()
            if "skill:" + skill.name.replace("-", "_") not in unforced.mandatory_skills
        )
        forced = knowledge.resolve(
            "x", forced_agent=self.AGENT, forced_skill=outsider, budget_tokens=2000
        )

        assert forced.mandatory_skills[0] == "skill:" + outsider.replace("-", "_")
        assert len(forced.mandatory_skills) == len(unforced.mandatory_skills) + 1

    def test_forcing_a_skill_already_in_the_closure_changes_nothing(self):
        unforced = knowledge.resolve("x", forced_agent=self.AGENT, budget_tokens=2000)
        already = unforced.mandatory_skills[0].split(":", 1)[1].replace("_", "-")
        forced = knowledge.resolve(
            "x", forced_agent=self.AGENT, forced_skill=already, budget_tokens=2000
        )

        assert forced.mandatory_skills == unforced.mandatory_skills

    def test_an_unknown_skill_is_refused_rather_than_ignored(self):
        """A silent miss would make a typo indistinguishable from a skill that
        contributed nothing."""
        with pytest.raises(knowledge.KnowledgeUnavailable, match="no skill named"):
            knowledge.resolve("x", forced_agent=self.AGENT, forced_skill="no-such-skill-xyz")


class TestTheCliNarratesTheNewPath:
    """cli.py handled kg_route_resolved/kg_route_unavailable, neither of which
    could fire after M6a -- so a run printed a persona name and nothing else."""

    def test_a_selection_renders_every_piece_of_evidence(self, capsys):
        _echo_event(
            {
                "type": "kgf_selection",
                "outcome": "selected",
                "agent": "spring-boot-microservices",
                "domain": "domain:backend_engineering",
                "confidence": 0.464,
                "role": "primary_coder",
                "skills": 10,
                "context_tokens": 1494,
                "budget_tokens": 2000,
                "edge_path": ["agent:x -AGENT_USES_SKILL-> skill:y"],
                "library_version": "29.97.4",
            }
        )
        out = capsys.readouterr().out
        for fragment in ("selected", "spring-boot-microservices", "0.464", "primary_coder", "1494/2000"):
            assert fragment in out
        assert "AGENT_USES_SKILL" in out

    def test_a_no_match_renders_without_the_agent_keys(self):
        """The no-match event carries no agent/domain/confidence at all, so a
        handler indexing them would raise inside the echo and take the run
        down with it."""
        _echo_event(
            {"type": "kgf_selection", "outcome": "no_match", "library_version": "29.97.4", "considered": 0}
        )

    def test_a_defect_is_surfaced(self, capsys):
        _echo_event({"type": "kgf_defect", "detail": "skill:x could not be read"})
        assert "could not be read" in capsys.readouterr().out

    def test_phase_outcomes_are_reported(self, capsys):
        _echo_event(
            {
                "type": "phases_completed",
                "levels": [],
                "completed": ["phase:B"],
                "failed": ["phase:D"],
                "skipped": [],
            }
        )
        out = capsys.readouterr().out
        assert "phase:B" in out and "phase:D" in out

    def test_a_refused_heal_is_reported(self, capsys):
        _echo_event(
            {"type": "heal_refused", "reason": "the test runner is missing", "detail": "mvn not on PATH"}
        )
        out = capsys.readouterr().out
        assert "refused" in out and "mvn not on PATH" in out

    def test_an_unknown_event_is_ignored_silently(self):
        """The echo is a display, not a validator: a new event type from any
        producer must not crash a run."""
        _echo_event({"type": "something_nobody_has_written_yet"})
