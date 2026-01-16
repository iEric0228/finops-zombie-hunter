resource "aws_iam_role" "lambda_exec" {
  name = "FinOps-Zombie-Hunter-Role"
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
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

output "lambda_exec_role_arn" {
  value = aws_iam_role.lambda_exec.arn
}