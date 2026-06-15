"""FinOps Zombie Hunter.

Identifies unused ("zombie") AWS resources across all enabled regions,
optionally deletes the ones that are safe to remove, persists a report to
S3, and sends a summary via SNS.

Safety model
------------
Detection covers EBS volumes, RDS instances, NAT gateways and Elastic IPs.
Only two low-blast-radius types are ever eligible for automatic deletion:
unattached EBS volumes and unassociated Elastic IPs. RDS instances and NAT
gateways are always *report only* — they are never deleted by this function.

Deletion happens only when ``DRY_RUN`` is ``false``. Even then a resource is
skipped when it is younger than ``MIN_AGE_DAYS`` or carries a protective tag
(``keep`` / ``DoNotDelete``). Every resource is recorded in the report with
the action taken and, when skipped, the reason.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("zombie-hunter")
logger.setLevel(logging.INFO)

# Rough monthly cost heuristics (USD). Deliberately conservative estimates,
# not billing-accurate — see README.
EBS_COST_PER_GB = 0.10
EIP_MONTHLY_COST = 3.60
RDS_MONTHLY_COST = 100.0
NAT_MONTHLY_COST = 32.0

# Resource types that may be deleted automatically. Everything else is
# report-only regardless of configuration.
DELETABLE_TYPES = ("EBS", "Elastic_IP")

# Tag keys that exclude a resource from deletion (case-insensitive).
PROTECTED_TAG_KEYS = {"keep", "donotdelete", "do-not-delete"}

# Finding actions.
ACTION_DELETED = "deleted"
ACTION_WOULD_DELETE = "would_delete"
ACTION_REPORT_ONLY = "report_only"
ACTION_SKIPPED = "skipped"


# --- Helpers ---------------------------------------------------------------


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


def _all_zero(metrics, stat):
    """Return True when a metric has no datapoints or all are zero."""
    datapoints = metrics.get("Datapoints", [])
    return not datapoints or all(d.get(stat, 0) == 0 for d in datapoints)


def _is_protected(tags):
    """Return True when any tag key marks the resource as do-not-delete."""
    for tag in tags or []:
        if tag.get("Key", "").strip().lower() in PROTECTED_TAG_KEYS:
            return True
    return False


def _age_days(create_time):
    """Return the age of a resource in whole days, or None if unknown."""
    if not create_time:
        return None
    if isinstance(create_time, str):
        create_time = datetime.fromisoformat(create_time)
    return (datetime.now(timezone.utc) - create_time).days


def _finding(
    rtype, rid, region, monthly_cost, reason, action, age_days=None, skip_reason=None
):
    """Build an immutable finding record for the report."""
    return {
        "type": rtype,
        "id": rid,
        "region": region,
        "monthly_cost": round(monthly_cost, 2),
        "reason": reason,
        "age_days": age_days,
        "action": action,
        "skip_reason": skip_reason,
    }


# --- EBS volumes (deletable) ----------------------------------------------


def _evaluate_ebs(ec2_client, volume, region, dry_run, min_age_days):
    """Decide what to do with a single unattached EBS volume."""
    vid = volume["VolumeId"]
    cost = volume["Size"] * EBS_COST_PER_GB
    age = _age_days(volume.get("CreateTime"))

    if _is_protected(volume.get("Tags")):
        return _finding(
            "EBS",
            vid,
            region,
            cost,
            "unattached",
            ACTION_SKIPPED,
            age,
            "protected by keep tag",
        )
    if age is not None and age < min_age_days:
        return _finding(
            "EBS",
            vid,
            region,
            cost,
            "unattached",
            ACTION_SKIPPED,
            age,
            "younger than %dd" % min_age_days,
        )
    if dry_run:
        return _finding(
            "EBS", vid, region, cost, "unattached", ACTION_WOULD_DELETE, age
        )

    try:
        ec2_client.delete_volume(VolumeId=vid)
        logger.info("EBS deleted: %s (%dGB, ~$%.2f/mo)", vid, volume["Size"], cost)
        return _finding("EBS", vid, region, cost, "unattached", ACTION_DELETED, age)
    except ClientError as exc:
        logger.warning("Failed to delete EBS %s: %s", vid, exc)
        return _finding(
            "EBS",
            vid,
            region,
            cost,
            "unattached",
            ACTION_SKIPPED,
            age,
            "delete failed: %s" % exc,
        )


def check_ebs_zombies(ec2_client, region, dry_run, min_age_days):
    """Find (and optionally delete) unattached EBS volumes in a region."""
    findings = []
    paginator = ec2_client.get_paginator("describe_volumes")
    for page in paginator.paginate(
        Filters=[{"Name": "status", "Values": ["available"]}]
    ):
        for volume in page["Volumes"]:
            findings.append(
                _evaluate_ebs(ec2_client, volume, region, dry_run, min_age_days)
            )
    return findings


# --- Elastic IPs (deletable) ----------------------------------------------


def _evaluate_eip(ec2_client, eip, region, dry_run):
    """Decide what to do with a single unassociated Elastic IP."""
    label = eip.get("PublicIp") or eip.get("AllocationId") or "unknown"
    alloc = eip.get("AllocationId")
    cost = EIP_MONTHLY_COST

    if _is_protected(eip.get("Tags")):
        return _finding(
            "Elastic_IP",
            label,
            region,
            cost,
            "unassociated",
            ACTION_SKIPPED,
            None,
            "protected by keep tag",
        )
    if dry_run:
        return _finding(
            "Elastic_IP", label, region, cost, "unassociated", ACTION_WOULD_DELETE
        )
    if not alloc:
        return _finding(
            "Elastic_IP",
            label,
            region,
            cost,
            "unassociated",
            ACTION_SKIPPED,
            None,
            "no AllocationId",
        )

    try:
        ec2_client.release_address(AllocationId=alloc)
        logger.info("EIP released: %s (~$%.2f/mo)", label, cost)
        return _finding(
            "Elastic_IP", label, region, cost, "unassociated", ACTION_DELETED
        )
    except ClientError as exc:
        logger.warning("Failed to release EIP %s: %s", label, exc)
        return _finding(
            "Elastic_IP",
            label,
            region,
            cost,
            "unassociated",
            ACTION_SKIPPED,
            None,
            "release failed: %s" % exc,
        )


def check_elastic_ip_zombies(ec2_client, region, dry_run):
    """Find (and optionally release) unassociated Elastic IPs in a region."""
    findings = []
    try:
        addresses = ec2_client.describe_addresses()["Addresses"]
    except ClientError as exc:
        logger.warning("Failed to describe addresses in %s: %s", region, exc)
        return findings

    for eip in addresses:
        if "AssociationId" in eip:
            continue
        findings.append(_evaluate_eip(ec2_client, eip, region, dry_run))
    return findings


# --- RDS instances (report-only) ------------------------------------------


def check_rds_zombies(rds_client, cw_client, region):
    """Report RDS instances with zero connections over the past week."""
    findings = []
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
            except ClientError as exc:
                logger.warning("Failed to check RDS %s: %s", db_id, exc)
                continue
            if _all_zero(metrics, "Average"):
                logger.info("RDS zombie: %s (zero connections 7d, report-only)", db_id)
                findings.append(
                    _finding(
                        "RDS",
                        db_id,
                        region,
                        RDS_MONTHLY_COST,
                        "zero connections for 7d",
                        ACTION_REPORT_ONLY,
                        None,
                        "report-only (not eligible for auto-delete)",
                    )
                )
    return findings


# --- NAT gateways (report-only) -------------------------------------------


def check_nat_gw_zombies(ec2_client, cw_client, region):
    """Report NAT gateways with zero bytes out over the past week."""
    findings = []
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
            except ClientError as exc:
                logger.warning("Failed to check NAT GW %s: %s", nat_id, exc)
                continue
            if _all_zero(metrics, "Sum"):
                logger.info(
                    "NAT GW zombie: %s (zero bytes out 7d, report-only)", nat_id
                )
                findings.append(
                    _finding(
                        "NAT_GW",
                        nat_id,
                        region,
                        NAT_MONTHLY_COST,
                        "zero bytes out for 7d",
                        ACTION_REPORT_ONLY,
                        None,
                        "report-only (not eligible for auto-delete)",
                    )
                )
    return findings


# --- Orchestration ---------------------------------------------------------


def _load_config():
    """Read runtime configuration from the environment, failing fast."""
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if not sns_topic_arn:
        raise ValueError("SNS_TOPIC_ARN environment variable is required")
    return {
        "dry_run": os.getenv("DRY_RUN", "true").lower() == "true",
        "sns_topic_arn": sns_topic_arn,
        "report_bucket": os.getenv("REPORT_BUCKET", ""),
        "min_age_days": int(os.getenv("MIN_AGE_DAYS", "7")),
    }


def _list_regions(ec2_client):
    """Return the names of all enabled regions."""
    return [r["RegionName"] for r in ec2_client.describe_regions()["Regions"]]


def _scan_region(region, config):
    """Run every detector against a single region and return its findings."""
    ec2 = boto3.client("ec2", region_name=region)
    cw = boto3.client("cloudwatch", region_name=region)
    rds = boto3.client("rds", region_name=region)

    findings = []
    findings += check_ebs_zombies(
        ec2, region, config["dry_run"], config["min_age_days"]
    )
    findings += check_elastic_ip_zombies(ec2, region, config["dry_run"])
    findings += check_rds_zombies(rds, cw, region)
    findings += check_nat_gw_zombies(ec2, cw, region)
    return findings


def _sum_cost(findings, actions):
    """Sum monthly cost of findings whose action is in ``actions``."""
    return sum(f["monthly_cost"] for f in findings if f["action"] in actions)


def build_report(findings, regions, errors, config):
    """Aggregate findings into the structured report payload."""
    realized = _sum_cost(findings, {ACTION_DELETED})
    potential = _sum_cost(findings, {ACTION_WOULD_DELETE, ACTION_REPORT_ONLY})

    savings_by_type = {}
    for rtype in ("EBS", "RDS", "NAT_GW", "Elastic_IP"):
        savings_by_type[rtype] = round(
            sum(f["monthly_cost"] for f in findings if f["type"] == rtype), 2
        )

    def count(action):
        return sum(1 for f in findings if f["action"] == action)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": config["dry_run"],
        "min_age_days": config["min_age_days"],
        "regions_scanned": len(regions),
        "zombies_found": len(findings),
        "deleted": count(ACTION_DELETED),
        "would_delete": count(ACTION_WOULD_DELETE),
        "report_only": count(ACTION_REPORT_ONLY),
        "skipped": count(ACTION_SKIPPED),
        "realized_monthly_savings": "$%.2f" % realized,
        "potential_monthly_savings": "$%.2f" % potential,
        "savings_by_type": {k: "$%.2f" % v for k, v in savings_by_type.items()},
        "errors": errors,
    }
    return {
        "summary": summary,
        "details": findings,
        "markdown": _render_markdown(summary, findings),
    }


def _render_markdown(summary, findings):
    """Render a human-readable Markdown report."""
    mode = "DRY RUN (no deletions)" if summary["dry_run"] else "DESTROY"
    lines = [
        "# FinOps Zombie Hunter Report",
        "",
        "- **Generated:** %s" % summary["timestamp"],
        "- **Mode:** %s" % mode,
        "- **Regions scanned:** %d" % summary["regions_scanned"],
        "- **Zombies found:** %d" % summary["zombies_found"],
        "- **Deleted:** %d  |  **Would delete:** %d  |  **Report-only:** %d  |  "
        "**Skipped:** %d"
        % (
            summary["deleted"],
            summary["would_delete"],
            summary["report_only"],
            summary["skipped"],
        ),
        "- **Realized savings:** %s/mo" % summary["realized_monthly_savings"],
        "- **Potential savings:** %s/mo" % summary["potential_monthly_savings"],
        "",
        "| Type | ID | Region | ~$/mo | Action | Reason / Skip |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for f in findings:
        note = f["skip_reason"] or f["reason"]
        lines.append(
            "| %s | %s | %s | $%.2f | %s | %s |"
            % (f["type"], f["id"], f["region"], f["monthly_cost"], f["action"], note)
        )
    return "\n".join(lines)


def _persist_report(report, config):
    """Write the JSON and Markdown report to S3. Returns the S3 URI or None."""
    bucket = config["report_bucket"]
    if not bucket:
        return None

    stamp = report["summary"]["timestamp"].replace(":", "").replace("-", "")
    prefix = "reports/zombie-report-%s" % stamp
    s3 = boto3.client("s3")
    try:
        s3.put_object(
            Bucket=bucket,
            Key="%s.json" % prefix,
            Body=json.dumps(report, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        s3.put_object(
            Bucket=bucket,
            Key="%s.md" % prefix,
            Body=report["markdown"].encode("utf-8"),
            ContentType="text/markdown",
        )
        uri = "s3://%s/%s.json" % (bucket, prefix)
        logger.info("Report written to %s", uri)
        return uri
    except ClientError as exc:
        logger.error("Failed to write report to S3: %s", exc)
        return None


def _notify(report, config, report_uri):
    """Publish the report summary to SNS."""
    summary = report["summary"]
    found = summary["zombies_found"]
    location = "\nFull report: %s" % report_uri if report_uri else ""
    headline = "Zombie resources detected!" if found else "No zombie resources found."
    message = "%s\n\n%s%s" % (headline, json.dumps(summary, indent=2), location)
    subject = "Zombie Hunter: %d found (%s/mo potential)" % (
        found,
        summary["potential_monthly_savings"],
    )
    sns = boto3.client("sns")
    try:
        sns.publish(TopicArn=config["sns_topic_arn"], Subject=subject, Message=message)
    except ClientError as exc:
        logger.error("Failed to publish SNS notification: %s", exc)


def lambda_handler(event, context):  # pylint: disable=unused-argument
    """AWS Lambda entrypoint for the zombie resource scan."""
    config = _load_config()
    logger.info(
        "Starting zombie scan (dry_run=%s, min_age_days=%d)",
        config["dry_run"],
        config["min_age_days"],
    )

    initial_ec2 = boto3.client("ec2")
    try:
        regions = _list_regions(initial_ec2)
    except ClientError as exc:
        logger.error("Failed to list regions: %s", exc)
        raise

    findings = []
    errors = []
    for region in regions:
        logger.info("Scanning region: %s", region)
        try:
            findings += _scan_region(region, config)
        except ClientError as exc:
            logger.warning("Error scanning region %s: %s", region, exc)
            errors.append({"region": region, "error": str(exc)})

    report = build_report(findings, regions, errors, config)
    logger.info(
        "Scan complete: %d zombies (%d deleted, %s/mo realized)",
        report["summary"]["zombies_found"],
        report["summary"]["deleted"],
        report["summary"]["realized_monthly_savings"],
    )

    report_uri = _persist_report(report, config)
    _notify(report, config, report_uri)

    return report["summary"]
