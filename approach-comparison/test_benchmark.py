"""Tests for the approach-comparison benchmark modules.

Validates scenarios, assertions, support_agent, and the benchmark runner
without requiring the attest engine or API keys.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from scenarios import SCENARIOS, SCENARIOS_BY_ID, Scenario, _BASE_OUTPUT_SCHEMA
from support_agent import (
    DEFAULT_TOOL_ARGS,
    TOOL_ARG_SCHEMAS,
    TOOL_RESULT_FACTORIES,
    TOOL_RESULT_SCHEMAS,
    build_trace,
)


# ---------------------------------------------------------------------------
# Scenario validation
# ---------------------------------------------------------------------------


class TestScenarios:
    """Validate scenario data integrity."""

    def test_scenario_count(self) -> None:
        """50 scenarios defined."""
        assert len(SCENARIOS) == 50

    def test_unique_ids(self) -> None:
        """All scenario IDs are unique."""
        ids = [s.id for s in SCENARIOS]
        assert len(ids) == len(set(ids))

    def test_id_format(self) -> None:
        """IDs follow SC-NNN format."""
        for s in SCENARIOS:
            assert s.id.startswith("SC-"), f"{s.id} does not start with SC-"
            num = int(s.id.split("-")[1])
            assert 1 <= num <= 50, f"{s.id} number out of range"

    def test_scenarios_by_id_lookup(self) -> None:
        """SCENARIOS_BY_ID contains all scenarios and maps correctly."""
        assert len(SCENARIOS_BY_ID) == 50
        for s in SCENARIOS:
            assert SCENARIOS_BY_ID[s.id] is s

    def test_categories_coverage(self) -> None:
        """10 categories with 5 scenarios each."""
        categories: dict[str, int] = {}
        for s in SCENARIOS:
            categories[s.category] = categories.get(s.category, 0) + 1
        assert len(categories) == 10
        for cat, count in categories.items():
            assert count == 5, f"Category '{cat}' has {count} scenarios, expected 5"

    def test_required_fields_populated(self) -> None:
        """Every scenario has non-empty required fields."""
        for s in SCENARIOS:
            assert s.name, f"{s.id} missing name"
            assert s.user_message, f"{s.id} missing user_message"
            assert s.output_message, f"{s.id} missing output_message"
            assert s.output_keywords, f"{s.id} missing output_keywords"
            assert s.output_schema, f"{s.id} missing output_schema"
            assert s.judge_criteria, f"{s.id} missing judge_criteria"
            assert s.tool_sequence, f"{s.id} missing tool_sequence"
            assert s.required_tools, f"{s.id} missing required_tools"

    def test_metadata_positive_values(self) -> None:
        """Metadata values are positive."""
        for s in SCENARIOS:
            assert s.metadata.total_tokens > 0, f"{s.id} tokens <= 0"
            assert s.metadata.cost_usd > 0, f"{s.id} cost <= 0"
            assert s.metadata.latency_ms > 0, f"{s.id} latency <= 0"

    def test_required_tools_subset_of_sequence(self) -> None:
        """Required tools are always in the tool sequence."""
        for s in SCENARIOS:
            seq_set = set(s.tool_sequence)
            for tool in s.required_tools:
                assert tool in seq_set, (
                    f"{s.id}: required tool '{tool}' not in tool_sequence {s.tool_sequence}"
                )

    def test_forbidden_tools_not_in_sequence(self) -> None:
        """Forbidden tools never appear in the tool sequence."""
        for s in SCENARIOS:
            seq_set = set(s.tool_sequence)
            for tool in s.forbidden_tools:
                assert tool not in seq_set, (
                    f"{s.id}: forbidden tool '{tool}' found in tool_sequence"
                )

    def test_output_schema_is_valid_jsonschema(self) -> None:
        """Output schema is valid JSON Schema structure."""
        for s in SCENARIOS:
            schema = s.output_schema
            assert schema.get("type") == "object"
            assert "properties" in schema
            assert "required" in schema

    def test_base_output_schema(self) -> None:
        """Base schema requires intent and status."""
        assert _BASE_OUTPUT_SCHEMA["type"] == "object"
        assert "intent" in _BASE_OUTPUT_SCHEMA["properties"]  # type: ignore[operator]
        assert "status" in _BASE_OUTPUT_SCHEMA["properties"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Tool schemas and factories
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    """Validate tool schemas and result factories."""

    KNOWN_TOOLS = [
        "lookup_account",
        "search_knowledge_base",
        "check_order_status",
        "create_ticket",
        "send_email",
        "escalate_to_human",
    ]

    def test_all_tools_have_arg_schemas(self) -> None:
        """Every known tool has an argument schema."""
        for tool in self.KNOWN_TOOLS:
            assert tool in TOOL_ARG_SCHEMAS, f"Missing arg schema for {tool}"

    def test_all_tools_have_result_schemas(self) -> None:
        """Every known tool has a result schema."""
        for tool in self.KNOWN_TOOLS:
            assert tool in TOOL_RESULT_SCHEMAS, f"Missing result schema for {tool}"

    def test_all_tools_have_factories(self) -> None:
        """Every known tool has a result factory."""
        for tool in self.KNOWN_TOOLS:
            assert tool in TOOL_RESULT_FACTORIES, f"Missing factory for {tool}"

    def test_all_tools_have_default_args(self) -> None:
        """Every known tool has default args."""
        for tool in self.KNOWN_TOOLS:
            assert tool in DEFAULT_TOOL_ARGS, f"Missing default args for {tool}"

    def test_factory_output_matches_result_schema_keys(self) -> None:
        """Factory output contains all required keys from the result schema."""
        for tool in self.KNOWN_TOOLS:
            factory = TOOL_RESULT_FACTORIES[tool]
            args = DEFAULT_TOOL_ARGS[tool]
            result = factory(args)
            required = TOOL_RESULT_SCHEMAS[tool].get("required", [])
            for key in required:
                assert key in result, (
                    f"Factory for '{tool}' missing required key '{key}'"
                )

    def test_arg_schemas_are_object_type(self) -> None:
        """All arg schemas define an object type."""
        for tool, schema in TOOL_ARG_SCHEMAS.items():
            assert schema.get("type") == "object", f"{tool} arg schema not object type"

    def test_scenario_tools_are_known(self) -> None:
        """Every tool referenced in scenarios exists in the tool definitions."""
        all_tools: set[str] = set()
        for s in SCENARIOS:
            all_tools.update(s.tool_sequence)
            all_tools.update(s.required_tools)
            all_tools.update(s.forbidden_tools)
        for tool in all_tools:
            assert tool in TOOL_ARG_SCHEMAS, f"Unknown tool '{tool}' used in scenarios"


# ---------------------------------------------------------------------------
# Trace builder
# ---------------------------------------------------------------------------


class TestBuildTrace:
    """Validate the synthetic trace builder."""

    @pytest.fixture
    def scenario(self) -> Scenario:
        return SCENARIOS_BY_ID["SC-001"]

    def test_returns_agent_result(self, scenario: Scenario) -> None:
        """build_trace returns an AgentResult with a trace."""
        result = build_trace(
            scenario_id=scenario.id,
            user_message=scenario.user_message,
            tool_sequence=scenario.tool_sequence,
            output_message=scenario.output_message,
            output_structured={"intent": scenario.category, "status": "resolved"},
            total_tokens=scenario.metadata.total_tokens,
            cost_usd=scenario.metadata.cost_usd,
            latency_ms=scenario.metadata.latency_ms,
        )
        # AgentResult has a .trace attribute
        assert result.trace is not None

    def test_trace_contains_tool_calls(self, scenario: Scenario) -> None:
        """Trace contains the expected number of tool calls."""
        result = build_trace(
            scenario_id=scenario.id,
            user_message=scenario.user_message,
            tool_sequence=scenario.tool_sequence,
            output_message=scenario.output_message,
            output_structured={"intent": scenario.category, "status": "resolved"},
            total_tokens=scenario.metadata.total_tokens,
            cost_usd=scenario.metadata.cost_usd,
            latency_ms=scenario.metadata.latency_ms,
        )
        tool_steps = [s for s in result.trace.steps if s.type == "tool_call"]
        assert len(tool_steps) == len(scenario.tool_sequence)

    def test_trace_tool_order(self, scenario: Scenario) -> None:
        """Tool calls appear in the order specified by the scenario."""
        result = build_trace(
            scenario_id=scenario.id,
            user_message=scenario.user_message,
            tool_sequence=scenario.tool_sequence,
            output_message=scenario.output_message,
            output_structured={"intent": scenario.category, "status": "resolved"},
            total_tokens=scenario.metadata.total_tokens,
            cost_usd=scenario.metadata.cost_usd,
            latency_ms=scenario.metadata.latency_ms,
        )
        tool_names = [s.name for s in result.trace.steps if s.type == "tool_call"]
        assert tool_names == scenario.tool_sequence

    def test_trace_has_llm_calls(self, scenario: Scenario) -> None:
        """Trace contains at least 2 LLM calls (intent + response generation)."""
        result = build_trace(
            scenario_id=scenario.id,
            user_message=scenario.user_message,
            tool_sequence=scenario.tool_sequence,
            output_message=scenario.output_message,
            output_structured={"intent": scenario.category, "status": "resolved"},
            total_tokens=scenario.metadata.total_tokens,
            cost_usd=scenario.metadata.cost_usd,
            latency_ms=scenario.metadata.latency_ms,
        )
        llm_steps = [s for s in result.trace.steps if s.type == "llm_call"]
        assert len(llm_steps) >= 2

    def test_all_scenarios_build_traces(self) -> None:
        """Every scenario produces a valid trace without errors."""
        for s in SCENARIOS:
            result = build_trace(
                scenario_id=s.id,
                user_message=s.user_message,
                tool_sequence=s.tool_sequence,
                output_message=s.output_message,
                output_structured={"intent": s.category, "status": "resolved"},
                total_tokens=s.metadata.total_tokens,
                cost_usd=s.metadata.cost_usd,
                latency_ms=s.metadata.latency_ms,
                tool_args_overrides=s.tool_args_overrides,
            )
            assert result.trace is not None, f"Trace build failed for {s.id}"

    def test_tool_args_overrides(self) -> None:
        """Custom tool args override defaults."""
        s = SCENARIOS_BY_ID["SC-001"]
        custom_args = {"lookup_account": {"email": "custom@test.com"}}
        result = build_trace(
            scenario_id=s.id,
            user_message=s.user_message,
            tool_sequence=s.tool_sequence,
            output_message=s.output_message,
            output_structured={"intent": s.category, "status": "resolved"},
            total_tokens=s.metadata.total_tokens,
            cost_usd=s.metadata.cost_usd,
            latency_ms=s.metadata.latency_ms,
            tool_args_overrides=custom_args,
        )
        tool_steps = [s for s in result.trace.steps if s.type == "tool_call"]
        lookup_step = next(s for s in tool_steps if s.name == "lookup_account")
        assert lookup_step.args["email"] == "custom@test.com"


# ---------------------------------------------------------------------------
# Assertion builders (structure only — no engine needed)
# ---------------------------------------------------------------------------


class TestAssertionBuilders:
    """Validate assertion chain construction without evaluating."""

    @pytest.fixture
    def scenario_and_result(self) -> tuple[Scenario, Any]:
        s = SCENARIOS_BY_ID["SC-001"]
        result = build_trace(
            scenario_id=s.id,
            user_message=s.user_message,
            tool_sequence=s.tool_sequence,
            output_message=s.output_message,
            output_structured={"intent": s.category, "status": "resolved"},
            total_tokens=s.metadata.total_tokens,
            cost_usd=s.metadata.cost_usd,
            latency_ms=s.metadata.latency_ms,
        )
        return s, result

    def test_all_judge_builds_chain(self, scenario_and_result: tuple[Scenario, Any]) -> None:
        """all_judge approach builds a chain with 4 judge assertions."""
        from assertions import build_all_judge_assertions

        s, result = scenario_and_result
        chain = build_all_judge_assertions(s, result)
        judge_assertions = [a for a in chain.assertions if a.type == "llm_judge"]
        assert len(judge_assertions) == 4

    def test_graduated_builds_chain(self, scenario_and_result: tuple[Scenario, Any]) -> None:
        """graduated approach builds a mixed chain."""
        from assertions import build_graduated_assertions

        s, result = scenario_and_result
        chain = build_graduated_assertions(s, result)
        types = {a.type for a in chain.assertions}
        # Should include deterministic AND judge types
        assert "llm_judge" in types
        assert len(chain.assertions) > 4  # More than just judge calls

    def test_deterministic_builds_chain_no_judge(
        self, scenario_and_result: tuple[Scenario, Any]
    ) -> None:
        """deterministic approach builds a chain with zero judge assertions."""
        from assertions import build_deterministic_assertions

        s, result = scenario_and_result
        chain = build_deterministic_assertions(s, result)
        judge_assertions = [a for a in chain.assertions if a.type == "llm_judge"]
        assert len(judge_assertions) == 0
        assert len(chain.assertions) > 0  # Has deterministic assertions

    def test_graduated_has_more_assertions_than_judge(
        self, scenario_and_result: tuple[Scenario, Any]
    ) -> None:
        """graduated should have more total assertions than all_judge."""
        from assertions import build_all_judge_assertions, build_graduated_assertions

        s, result = scenario_and_result
        judge_chain = build_all_judge_assertions(s, result)
        graduated_chain = build_graduated_assertions(s, result)
        assert len(graduated_chain.assertions) > len(judge_chain.assertions)

    def test_approach_builders_registry(self) -> None:
        """APPROACH_BUILDERS maps all three approaches."""
        from assertions import APPROACH_BUILDERS

        assert set(APPROACH_BUILDERS.keys()) == {"all_judge", "graduated", "deterministic"}


# ---------------------------------------------------------------------------
# Benchmark runner (unit tests)
# ---------------------------------------------------------------------------


class TestBenchmarkRunner:
    """Test runner logic without executing benchmarks."""

    def test_compute_consistency_identical(self) -> None:
        """Identical trials produce 100% consistency."""
        from run_benchmark import ScenarioTrialResult, compute_consistency

        trial = [
            ScenarioTrialResult(
                scenario_id="SC-001",
                approach="test",
                trial=0,
                assertion_count=3,
                pass_count=3,
                fail_count=0,
                cost_usd=0.0,
                duration_ms=0,
                wall_clock_ms=0.0,
                passed=True,
                pass_fail_vector=["pass", "pass", "pass"],
            ),
        ]
        # Two identical trials
        consistency = compute_consistency([trial, trial])
        assert consistency == 100.0

    def test_compute_consistency_divergent(self) -> None:
        """Divergent trials produce < 100% consistency."""
        from run_benchmark import ScenarioTrialResult, compute_consistency

        trial_a = [
            ScenarioTrialResult(
                scenario_id="SC-001",
                approach="test",
                trial=0,
                assertion_count=2,
                pass_count=2,
                fail_count=0,
                cost_usd=0.0,
                duration_ms=0,
                wall_clock_ms=0.0,
                passed=True,
                pass_fail_vector=["pass", "pass"],
            ),
        ]
        trial_b = [
            ScenarioTrialResult(
                scenario_id="SC-001",
                approach="test",
                trial=1,
                assertion_count=2,
                pass_count=1,
                fail_count=1,
                cost_usd=0.0,
                duration_ms=0,
                wall_clock_ms=0.0,
                passed=False,
                pass_fail_vector=["pass", "fail"],
            ),
        ]
        consistency = compute_consistency([trial_a, trial_b])
        assert consistency == 50.0

    def test_compute_consistency_empty(self) -> None:
        """Empty input returns 100%."""
        from run_benchmark import compute_consistency

        assert compute_consistency([]) == 100.0

    def test_count_judge_calls_deterministic(self) -> None:
        """Deterministic approach has zero judge calls."""
        from run_benchmark import count_judge_calls

        assert count_judge_calls("deterministic", SCENARIOS) == 0

    def test_count_judge_calls_all_judge(self) -> None:
        """all_judge approach has 4 calls per scenario."""
        from run_benchmark import count_judge_calls

        assert count_judge_calls("all_judge", SCENARIOS) == 4 * len(SCENARIOS)

    def test_count_judge_calls_graduated(self) -> None:
        """graduated approach judge calls match sum of judge_criteria lengths."""
        from run_benchmark import count_judge_calls

        expected = sum(len(s.judge_criteria) for s in SCENARIOS)
        assert count_judge_calls("graduated", SCENARIOS) == expected

    def test_generate_report_structure(self) -> None:
        """Report has expected top-level keys."""
        from run_benchmark import ApproachSummary, generate_report

        summaries = [
            ApproachSummary(
                approach="test",
                total_cost_usd=0.0,
                total_wall_clock_ms=0.0,
                total_assertions=0,
                total_pass=0,
                total_fail=0,
                consistency_pct=100.0,
                avg_cost_per_scenario=0.0,
                avg_wall_clock_per_scenario_ms=0.0,
                judge_call_count=0,
            ),
        ]
        report = generate_report(summaries, {"test": []}, {"dry_run": True})
        assert "metadata" in report
        assert "summary" in report
        assert "scenarios" in report
        assert "test" in report["summary"]

    def test_simulation_fixture_evaluates(self) -> None:
        """_SimulationFixture returns passing results for any chain."""
        from run_benchmark import _SimulationFixture

        from assertions import build_deterministic_assertions

        s = SCENARIOS_BY_ID["SC-001"]
        result = build_trace(
            scenario_id=s.id,
            user_message=s.user_message,
            tool_sequence=s.tool_sequence,
            output_message=s.output_message,
            output_structured={"intent": s.category, "status": "resolved"},
            total_tokens=s.metadata.total_tokens,
            cost_usd=s.metadata.cost_usd,
            latency_ms=s.metadata.latency_ms,
        )
        chain = build_deterministic_assertions(s, result)
        fixture = _SimulationFixture()
        eval_result = fixture.evaluate(chain)

        assert eval_result.total_cost == 0.0
        assert eval_result.total_duration_ms == 0
        assert all(r.status == "pass" for r in eval_result.assertion_results)

    def test_parse_args_defaults(self) -> None:
        """Default CLI args are valid."""
        from run_benchmark import parse_args

        with patch("sys.argv", ["run_benchmark.py"]):
            args = parse_args()
        assert args.trials == 3
        assert args.dry_run is False
        assert args.approach is None
        assert args.scenarios is None
        assert args.budget == 15.0
        assert args.use_cache is False
