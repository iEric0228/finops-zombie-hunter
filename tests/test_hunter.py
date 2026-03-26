"""Unit tests for the Zombie Hunter Lambda function."""

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Ensure dry_run is enabled for tests
os.environ["DRY_RUN"] = "true"
os.environ["SNS_TOPIC_ARN"] = "arn:aws:sns:us-east-1:123456789012:TestTopic"

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hunter import (
    check_ebs_zombies,
    check_elastic_ip_zombies,
    check_nat_gw_zombies,
    check_rds_zombies,
)


# --- Fixtures ---

@pytest.fixture
def mock_ec2_client():
    return MagicMock()


@pytest.fixture
def mock_cw_client():
    return MagicMock()


@pytest.fixture
def mock_rds_client():
    return MagicMock()


# --- EBS Volume Tests ---

class TestCheckEbsZombies:
    def test_detects_unattached_volumes(self, mock_ec2_client):
        mock_ec2_client.describe_volumes.return_value = {
            "Volumes": [
                {"VolumeId": "vol-abc123", "Size": 100, "State": "available"},
                {"VolumeId": "vol-def456", "Size": 50, "State": "available"},
            ]
        }

        savings = check_ebs_zombies(mock_ec2_client, dry_run=True)

        assert savings == 15.0  # (100 * 0.10) + (50 * 0.10)

    def test_returns_zero_when_no_volumes(self, mock_ec2_client):
        mock_ec2_client.describe_volumes.return_value = {"Volumes": []}

        savings = check_ebs_zombies(mock_ec2_client, dry_run=True)

        assert savings == 0

    def test_calculates_cost_by_size(self, mock_ec2_client):
        mock_ec2_client.describe_volumes.return_value = {
            "Volumes": [{"VolumeId": "vol-big", "Size": 500, "State": "available"}]
        }

        savings = check_ebs_zombies(mock_ec2_client, dry_run=True)

        assert savings == 50.0  # 500 * 0.10


# --- RDS Tests ---

class TestCheckRdsZombies:
    def test_detects_zero_connection_instances(self, mock_rds_client, mock_cw_client):
        mock_rds_client.describe_db_instances.return_value = {
            "DBInstances": [{"DBInstanceIdentifier": "db-idle"}]
        }
        mock_cw_client.get_metric_statistics.return_value = {
            "Datapoints": [{"Average": 0}, {"Average": 0}]
        }

        savings = check_rds_zombies(mock_rds_client, mock_cw_client, dry_run=True)

        assert savings == 100

    def test_ignores_active_instances(self, mock_rds_client, mock_cw_client):
        mock_rds_client.describe_db_instances.return_value = {
            "DBInstances": [{"DBInstanceIdentifier": "db-active"}]
        }
        mock_cw_client.get_metric_statistics.return_value = {
            "Datapoints": [{"Average": 5.0}, {"Average": 12.0}]
        }

        savings = check_rds_zombies(mock_rds_client, mock_cw_client, dry_run=True)

        assert savings == 0

    def test_detects_instance_with_no_datapoints(self, mock_rds_client, mock_cw_client):
        mock_rds_client.describe_db_instances.return_value = {
            "DBInstances": [{"DBInstanceIdentifier": "db-no-metrics"}]
        }
        mock_cw_client.get_metric_statistics.return_value = {"Datapoints": []}

        savings = check_rds_zombies(mock_rds_client, mock_cw_client, dry_run=True)

        assert savings == 100


# --- NAT Gateway Tests ---

class TestCheckNatGwZombies:
    def test_detects_zero_traffic_nat_gateways(self, mock_ec2_client, mock_cw_client):
        mock_ec2_client.describe_nat_gateways.return_value = {
            "NatGateways": [{"NatGatewayId": "nat-idle"}]
        }
        mock_cw_client.get_metric_statistics.return_value = {
            "Datapoints": [{"Sum": 0}]
        }

        savings = check_nat_gw_zombies(mock_ec2_client, mock_cw_client, dry_run=True)

        assert savings == 32

    def test_ignores_active_nat_gateways(self, mock_ec2_client, mock_cw_client):
        mock_ec2_client.describe_nat_gateways.return_value = {
            "NatGateways": [{"NatGatewayId": "nat-active"}]
        }
        mock_cw_client.get_metric_statistics.return_value = {
            "Datapoints": [{"Sum": 1048576}]
        }

        savings = check_nat_gw_zombies(mock_ec2_client, mock_cw_client, dry_run=True)

        assert savings == 0

    def test_detects_nat_with_no_datapoints(self, mock_ec2_client, mock_cw_client):
        mock_ec2_client.describe_nat_gateways.return_value = {
            "NatGateways": [{"NatGatewayId": "nat-no-data"}]
        }
        mock_cw_client.get_metric_statistics.return_value = {"Datapoints": []}

        savings = check_nat_gw_zombies(mock_ec2_client, mock_cw_client, dry_run=True)

        assert savings == 32


# --- Elastic IP Tests ---

class TestCheckElasticIpZombies:
    def test_detects_unattached_eips(self, mock_ec2_client):
        mock_ec2_client.describe_addresses.return_value = {
            "Addresses": [
                {"PublicIp": "1.2.3.4", "AllocationId": "eipalloc-abc"},
                {"PublicIp": "5.6.7.8", "AllocationId": "eipalloc-def"},
            ]
        }

        savings = check_elastic_ip_zombies(mock_ec2_client, dry_run=True)

        assert savings == 7.2  # 2 * 3.6

    def test_ignores_attached_eips(self, mock_ec2_client):
        mock_ec2_client.describe_addresses.return_value = {
            "Addresses": [
                {"PublicIp": "1.2.3.4", "AllocationId": "eipalloc-abc", "InstanceId": "i-123"},
            ]
        }

        savings = check_elastic_ip_zombies(mock_ec2_client, dry_run=True)

        assert savings == 0

    def test_mixed_attached_and_unattached(self, mock_ec2_client):
        mock_ec2_client.describe_addresses.return_value = {
            "Addresses": [
                {"PublicIp": "1.2.3.4", "InstanceId": "i-123"},
                {"PublicIp": "5.6.7.8"},
            ]
        }

        savings = check_elastic_ip_zombies(mock_ec2_client, dry_run=True)

        assert savings == 3.6
