"""Unit tests for the FinOps Zombie Hunter Lambda function."""

import os
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

# Detection must default to a safe (dry-run) posture for the import-time config.
os.environ["DRY_RUN"] = "true"
os.environ["SNS_TOPIC_ARN"] = "arn:aws:sns:us-east-1:123456789012:TestTopic"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import hunter  # noqa: E402
from hunter import (  # noqa: E402
    _age_days,
    _is_protected,
    build_report,
    check_ebs_zombies,
    check_elastic_ip_zombies,
    check_nat_gw_zombies,
    check_rds_zombies,
    lambda_handler,
)

# --- Helpers ---------------------------------------------------------------


def _client_error(operation):
    return ClientError({"Error": {"Code": "Boom", "Message": "fail"}}, operation)


def _paginated(client, page):
    """Configure a mock client's paginator to yield a single page."""
    client.get_paginator.return_value.paginate.return_value = [page]


def _old():
    return datetime.now(UTC) - timedelta(days=30)


def _recent():
    return datetime.now(UTC) - timedelta(days=1)


@pytest.fixture
def ec2():
    return MagicMock()


@pytest.fixture
def cw():
    return MagicMock()


@pytest.fixture
def rds():
    return MagicMock()


# --- Pure helpers ----------------------------------------------------------


class TestHelpers:
    def test_is_protected_detects_keep_tag(self):
        assert _is_protected([{"Key": "keep", "Value": "true"}]) is True

    def test_is_protected_is_case_insensitive(self):
        assert _is_protected([{"Key": "DoNotDelete", "Value": "x"}]) is True

    def test_is_protected_false_for_unrelated_tags(self):
        assert _is_protected([{"Key": "env", "Value": "dev"}]) is False

    def test_is_protected_handles_none(self):
        assert _is_protected(None) is False

    def test_age_days_none_when_missing(self):
        assert _age_days(None) is None

    def test_age_days_counts_whole_days(self):
        age = _age_days(_old())
        assert age is not None
        assert age >= 29


# --- EBS volumes (deletable) ----------------------------------------------


class TestCheckEbsZombies:
    def test_flags_old_unattached_in_dry_run(self, ec2):
        _paginated(
            ec2,
            {
                "Volumes": [
                    {"VolumeId": "vol-1", "Size": 100, "CreateTime": _old()},
                ]
            },
        )

        findings = check_ebs_zombies(ec2, "us-east-1", dry_run=True, min_age_days=7)

        assert len(findings) == 1
        assert findings[0]["action"] == "would_delete"
        assert findings[0]["monthly_cost"] == 10.0
        ec2.delete_volume.assert_not_called()

    def test_skips_volume_younger_than_threshold(self, ec2):
        _paginated(
            ec2,
            {
                "Volumes": [
                    {"VolumeId": "vol-young", "Size": 50, "CreateTime": _recent()},
                ]
            },
        )

        findings = check_ebs_zombies(ec2, "us-east-1", dry_run=False, min_age_days=7)

        assert findings[0]["action"] == "skipped"
        ec2.delete_volume.assert_not_called()

    def test_skips_volume_with_keep_tag(self, ec2):
        _paginated(
            ec2,
            {
                "Volumes": [
                    {
                        "VolumeId": "vol-keep",
                        "Size": 50,
                        "CreateTime": _old(),
                        "Tags": [{"Key": "keep", "Value": "true"}],
                    },
                ]
            },
        )

        findings = check_ebs_zombies(ec2, "us-east-1", dry_run=False, min_age_days=7)

        assert findings[0]["action"] == "skipped"
        assert "keep tag" in findings[0]["skip_reason"]
        ec2.delete_volume.assert_not_called()

    def test_deletes_when_not_dry_run(self, ec2):
        _paginated(
            ec2,
            {
                "Volumes": [
                    {"VolumeId": "vol-del", "Size": 200, "CreateTime": _old()},
                ]
            },
        )

        findings = check_ebs_zombies(ec2, "us-east-1", dry_run=False, min_age_days=7)

        assert findings[0]["action"] == "deleted"
        ec2.delete_volume.assert_called_once_with(VolumeId="vol-del")

    def test_delete_failure_is_skipped_not_raised(self, ec2):
        _paginated(
            ec2,
            {
                "Volumes": [
                    {"VolumeId": "vol-err", "Size": 10, "CreateTime": _old()},
                ]
            },
        )
        ec2.delete_volume.side_effect = _client_error("DeleteVolume")

        findings = check_ebs_zombies(ec2, "us-east-1", dry_run=False, min_age_days=7)

        assert findings[0]["action"] == "skipped"
        assert "delete failed" in findings[0]["skip_reason"]

    def test_returns_empty_when_no_volumes(self, ec2):
        _paginated(ec2, {"Volumes": []})

        assert check_ebs_zombies(ec2, "us-east-1", True, 7) == []

    def test_volume_exactly_at_threshold_is_not_skipped(self, ec2):
        # Guard is `age < min_age_days`, so a volume AT the threshold is eligible.
        _paginated(
            ec2,
            {
                "Volumes": [
                    {
                        "VolumeId": "vol-boundary",
                        "Size": 10,
                        "CreateTime": datetime.now(UTC) - timedelta(days=7, minutes=1),
                    },
                ]
            },
        )

        findings = check_ebs_zombies(ec2, "us-east-1", dry_run=True, min_age_days=7)

        assert findings[0]["action"] == "would_delete"


# --- Elastic IPs (deletable) ----------------------------------------------


class TestCheckElasticIpZombies:
    def test_flags_unassociated_in_dry_run(self, ec2):
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {"PublicIp": "1.2.3.4", "AllocationId": "eipalloc-a"},
            ]
        }

        findings = check_elastic_ip_zombies(ec2, "us-east-1", dry_run=True)

        assert len(findings) == 1
        assert findings[0]["action"] == "would_delete"
        ec2.release_address.assert_not_called()

    def test_ignores_associated_eips(self, ec2):
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {
                    "PublicIp": "1.2.3.4",
                    "AllocationId": "eipalloc-a",
                    "AssociationId": "eipassoc-1",
                },
            ]
        }

        assert check_elastic_ip_zombies(ec2, "us-east-1", dry_run=True) == []

    def test_releases_when_not_dry_run(self, ec2):
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {"PublicIp": "5.6.7.8", "AllocationId": "eipalloc-b"},
            ]
        }

        findings = check_elastic_ip_zombies(ec2, "us-east-1", dry_run=False)

        assert findings[0]["action"] == "deleted"
        ec2.release_address.assert_called_once_with(AllocationId="eipalloc-b")

    def test_skips_eip_with_keep_tag(self, ec2):
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {
                    "PublicIp": "9.9.9.9",
                    "AllocationId": "eipalloc-c",
                    "Tags": [{"Key": "Keep", "Value": "yes"}],
                },
            ]
        }

        findings = check_elastic_ip_zombies(ec2, "us-east-1", dry_run=False)

        assert findings[0]["action"] == "skipped"
        ec2.release_address.assert_not_called()

    def test_describe_failure_returns_empty(self, ec2):
        ec2.describe_addresses.side_effect = _client_error("DescribeAddresses")

        assert check_elastic_ip_zombies(ec2, "us-east-1", dry_run=True) == []


# --- RDS instances (report-only) ------------------------------------------


class TestCheckRdsZombies:
    def test_reports_idle_instance(self, rds, cw):
        _paginated(rds, {"DBInstances": [{"DBInstanceIdentifier": "db-idle"}]})
        cw.get_metric_statistics.return_value = {
            "Datapoints": [{"Average": 0}, {"Average": 0}]
        }

        findings = check_rds_zombies(rds, cw, "us-east-1")

        assert findings[0]["action"] == "report_only"
        assert findings[0]["type"] == "RDS"

    def test_ignores_active_instance(self, rds, cw):
        _paginated(rds, {"DBInstances": [{"DBInstanceIdentifier": "db-busy"}]})
        cw.get_metric_statistics.return_value = {"Datapoints": [{"Average": 7.0}]}

        assert check_rds_zombies(rds, cw, "us-east-1") == []

    def test_reports_instance_with_no_datapoints(self, rds, cw):
        _paginated(rds, {"DBInstances": [{"DBInstanceIdentifier": "db-nometrics"}]})
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        findings = check_rds_zombies(rds, cw, "us-east-1")

        assert findings[0]["action"] == "report_only"

    def test_never_deletes_an_instance(self, rds, cw):
        # RDS is report-only: a future edit adding deletion here must fail CI.
        _paginated(rds, {"DBInstances": [{"DBInstanceIdentifier": "db-idle"}]})
        cw.get_metric_statistics.return_value = {"Datapoints": [{"Average": 0}]}

        findings = check_rds_zombies(rds, cw, "us-east-1")

        assert all(f["action"] == "report_only" for f in findings)
        rds.delete_db_instance.assert_not_called()


# --- NAT gateways (report-only) -------------------------------------------


class TestCheckNatGwZombies:
    def test_reports_idle_nat(self, ec2, cw):
        _paginated(ec2, {"NatGateways": [{"NatGatewayId": "nat-idle"}]})
        cw.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 0}]}

        findings = check_nat_gw_zombies(ec2, cw, "us-east-1")

        assert findings[0]["action"] == "report_only"
        assert findings[0]["monthly_cost"] == 32.0

    def test_ignores_active_nat(self, ec2, cw):
        _paginated(ec2, {"NatGateways": [{"NatGatewayId": "nat-busy"}]})
        cw.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 1048576}]}

        assert check_nat_gw_zombies(ec2, cw, "us-east-1") == []

    def test_never_deletes_a_gateway(self, ec2, cw):
        # NAT is report-only: a future edit adding deletion here must fail CI.
        _paginated(ec2, {"NatGateways": [{"NatGatewayId": "nat-idle"}]})
        cw.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 0}]}

        findings = check_nat_gw_zombies(ec2, cw, "us-east-1")

        assert all(f["action"] == "report_only" for f in findings)
        ec2.delete_nat_gateway.assert_not_called()


# --- Report aggregation ----------------------------------------------------


class TestBuildReport:
    def _findings(self):
        return [
            hunter._finding(
                "EBS", "vol-1", "us-east-1", 10.0, "unattached", "deleted", 30
            ),
            hunter._finding(
                "Elastic_IP",
                "1.2.3.4",
                "us-east-1",
                3.6,
                "unassociated",
                "would_delete",
            ),
            hunter._finding("RDS", "db-1", "us-west-2", 100.0, "idle", "report_only"),
        ]

    def test_summary_counts_and_savings(self):
        config = {"dry_run": False, "min_age_days": 7}

        report = build_report(self._findings(), ["us-east-1", "us-west-2"], [], config)
        summary = report["summary"]

        assert summary["zombies_found"] == 3
        assert summary["deleted"] == 1
        assert summary["realized_monthly_savings"] == "$10.00"
        assert summary["potential_monthly_savings"] == "$103.60"
        assert summary["savings_by_type"]["RDS"] == "$100.00"

    def test_markdown_contains_table_rows(self):
        config = {"dry_run": True, "min_age_days": 7}

        report = build_report(self._findings(), ["us-east-1"], [], config)

        assert "# FinOps Zombie Hunter Report" in report["markdown"]
        assert "vol-1" in report["markdown"]
        assert "db-1" in report["markdown"]


# --- Handler integration ---------------------------------------------------


def _fake_clients():
    ec2 = MagicMock()
    ec2.describe_regions.return_value = {"Regions": [{"RegionName": "us-east-1"}]}
    ec2.get_paginator.return_value.paginate.return_value = [
        {"Volumes": [], "NatGateways": []}
    ]
    ec2.describe_addresses.return_value = {"Addresses": []}
    rds = MagicMock()
    rds.get_paginator.return_value.paginate.return_value = [{"DBInstances": []}]
    return {
        "ec2": ec2,
        "cloudwatch": MagicMock(),
        "rds": rds,
        "sns": MagicMock(),
        "s3": MagicMock(),
    }


class TestLambdaHandler:
    def test_dry_run_publishes_without_deleting(self, monkeypatch):
        clients = _fake_clients()
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:T")
        monkeypatch.delenv("REPORT_BUCKET", raising=False)

        with patch.object(
            hunter.boto3, "client", side_effect=lambda s, **k: clients[s]
        ):
            report = lambda_handler({}, None)

        # Handler returns the full report (summary + details + markdown).
        assert report["summary"]["zombies_found"] == 0
        assert report["summary"]["dry_run"] is True
        assert report["markdown"].startswith("# FinOps Zombie Hunter Report")
        assert "details" in report
        clients["sns"].publish.assert_called_once()
        clients["s3"].put_object.assert_not_called()

    def test_report_persisted_when_bucket_set(self, monkeypatch):
        clients = _fake_clients()
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:T")
        monkeypatch.setenv("REPORT_BUCKET", "my-report-bucket")

        with patch.object(
            hunter.boto3, "client", side_effect=lambda s, **k: clients[s]
        ):
            lambda_handler({}, None)

        # One JSON object and one Markdown object.
        assert clients["s3"].put_object.call_count == 2

    def test_missing_sns_topic_raises(self, monkeypatch):
        monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)

        with pytest.raises(ValueError):
            lambda_handler({}, None)
