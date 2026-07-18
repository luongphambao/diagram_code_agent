"""Well-Architected semantic audit — ported from drawio-ai-kit/src/core.mjs
auditArchitecture: database in a public subnet (Security), single NAT gateway
across multiple AZs (Reliability SPOF). XML-level (audit_architecture, AWS-gated
on mxgraph.aws4.*) and spec-level (audit_spec_architecture, refined/non-AWS)
twins are both advisory-only — they must never turn into errors/warnings or
move the production_scorecard.
"""

from __future__ import annotations

import domain.validation.validate_drawio as vd
from prettygraph.native import Diagram, group, icon, render_tree
from prettygraph.native.layout_engine import subnet


def _diagram(*, subnet_label: str, az_count: int, nat_count: int) -> Diagram:
    d = Diagram("network")
    azs = []
    for i in range(az_count):
        azs.append(group(f"az{i}", "group_availability_zone", f"AZ-{i}", {"dir": "col"}, [
            subnet(f"sub{i}", subnet_label if i == 0 else "Private Subnet", [
                icon(f"rds{i}", "rds", f"DB {i}") if i == 0
                else icon(f"ec2{i}", "ec2", f"Web {i}"),
            ]),
        ]))
    nats = [icon(f"nat{i}", "nat_gateway", f"NAT {i}") for i in range(nat_count)]
    tree = group("vpc", "group_vpc", "VPC", {"dir": "row", "gap": 30}, azs + nats)
    render_tree(d, tree)
    d.title("t")
    return d


def _xml(**kw) -> str:
    return _diagram(**kw).mxfile("t")


# --------------------------------------------------------------------------- #
# XML-level: audit_architecture (AWS-gated)
# --------------------------------------------------------------------------- #

def test_db_in_public_subnet_flagged():
    advice = vd.audit_architecture(_xml(subnet_label="Public Subnet", az_count=1, nat_count=1))
    assert any("well-arch" in a and "PUBLIC subnet" in a for a in advice)


def test_db_in_private_subnet_silent():
    advice = vd.audit_architecture(_xml(subnet_label="Private Subnet", az_count=1, nat_count=1))
    assert not any("PUBLIC subnet" in a for a in advice)


def test_single_nat_multi_az_flagged():
    advice = vd.audit_architecture(_xml(subnet_label="Private Subnet", az_count=2, nat_count=1))
    assert any("well-arch" in a and "single point of failure" in a for a in advice)


def test_two_nat_multi_az_silent():
    advice = vd.audit_architecture(_xml(subnet_label="Private Subnet", az_count=2, nat_count=2))
    assert not any("single point of failure" in a for a in advice)


def test_gated_on_aws_stencils():
    generic_xml = ('<mxfile><diagram name="t" id="d1"><mxGraphModel><root>'
                   '<mxCell id="0"/><mxCell id="1" parent="0"/>'
                   '</root></mxGraphModel></diagram></mxfile>')
    assert vd.audit_architecture(generic_xml) == []


def test_wired_into_audit_xml_and_validate_file(tmp_path):
    p = tmp_path / "waf.drawio"
    p.write_text(_xml(subnet_label="Public Subnet", az_count=2, nat_count=1), encoding="utf-8")
    report = vd.validate_file(str(p))
    assert any("well-arch" in a for a in report["advice"])
    # advisory only — never an error/warning, never blocks the gate
    assert report["error_count"] == 0
    assert report["ok"]


def test_well_arch_advice_is_scorecard_neutral(tmp_path):
    """Advice-only findings must not move production_scorecard's total."""
    clean = _xml(subnet_label="Private Subnet", az_count=2, nat_count=2)
    flagged = _xml(subnet_label="Public Subnet", az_count=2, nat_count=1)
    p1, p2 = tmp_path / "clean.drawio", tmp_path / "flagged.drawio"
    p1.write_text(clean, encoding="utf-8")
    p2.write_text(flagged, encoding="utf-8")
    r1, r2 = vd.validate_file(str(p1)), vd.validate_file(str(p2))
    sc1 = vd.production_scorecard(r1, {"edges": 1})
    sc2 = vd.production_scorecard(r2, {"edges": 1})
    assert sc1["total"] == sc2["total"]


# --------------------------------------------------------------------------- #
# Spec-level: audit_spec_architecture (refined / non-AWS)
# --------------------------------------------------------------------------- #

def _spec(*, subnet_zone: str, az_count: int, nat_count: int) -> dict:
    clusters = [{"id": "vpc", "label": "VPC", "zone": "vpc"}]
    nodes = []
    for i in range(az_count):
        az_id = f"az{i}"
        clusters.append({"id": az_id, "label": f"AZ-{i}", "parent": "vpc", "zone": "az"})
        sub_id = f"sub{i}"
        clusters.append({"id": sub_id, "label": f"Subnet {i}", "parent": az_id,
                         "zone": subnet_zone if i == 0 else "subnet_private"})
        if i == 0:
            nodes.append({"id": f"db{i}", "label": f"DB {i}", "type": "database", "cluster": sub_id})
        else:
            nodes.append({"id": f"web{i}", "label": f"Web {i}", "type": "service", "cluster": sub_id})
    for i in range(nat_count):
        nodes.append({"id": f"nat{i}", "label": f"NAT Gateway {i}", "type": "gateway", "cluster": "vpc"})
    return {"provider": "aws", "nodes": nodes, "clusters": clusters, "edges": []}


def test_spec_db_in_public_subnet_flagged():
    advice = vd.audit_spec_architecture(_spec(subnet_zone="subnet_public", az_count=1, nat_count=1))
    assert any("well-arch" in a and "PUBLIC subnet" in a for a in advice)


def test_spec_db_in_private_subnet_silent():
    advice = vd.audit_spec_architecture(_spec(subnet_zone="subnet_private", az_count=1, nat_count=1))
    assert not any("PUBLIC subnet" in a for a in advice)


def test_spec_single_nat_multi_az_flagged():
    advice = vd.audit_spec_architecture(_spec(subnet_zone="subnet_private", az_count=2, nat_count=1))
    assert any("well-arch" in a and "single point of failure" in a for a in advice)


def test_spec_two_nat_multi_az_silent():
    advice = vd.audit_spec_architecture(_spec(subnet_zone="subnet_private", az_count=2, nat_count=2))
    assert not any("single point of failure" in a for a in advice)


def test_spec_empty_is_silent():
    assert vd.audit_spec_architecture({"nodes": [], "clusters": [], "edges": []}) == []
