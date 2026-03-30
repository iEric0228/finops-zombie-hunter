"""
FinOps Zombie Hunter: Identifies unused AWS resources across all regions
and sends cost-saving reports via SNS. Supports dry-run mode for safe operation.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("zombie-hunter")
logger.setLevel(logging.INFO)


def _get_metric_stats(cw_client, namespace, metric_name, dimensions, stat="Average"):
    """Fetch CloudWatch metric statistics for the past 7 days."""
    now = datetime.now(timezone.utc)
    return cw_client.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=now - timedelta(days=7),
        EndTime=now,
        Period=86400,
        Statistics=[stat],
    )


def check_rds_zombies(rds_client, cw_client, dry_run):
    """Check for RDS instances with zero connections over the past week."""
    savings = 0.0
    count = 0
    paginator = rds_client.get_paginator("describe_db_instances")

    for page in paginator.paginate():
        for db in page["DBInstances"]:
            db_id = db["DBInstanceIdentifier"]
            try:
                metrics = _get_metric_stats(
                    cw_client,
                    "AWS/RDS",
                    "DatabaseConnections",
                    [{"Name": "DBInstanceIdentifier", "Value": db_id}],
                )
                if not metrics["Datapoints"] or all(
                    d["Average"] == 0 for d in metrics["Datapoints"]
                ):
                    instance_saving = 100.0
                    savings += instance_saving
                    count += 1
                    logger.info(
                        "RDS zombie: %s (zero connections for 7d, ~$%.2f/mo)",
                        db_id,
                        instance_saving,
                    )
            except ClientError as exc:
                logger.warning("Failed to check RDS %s: %s", db_id, exc)

    return savings, count


def check_nat_gw_zombies(ec2_client, cw_client, dry_run):
    """Check for NAT Gateways with zero bytes out in the past week."""
    savings = 0.0
    count = 0
    paginator = ec2_client.get_paginator("describe_nat_gateways")

    for page in paginator.paginate(
        Filters=[{"Name": "state", "Values": ["available"]}]
    ):
        for nat in page["NatGateways"]:
            nat_id = nat["NatGatewayId"]
            try:
                metrics = _get_metric_stats(
                    cw_client,
                    "AWS/NATGateway",
                    "BytesOutToDestination",
                    [{"Name": "NatGatewayId", "Value": nat_id}],
                    stat="Sum",
                )
                if not metrics["Datapoints"] or all(
                    d["Sum"] == 0 for d in metrics["Datapoints"]
                ):
                    savings += 32.0
                    count += 1
                    logger.info(
                        "NAT GW zombie: %s (zero bytes out for 7d, ~$32/mo)",
                        nat_id,
                    )
            except ClientError as exc:
                logger.warning("Failed to check NAT GW %s: %s", nat_id, exc)

    return savings, count


def check_elastic_ip_zombies(ec2_client, dry_run):
    """Check for unattached Elastic IPs (not associated with any resource)."""
    savings = 0.0
    count = 0

    try:
        elastic_ips = ec2_client.describe_addresses()["Addresses"]
    except ClientError as exc:
        logger.warning("Failed to describe addresses: %s", exc)
        return savings, count

    for eip in elastic_ips:
        if "AssociationId" not in eip:
            savings += 3.6
            count += 1
            logger.info(
                "EIP zombie: %s (unattached, ~$3.60/mo)",
                eip.get("PublicIp", eip.get("AllocationId", "unknown")),
            )

    return savings, count


def check_ebs_zombies(ec2_client, dry_run):
    """Check for unattached EBS volumes."""
    savings = 0.0
    count = 0
    paginator = ec2_client.get_paginator("describe_volumes")

    for page in paginator.paginate(
        Filters=[{"Name": "status", "Values": ["available"]}]
    ):
        for volume in page["Volumes"]:
            cost = volume["Size"] * 0.10
            savings += cost
            count += 1
            logger.info(
                "EBS zombie: %s (%dGB, ~$%.2f/mo)",
                volume["VolumeId"],
                volume["Size"],
                cost,
            )

    return savings, count


def lambda_handler(event, context):  # pylint: disable=unused-argument
    """AWS Lambda entrypoint for zombie resource scan."""
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")

    if not sns_topic_arn:
        raise ValueError("SNS_TOPIC_ARN environment variable is required")

    logger.info("Starting zombie scan (dry_run=%s)", dry_run)

    initial_ec2 = boto3.client("ec2")
    try:
        regions = [
            r["RegionName"] for r in initial_ec2.describe_regions()["Regions"]
        ]
    except ClientError as exc:
        logger.error("Failed to list regions: %s", exc)
        raise

    totals = {"EBS": 0.0, "RDS": 0.0, "NAT_GW": 0.0, "Elastic_IP": 0.0}
    counts = {"ebs_volumes": 0, "rds_instances": 0, "nat_gateways": 0, "elastic_ips": 0}
    errors = []

    for region in regions:
        logger.info("Scanning region: %s", region)
        try:
            ec2 = boto3.client("ec2", region_name=region)
            cw = boto3.client("cloudwatch", region_name=region)
            rds = boto3.client("rds", region_name=region)

            ebs_savings, ebs_count = check_ebs_zombies(ec2, dry_run)
            totals["EBS"] += ebs_savings
            counts["ebs_volumes"] += ebs_count

            rds_savings, rds_count = check_rds_zombies(rds, cw, dry_run)
            totals["RDS"] += rds_savings
            counts["rds_instances"] += rds_count

            nat_savings, nat_count = check_nat_gw_zombies(ec2, cw, dry_run)
            totals["NAT_GW"] += nat_savings
            counts["nat_gateways"] += nat_count

            eip_savings, eip_count = check_elastic_ip_zombies(ec2, dry_run)
            totals["Elastic_IP"] += eip_savings
            counts["elastic_ips"] += eip_count

        except ClientError as exc:
            logger.warning("Error scanning region %s: %s", region, exc)
            errors.append({"region": region, "error": str(exc)})

    total_savings = sum(totals.values())
    total_zombies = sum(counts.values())

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "regions_scanned": len(regions),
        "zombie_resources": counts,
        "savings_by_type": {k: f"${v:.2f}" for k, v in totals.items()},
        "estimated_monthly_savings": f"${total_savings:.2f}",
        "errors": errors,
    }

    logger.info("Scan complete: %d zombies, $%.2f/mo savings", total_zombies, total_savings)

    sns = boto3.client("sns")
    try:
        if total_zombies > 0:
            message = (
                f"Zombie resources detected!\n\n"
                f"{json.dumps(summary, indent=2)}"
            )
        else:
            message = (
                f"No zombie resources found.\n\n"
                f"{json.dumps(summary, indent=2)}"
            )
        sns.publish(
            TopicArn=sns_topic_arn,
            Subject=f"Zombie Hunter: {total_zombies} zombies (${total_savings:.2f}/mo)",
            Message=message,
        )
    except ClientError as exc:
        logger.error("Failed to publish SNS notification: %s", exc)

    return summary
