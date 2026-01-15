import boto3
import os
from datetime import datetime, timedelta

# --- 1. RDS Hunter ---
def check_rds_zombies(rds_client, cw_client, dry_run):
    savings = 0
    instances = rds_client.describe_db_instances()

    for db in instances['DBInstances']:
        db_id = db['DBInstanceIdentifier']
    # Looking for RDS instances with zero connections over the past week
        metrics = cw_client.get_metric_statistics(
            Namespace = 'AWS/RDS',
            MetricName = 'DatabaseConnections',
            Dimensions = [{'Name' : 'DBInstanceIdentifier', 'Value' : db_id}],
            StartTime = datetime.utcnow() - timedelta(days=7),
            EndTime = datetime.utcnow(),
            Period = 86400,  # How many second in a day
            Statistics = ['Average']
    )

        if not metrics['Datapoints'] or all (d['Average'] == 0 for d in metrics['Datapoints']):
            instance_saving = 100
            savings += instance_saving  # Assume $100 per month for an unused RDS instance
            print(f"[RDS Zombie] : {db_id} has had zero connections in the past week. Potential saving: ${savings}/month.")
    return savings

# --- 2. NAT Gateway Hunter ---
def check_NAT_gw_zombies(ec2_client, cw_client, dry_run):
    nat_gateways = ec2_client.describe_nat_gateways(Filters =[{'Name' : 'state', 'Values' : ['available']}])
    savings = 0
    for nat in nat_gateways:
        metrics = cw_client.get_metric_statistics(
            Namespace = 'AWS/NATGateway',
            MetricName = 'BytesOutToDestination',
            Dimensions = [{'Name' : 'NatGatewayId', 'Value' : nat_id}],
            StartTime = datetime.utcnow() - timedelta(days=7),
            EndTime = datetime.utcnow(),
            Period = 604800,  # How many second in a 7 days
            Statistics = ['Sum']
        )
        if not metrics['Datapoints'] or metrics['Datapoints'][0]['Sum'] == 0:
            savings += 32 
            print(f"[NAT Gateway Zombie] : {nat_id} has had zero bytes out in the past week. Potential saving: ${savings}/month.")
    return savings
 
 # --- 3. Elastic IP Hunter ---
def check_elastic_ip_zombies(ec2_client, dry_run):
    saving = 0
    elastic_ips = ec2_client.describe_addresses()
    for eip in elastic_ips['Addresses']:
        if 'InstanceId' not in eip:
            savings += 3.6  # Assume $3.60 per month for unused Elastic IP
            print(f"[Elastic IP Zombie] : Elastic IP {eip['PublicIp']} is unattached. Potential saving: $3.60/month.")
    return savings

# --- 4. EBS Volume Hunter ---
# Filter out all the attached volumes and only show those that are unattached
 #'available' status means it is NOT attached to an EC2 instance
def check_ebs_zombies(ec2_client, dry_run):
    savings = 0
    volumes = ec2_client.describe_volumes(Filters=[{'Name': 'status', 'Values': ['available']}])['Volumes']
    for volume in volumes:
       cost = volume['Size'] * 0.10  # Assume $0.10 per GB-month for general purpose SSD
       savings += cost
       print(f"[EBS Zombie] : Volume ID {volume['VolumeId']} of size {volume['Size']}GB could save ${cost}/month.")
    return savings


def lambda_handler(event, context):
    dry_run = os.getenv('DRY_RUN', 'true').lower() == 'true'

    # 1. Get all regions
    inital_ec2 = boto3.client('ec2')
    regions = [region['RegionName'] for region in inital_ec2.describe_regions()['Regions']]

    report ={
        'EBS' : 0,
        'RDS' : 0,
        'NAT_GW' : 0,
        'Elastic_IP' : 0,
        'total_savings' : 0
    }

    for region in regions:
        print(f'--- Scanning region: {region} ---')
        ec2 = boto3.client('ec2', region_name=region)
        cw = boto3.client('cloudwatch', region_name=region)
        rds = boto3.client('rds', region_name=region)
        report['EBS'] += check_ebs_zombies(ec2, dry_run)
        report['RDS'] += check_rds_zombies(rds, cw, dry_run)
        report['NAT_GW'] += check_NAT_gw_zombies(ec2, cw, dry_run)
        report['Elastic_IP'] += check_elastic_ip_zombies(ec2, dry_run)
        report['total_savings'] = sum([report['EBS'], report['RDS'], report['NAT_GW'], report['Elastic_IP']])

    summary = f"Hunt Complete! Total Potential Savings: ${report['total_savings']:.2f}/mo"
    if report['total_savings'] == 0:
        summary = " No zombie resources found. Great job!"
    else:
        print(f"\n{summary}")
    print(f"Breakdown: EBS: ${report['EBS']:.2f}, RDS: ${report['RDS']:.2f}, NAT: ${report['NAT_GW']:.2f}, EIP: ${report['Elastic_IP']:.2f}")

    return {
        'statusCode': 200,
        'body': summary,
        'breakdown': report
    }