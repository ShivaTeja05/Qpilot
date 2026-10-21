"""Rule packs: the shipped pack, loading, refusal of malformed packs, edits and evaluation."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from qpilot.core import rules as core_rules
from qpilot.core.rules import (
    Check,
    Finding,
    RulePack,
    RulePackError,
    check_pack_against,
    diff_packs,
    dump_pack_yaml,
    evaluate_pack,
    load_pack,
    override,
    pack_from_json,
    pack_hash,
    parse_pack,
    summarise,
)
from qpilot.qpcr import gate_rules
from qpilot.qpcr.gate_rules import CHECKS, PACKS_DIR_CANDIDATES, pack_path, resolve_pack

ROOT = Path(__file__).resolve().parents[2]

MINIMAL = """
pack: lab-pack
version: 1.0.0
label: Research use only. A test pack.
sources:
  lab_default: {citation: Unsourced test default.}
rules:
  - id: G-ONE
    name: One rule
    check: ntc_gap
    statement: A statement.
    sources: [lab_default]
"""


def extra(line: str) -> str:
    """The minimal pack with one more line in its rule."""
    return MINIMAL.rstrip("\n") + f"\n    {line}\n"


def minimal(**replace: str) -> str:
    text = MINIMAL
    for old, new in replace.items():
        assert old in text, old
        text = text.replace(old, new)
    return text


# ---------- the shipped pack ----------


def test_the_shipped_pack_loads_and_matches_this_builds_evaluators():
    pack = resolve_pack()
    assert pack.pack == "research-default" and pack.version == "1.0.0"
    assert "research use" in pack.label.lower()
    assert [r.id for r in pack.rules] == [
        "G-TYPED",
        "G-NTC-1",
        "G-NAC",
        "G-NRT",
        "G-POS",
        "G-STD",
        "G-REP",
    ]
    assert check_pack_against(pack, CHECKS) == []
    for rule in pack.rules:
        assert rule.sources and all(s in pack.sources for s in rule.sources)
        # informational rules carry no options; the others offer only what the check can do
        assert set(rule.consequence_scope) <= set(CHECKS[rule.check].options)
    assert pack.consequence.magnitude_log2 == 0.5
    assert pack.consequence.magnitude_agreement == 0.10


def test_the_pack_hash_is_of_its_content_not_its_bytes():
    path = pack_path()
    pack = load_pack(path)
    assert pack.hash == pack_hash(pack) and len(pack.hash) == 64
    # comments and layout do not count
    text = "# a comment\n\n" + path.read_text(encoding="utf-8")
    assert parse_pack(text).hash == pack.hash
    # a threshold does
    edited = override(pack, "1.0.1", params={"G-NTC-1": {"k_cycles": 4}})
    assert edited.hash != pack.hash
    assert pack.ref() == {"pack": "research-default", "version": "1.0.0", "hash": pack.hash}
    # the canonical JSON a record keeps loads back to the same pack
    assert pack_from_json(core_rules.canonical_pack_json(pack)).hash == pack.hash
    # and the YAML a lab saves loads back too
    assert parse_pack(dump_pack_yaml(edited)).hash == edited.hash


def test_a_pack_is_found_by_name_path_or_canonical_json(tmp_path):
    pack = resolve_pack("research-default")
    assert resolve_pack(pack) is pack
    assert resolve_pack(pack_path()).hash == pack.hash
    j = tmp_path / "pack.json"
    j.write_text(core_rules.canonical_pack_json(pack), encoding="utf-8")
    assert resolve_pack(j).hash == pack.hash
    for bad in ("../research-default", "a/b", ".hidden", ""):
        with pytest.raises(ValueError):
            pack_path(bad)
    with pytest.raises(FileNotFoundError):
        pack_path("no-such-pack")


def test_the_pack_ships_in_the_wheel():
    """``PACKS_DIR_CANDIDATES`` looks in ``qpilot/_packs`` first: the wheel must put it there."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["force-include"]["packs"] == "qpilot/_packs"
    assert PACKS_DIR_CANDIDATES[0] == Path(gate_rules.__file__).resolve().parents[1] / "_packs"
    assert (ROOT / "packs" / "research-default.yaml").is_file()


# ---------- refusals ----------


@pytest.mark.parametrize(
    ("text", "words"),
    [
        (minimal(**{"Research use only. A test pack.": "A clinical pack."}), "Research use"),
        (minimal(**{"id: G-ONE": "id: g-one"}), "rule id"),
        (minimal(**{"check: ntc_gap": "check: NTC-gap"}), "check name"),
        (minimal(**{"sources: [lab_default]": "sources: [elsewhere]"}), "does not list"),
        (minimal(**{"sources: [lab_default]": "sources: []"}), "sources"),
        (minimal(**{"version: 1.0.0": "version: one"}), "version"),
        (minimal(**{"pack: lab-pack": "pack: Lab Pack"}), "pack name"),
        (
            extra("colour: red"),
            "colour",
        ),
        (
            extra("severity: {not_applicable: pass}"),
            "cannot be remapped",
        ),
        (
            extra("params: {k_cycles: .nan}"),
            "not a number",
        ),
        (
            extra("severity: {clean: perfect}"),
            "severity",
        ),
        (
            minimal(
                **{"{citation: Unsourced test default.}": "{citation: x, url: 'http://x.org'}"}
            ),
            "https",
        ),
        ("pack: [a, b\n", "not valid YAML"),
        ("- a\n- b\n", "mapping at the top level"),
        ("a: &x 1\nb: *x\n", "aliases"),
        ("pack: a\npack: b\n", "twice"),
    ],
)
def test_malformed_packs_are_refused_with_the_reason(text, words):
    with pytest.raises(RulePackError) as err:
        parse_pack(text)
    assert words.lower() in str(err.value).lower()


def test_two_rules_with_one_id_are_refused():
    rule = MINIMAL.split("rules:\n")[1]
    with pytest.raises(RulePackError, match="appear twice"):
        parse_pack(MINIMAL + rule.replace("  - id", "  - id", 1))


def test_size_and_depth_caps(tmp_path):
    big = MINIMAL + "# " + "x" * core_rules.MAX_PACK_BYTES + "\n"
    with pytest.raises(RulePackError, match="larger than"):
        parse_pack(big)
    deep = "pack: a\nx: " + "[" * 20 + "]" * 20 + "\n"
    with pytest.raises(RulePackError, match="deeper"):
        parse_pack(deep)
    path = tmp_path / "big.yaml"
    path.write_text(big, encoding="utf-8")
    with pytest.raises(RulePackError, match="larger than"):
        load_pack(path)
    latin = tmp_path / "latin.yaml"
    latin.write_bytes("label: caf\xe9\n".encode("latin-1"))
    with pytest.raises(RulePackError, match="UTF-8"):
        load_pack(latin)
    with pytest.raises(RulePackError):
        load_pack(tmp_path / "missing.yaml")
    with pytest.raises(RulePackError, match="not a file"):
        load_pack(tmp_path)
    with pytest.raises(RulePackError):
        pack_from_json("{}")


# ---------- edits ----------


def test_a_labs_edit_is_a_new_version_based_on_the_old_hash():
    base = resolve_pack()
    edited = override(
        base,
        "1.1.0-lab.1",
        params={"G-NTC-1": {"k_cycles": 4}},
        severity={"G-STD": {"few_replicates": "pass"}},
        enabled={"G-POS": False},
    )
    assert edited.based_on is not None and edited.based_on.hash == base.hash
    assert base.rule("G-NTC-1").params["k_cycles"] == 5  # the base is untouched
    changes = {(c.get("rule"), c["what"]) for c in diff_packs(base, edited)}
    assert {
        (None, "version"),
        ("G-NTC-1", "params.k_cycles"),
        ("G-STD", "severity.few_replicates"),
        ("G-POS", "enabled"),
    } <= changes
    with pytest.raises(RulePackError, match="new version"):
        override(base, base.version)
    with pytest.raises(RulePackError, match="no such rule"):
        override(base, "2.0.0", params={"G-NOPE": {"k": 1}})


# ---------- verdicts ----------


def test_outcomes_map_to_verdicts_through_the_pack():
    rule = resolve_pack().rule("G-NTC-1")
    assert rule.verdict_for("tainted") == "fail"
    assert rule.verdict_for("clean") == "pass"
    assert rule.verdict_for("not_applicable") == "not_applicable"
    assert rule.verdict_for("never_heard_of", {"never_heard_of": "pass"}) == "pass"
    assert rule.verdict_for("never_heard_of") == "warn"  # never a silent pass
    lab = override(resolve_pack(), "1.0.1", severity={"G-NTC-1": {"tainted": "warn"}})
    assert lab.rule("G-NTC-1").verdict_for("tainted") == "warn"


def test_a_not_applicable_finding_needs_a_reason_code_and_cited_facts_must_be_listed():
    with pytest.raises(ValueError, match="machine reason"):
        Finding(scope={}, outcome="not_applicable", reason="No.")
    with pytest.raises(ValueError, match="does not list"):
        Finding(scope={}, outcome="clean", reason="{{f_gate_x_abc}} wells.", facts=[])
    ok = Finding(
        scope={}, outcome="clean", reason="{{f_gate_x_abc}} wells.", facts=["f_gate_x_abc"]
    )
    assert ok.facts == ["f_gate_x_abc"]


def _pack(check: str = "probe", scope: str = "[keep_out]") -> RulePack:
    return parse_pack(
        minimal(
            **{
                "check: ntc_gap": f"check: {check}",
            }
        ).rstrip("\n")
        + f"\n    consequence_scope: {scope}\n"
    )


def test_evaluate_pack_turns_findings_into_verdicts_and_keeps_only_allowed_options():
    def probe(rule, ctx):
        yield Finding(
            scope={"plate": "P1"},
            outcome="bad",
            reason="Bad.",
            flagged=["P1/A1"],
            options={"keep_out": ["P1/A1"], "not_in_pack": ["P1/A2"]},
        )
        yield Finding(
            scope={"plate": "P2"}, outcome="good", reason="Good.", options={"keep_out": ["x"]}
        )

    checks = {
        "probe": Check(name="probe", evaluate=probe, outcomes={"bad": "fail", "good": "pass"})
    }
    bad, good = evaluate_pack(_pack(), checks, None)
    assert (bad.verdict, bad.options, bad.flagged) == ("fail", {"keep_out": ["P1/A1"]}, ["P1/A1"])
    assert good.verdict == "pass" and good.options == {}  # a pass carries no options
    assert bad.key == "G-ONE|plate=P1"
    informational = evaluate_pack(_pack(scope="[]"), checks, None)[0]
    assert informational.options == {}
    assert summarise([bad, good]) == {"pass": 1, "warn": 0, "fail": 1, "not_applicable": 0}
    assert summarise([]) == dict.fromkeys(("pass", "warn", "fail", "not_applicable"), 0)


def test_a_rule_without_an_evaluator_is_not_applicable_never_a_pass():
    (ev,) = evaluate_pack(_pack(check="unknown_check"), {}, None)
    assert ev.verdict == "not_applicable" and ev.code == "no_evaluator"
    assert check_pack_against(_pack(check="unknown_check"), {}) == [
        "G-ONE: no evaluator for check 'unknown_check' in this build"
    ]


def test_a_disabled_rule_is_not_evaluated():
    pack = override(
        resolve_pack(), "1.0.1", enabled={r.id: False for r in resolve_pack().rules[1:]}
    )
    seen = []

    def spy(rule, ctx):
        seen.append(rule.id)
        return iter(())

    checks = {name: c.model_copy(update={"evaluate": spy}) for name, c in CHECKS.items()}
    evaluate_pack(pack, checks, None)
    assert seen == ["G-TYPED"]


def test_check_pack_against_names_what_does_not_fit():
    pack = parse_pack(
        minimal(
            **{
                "    sources: [lab_default]": "    sources: [lab_default]\n"
                "    severity: {invented: fail}\n    consequence_scope: [launder]"
            }
        )
    )
    problems = check_pack_against(pack, CHECKS)
    assert any("never reports outcome 'invented'" in p for p in problems)
    assert any("offers no option 'launder'" in p for p in problems)


def test_every_shipped_rule_says_what_it_needs_and_where_its_threshold_comes_from():
    pack = resolve_pack()
    data = json.loads(core_rules.canonical_pack_json(pack))
    for rule in data["rules"]:
        assert rule["statement"] and rule["name"]
        for key in rule["params"]:
            assert key.islower()
    assert "lab_default" in pack.sources  # unsourced defaults say so
