"""Direct tests for the DAG machinery extracted from parallel_generate.py.

That code shipped with one indirect assertion covering it, which is why the
plan required the extraction to land with tests of its own. The properties
asserted here are the ones both callers depend on: a level's members are
mutually independent, the output is a partition of the input, ordering is
stable, and the two cycle policies differ in exactly the intended way.
"""

from __future__ import annotations

import random

import pytest

from kgf.dag import (
    CyclePolicy,
    DependencyCycleError,
    DisjointSet,
    depth_tiers,
    find_cycles,
    levels,
    strongly_connected_components,
)


class TestDisjointSet:
    def test_unrelated_items_stay_in_their_own_sets(self):
        dsu = DisjointSet(["a", "b", "c"])
        assert [sorted(group) for group in dsu.groups()] == [["a"], ["b"], ["c"]]

    def test_union_is_transitive(self):
        dsu = DisjointSet(["a", "b", "c", "d"])
        dsu.union("a", "b")
        dsu.union("b", "c")
        assert dsu.find("a") == dsu.find("c")
        assert dsu.find("d") != dsu.find("a")

    def test_groups_are_ordered_by_first_appearance(self):
        """_partition_manifest relies on this: cluster order must follow the
        manifest's order, or identical manifests produce different groupings."""
        dsu = DisjointSet(["z", "y", "x"])
        dsu.union("z", "x")
        assert dsu.groups() == [["z", "x"], ["y"]]

    def test_union_of_an_item_with_itself_is_a_no_op(self):
        dsu = DisjointSet(["a"])
        dsu.union("a", "a")
        assert dsu.groups() == [["a"]]


class TestStronglyConnectedComponents:
    def test_a_chain_yields_one_component_per_node(self):
        components = strongly_connected_components(["a", "b", "c"], {"a": {"b"}, "b": {"c"}})
        assert sorted(sorted(c) for c in components) == [["a"], ["b"], ["c"]]

    def test_a_cycle_collapses_into_one_component(self):
        components = strongly_connected_components(
            ["a", "b", "c"], {"a": {"b"}, "b": {"c"}, "c": {"a"}}
        )
        assert len(components) == 1
        assert sorted(components[0]) == ["a", "b", "c"]

    def test_edges_leaving_the_node_set_are_ignored(self):
        """Callers pass one subgraph at a time -- a dependency on a file in a
        different cluster must not drag that file into this computation."""
        components = strongly_connected_components(["a"], {"a": {"outside"}})
        assert components == [["a"]]

    def test_a_node_with_no_edges_at_all_is_its_own_component(self):
        assert strongly_connected_components(["lonely"], {}) == [["lonely"]]


class TestFindCycles:
    def test_an_acyclic_graph_has_none(self):
        assert find_cycles(["a", "b"], {"a": {"b"}}) == []

    def test_a_mutual_pair_is_a_cycle(self):
        cycles = find_cycles(["a", "b"], {"a": {"b"}, "b": {"a"}})
        assert len(cycles) == 1 and sorted(cycles[0]) == ["a", "b"]

    def test_a_self_dependency_is_a_cycle(self):
        """A file manifest cannot express this; a hand-authored topology can,
        so it is checked rather than assumed away."""
        assert find_cycles(["a"], {"a": {"a"}}) == [["a"]]

    def test_every_cycle_is_reported_not_just_the_first(self):
        edges = {"a": {"b"}, "b": {"a"}, "c": {"d"}, "d": {"c"}, "e": set()}
        assert len(find_cycles(["a", "b", "c", "d", "e"], edges)) == 2


class TestDepthTiers:
    def test_tiers_are_in_ascending_dependency_depth(self):
        tiers = depth_tiers(["a", "b", "c"], {"b": {"a"}, "c": {"b"}})
        assert tiers == [["a"], ["b"], ["c"]]

    def test_independent_nodes_share_the_first_tier(self):
        assert depth_tiers(["a", "b"], {}) == [["a", "b"]]

    def test_input_order_is_preserved_within_a_tier(self):
        assert depth_tiers(["z", "y", "x"], {}) == [["z", "y", "x"]]

    def test_a_cycle_is_condensed_into_a_single_tier(self):
        """This is the generalisation of the old mutual-dependency tie rule:
        free-text-derived edges are not provably acyclic, so a cycle must be
        schedulable rather than fatal on this path."""
        tiers = depth_tiers(["a", "b", "c"], {"a": {"b"}, "b": {"a"}, "c": {"a"}})
        assert tiers == [["a", "b"], ["c"]]

    def test_empty_input_yields_no_tiers(self):
        assert depth_tiers([], {}) == []


class TestLevels:
    def test_a_chain_produces_one_node_per_level(self):
        assert levels(["a", "b", "c"], {"b": {"a"}, "c": {"b"}}) == [["a"], ["b"], ["c"]]

    def test_a_diamond_puts_both_middles_in_one_level(self):
        edges = {"left": {"top"}, "right": {"top"}, "bottom": {"left", "right"}}
        assert levels(["top", "left", "right", "bottom"], edges) == [
            ["top"],
            ["left", "right"],
            ["bottom"],
        ]

    def test_every_dependency_sits_in_a_strictly_lower_level(self):
        """The one property both callers actually rely on."""
        random.seed(20260913)
        for _ in range(200):
            count = random.randint(1, 12)
            nodes = [f"n{i}" for i in range(count)]
            edges = {
                nodes[i]: {nodes[j] for j in range(i) if random.random() < 0.35}
                for i in range(count)
            }
            computed = levels(nodes, edges)
            level_of = {node: i for i, level in enumerate(computed) for node in level}
            assert set(level_of) == set(nodes)
            assert sum(len(level) for level in computed) == count
            for node, deps in edges.items():
                for dep in deps:
                    assert level_of[dep] < level_of[node]

    def test_the_result_is_a_partition_with_no_empty_level(self):
        computed = levels(["a", "b", "c", "d"], {"c": {"a"}, "d": {"c"}})
        assert all(level for level in computed)
        flattened = [node for level in computed for node in level]
        assert sorted(flattened) == ["a", "b", "c", "d"]
        assert len(flattened) == len(set(flattened))

    def test_fatal_is_the_default_policy(self):
        """An authored topology must not have to opt in to correctness."""
        with pytest.raises(DependencyCycleError):
            levels(["a", "b"], {"a": {"b"}, "b": {"a"}})

    def test_fatal_names_the_members_of_the_cycle(self):
        """A policy that reports a cycle has to say which nodes are in it,
        which is why detection is by SCC and not by a back-edge marker."""
        with pytest.raises(DependencyCycleError) as raised:
            levels(["a", "b", "c"], {"a": {"b"}, "b": {"c"}, "c": {"a"}}, cycle_policy=CyclePolicy.FATAL)
        assert sorted(raised.value.cycles[0]) == ["a", "b", "c"]
        assert "a" in str(raised.value)

    def test_collapse_returns_one_level_and_reports(self):
        seen: list[list[list[str]]] = []
        computed = levels(
            ["a", "b", "c"],
            {"a": {"b"}, "b": {"a"}},
            cycle_policy=CyclePolicy.COLLAPSE,
            on_cycle=seen.append,
        )
        assert computed == [["a", "b", "c"]]
        assert len(seen) == 1 and sorted(seen[0][0]) == ["a", "b"]

    def test_collapse_without_a_callback_still_collapses(self):
        computed = levels(["a", "b"], {"a": {"b"}, "b": {"a"}}, cycle_policy=CyclePolicy.COLLAPSE)
        assert computed == [["a", "b"]]

    def test_empty_input_yields_no_levels(self):
        assert levels([], {}) == []

    def test_a_dependency_outside_the_node_set_is_ignored(self):
        assert levels(["a"], {"a": {"not-a-node"}}) == [["a"]]

    def test_a_long_chain_does_not_exhaust_the_stack(self):
        """Both the SCC pass and the depth pass are iterative for this reason;
        the originals were recursive and would have raised here."""
        count = 5000
        nodes = [f"n{i}" for i in range(count)]
        edges = {nodes[i]: {nodes[i - 1]} for i in range(1, count)}
        computed = levels(nodes, edges)
        assert len(computed) == count
        assert computed[0] == ["n0"] and computed[-1] == [f"n{count - 1}"]

    def test_levels_are_stable_across_runs(self):
        edges = {"c": {"a"}, "d": {"b"}}
        nodes = ["a", "b", "c", "d"]
        assert levels(nodes, edges) == levels(nodes, edges)
