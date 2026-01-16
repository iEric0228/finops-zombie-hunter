"""
Zombie Hunter Lambda: Identifies and optionally deletes unused AWS resources for cost optimization.
All destructive actions are protected by dry_run mode.
"""
import os
from datetime import datetime, timedelta
import boto3

# --- 1. RDS Hunter ---
def check_rds_zombies(rds_client, cw_client, dry_run):
    """Check for RDS instances with zero connections over the past week."""
    savings = 0
    instances = rds_client.describe_db_instances()
    for db in instances["DBInstances"]:
        db_id = db["DBInstanceIdentifier"]
        metrics = cw_client.get_metric_statistics(
            Namespace="AWS/RDS",
            MetricName="DatabaseConnections",
            Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            StartTime=datetime.utcnow() - timedelta(days=7),
            EndTime=datetime.utcnow(),
            Period=86400,
            Statistics=["Average"],
        )
        if not metrics["Datapoints"] or all(d["Average"] == 0 for d in metrics["Datapoints"]):
            instance_saving = 100
            savings += instance_saving
            print(
                f"[RDS Zombie] : {db_id} has had zero connections in the past week. "
                f"Potential saving: ${instance_saving}/month."
            )
            if not dry_run:
                print(f"Would delete RDS instance: {db_id}")
    return savings

# --- 2. NAT Gateway Hunter ---
def check_nat_gw_zombies(ec2_client, cw_client, dry_run):
    """Check for NAT Gateways with zero bytes out in the past week."""
    nat_gateways = ec2_client.describe_nat_gateways(
        Filters=[{"Name": "state", "Values": ["available"]}]
    )["NatGateways"]
    savings = 0
    for nat in nat_gateways:
        nat_id = nat["NatGatewayId"]
        metrics = cw_client.get_metric_statistics(
            Namespace="AWS/NATGateway",
            MetricName="BytesOutToDestination",
            Dimensions=[{"Name": "NatGatewayId", "Value": nat_id}],
            StartTime=datetime.utcnow() - timedelta(days=7),
            EndTime=datetime.utcnow(),
            Period=604800,
            Statistics=["Sum"],
        )
        if not metrics["Datapoints"] or metrics["Datapoints"][0]["Sum"] == 0:
            savings += 32
            print(
                f"[NAT Gateway Zombie] : {nat_id} has had zero bytes out in the past week. "
                f"Potential saving: $32/month."
            )
            if not dry_run:
                print(f"Would delete NAT Gateway: {nat_id}")
    return savings

# --- 3. Elastic IP Hunter ---
def check_elastic_ip_zombies(ec2_client, dry_run):
    """Check for unattached Elastic IPs."""
    savings = 0
    elastic_ips = ec2_client.describe_addresses()["Addresses"]
    for eip in elastic_ips:
        if "InstanceId" not in eip:
            savings += 3.6
            print(
                f"[Elastic IP Zombie] : Elastic IP {eip['PublicIp']} is unattached. "
                f"Potential saving: $3.60/month."
            )
            if not dry_run:
                print(f"Would release Elastic IP: {eip['PublicIp']}")
    return savings

# --- 4. EBS Volume Hunter ---
def check_ebs_zombies(ec2_client, dry_run):
    """Check for unattached EBS volumes."""
    savings = 0
    volumes = ec2_client.describe_volumes(
        Filters=[{"Name": "status", "Values": ["available"]}]
    )["Volumes"]
    for volume in volumes:
        cost = volume["Size"] * 0.10
        savings += cost
        print(
            f"[EBS Zombie] : Volume ID {volume['VolumeId']} of size {volume['Size']}GB "
            f"could save ${cost}/month."
        )
        if not dry_run:
            print(f"Would delete EBS Volume: {volume['VolumeId']}")
    return savings


def lambda_handler(event, context):  # pylint: disable=unused-argument
    """AWS Lambda entrypoint for zombie resource scan."""
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    initial_ec2 = boto3.client("ec2")
    regions = [region["RegionName"] for region in initial_ec2.describe_regions()["Regions"]]
    report = {"EBS": 0, "RDS": 0, "NAT_GW": 0, "Elastic_IP": 0, "total_savings": 0}
    for region in regions:
        print(f"--- Scanning region: {region} ---")
        ec2 = boto3.client("ec2", region_name=region)
        cw = boto3.client("cloudwatch", region_name=region)
        rds = boto3.client("rds", region_name=region)
        report["EBS"] += check_ebs_zombies(ec2, dry_run)
        report["RDS"] += check_rds_zombies(rds, cw, dry_run)
        report["NAT_GW"] += check_nat_gw_zombies(ec2, cw, dry_run)
        report["Elastic_IP"] += check_elastic_ip_zombies(ec2, dry_run)
    report["total_savings"] = sum([
        report["EBS"], report["RDS"], report["NAT_GW"], report["Elastic_IP"]
    ])
    summary = (
        f"Hunt Complete! Total Potential Savings: ${report['total_savings']:.2f}/mo"
    )
    if report["total_savings"] == 0:
        summary = "No zombie resources found. Great job!"
    else:
        print(f"\n{summary}")
    print(
        f"Breakdown: EBS: ${report['EBS']:.2f}, RDS: ${report['RDS']:.2f}, "
        f"NAT: ${report['NAT_GW']:.2f}, EIP: ${report['Elastic_IP']:.2f}"
    )
    return {"statusCode": 200, "body": summary, "breakdown": report}
