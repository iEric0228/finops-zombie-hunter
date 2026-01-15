resource "aws_iam_role" "hunter_policy" {
    name = "FinOps-Zombie-Hunter-Role"
    description = "Allows viewing and deleting availables EBS volumes"

    policy = jsonencode({
        Verison = "2012-10-17"
        Statement = [
            {
                Actions = [
                    "ebs:DescribeVolumes",
                    "ebs:DeleteVolume"
                    "rds:DescribeDBInstances",
                    "rds:DeleteDBInstance",
                    "cloudwatch:GetMetricData",
                    "ec2:DescribeNatGateways",
                    "ec2:DeleteNatGateway",
                    "ec2:DescribeAddresses",
                    "ec2:ReleaseAddress"
                ]
                Effect   = "Allow"
                Resource = "*"
            },
            {
                Actions = [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ]
                Effect   = "Allow"
                Resource = "arn:aws:logs:*:*:*"
            }
        ]
    })
}