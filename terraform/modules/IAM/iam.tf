resource "aws_iam_role" "lambda_exec" {
  name               = "FinOps-Zombie-Hunter-Role"
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
  tags = {
    "Project" = "FinOps-Zombie-Hunter"
  }
}

resource "aws_iam_role_policy" "lambda_exec_policy" {
  name = "FinOps-Zombie-Hunter-Policy"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ebs:DescribeVolumes",
          "ebs:DeleteVolume",
          "rds:DescribeDBInstances",
          "rds:DeleteDBInstance",
          "cloudwatch:GetMetricData",
          "ec2:DescribeNatGateways",
          "ec2:DeleteNatGateway",
          "ec2:DescribeAddresses",
          "ec2:ReleaseAddress",
          "ec2:DescribeRegions",
          "ec2:DescribeVolumes",
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_policy" "lambda_ec2_describe_regions" {
  name        = "lambda-ec2-describe-regions"
  description = "Allow Lambda to describe EC2 regions"
  policy      = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = [
          "ec2:DescribeRegions"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_ec2_describe_regions" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_ec2_describe_regions.arn
}

output "lambda_exec_role_arn" {
  value = aws_iam_role.lambda_exec.arn
}