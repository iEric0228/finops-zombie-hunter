variable "function_name" {
  description = "Lambda function name for log group ARN scoping"
  type        = string
}

variable "sns_topic_arn" {
  description = "SNS topic ARN for publish permission scoping"
  type        = string
}

variable "report_bucket_arn" {
  description = "ARN of the S3 bucket that receives scan reports"
  type        = string
}

variable "enable_destroy" {
  description = "Attach delete permissions so the Lambda can remove zombie resources. Keep false in dry-run mode."
  type        = bool
  default     = false
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_iam_role" "lambda_exec" {
  name = "FinOps-Zombie-Hunter-Role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "read_only" {
  name = "FinOps-Zombie-Hunter-ReadOnly"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Account-wide zombie discovery requires unscoped reads; these
        # Describe/GetMetricStatistics APIs do not support resource-level
        # permissions anyway.
        Sid    = "DescribeResources"
        Effect = "Allow"
        Action = [
          "ec2:DescribeVolumes",
          "ec2:DescribeNatGateways",
          "ec2:DescribeAddresses",
          "ec2:DescribeRegions",
          "rds:DescribeDBInstances",
          "cloudwatch:GetMetricStatistics",
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "sns_publish" {
  name = "FinOps-Zombie-Hunter-SNSPublish"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "PublishToSNS"
        Effect = "Allow"
        Action = [
          "sns:Publish",
        ]
        Resource = var.sns_topic_arn
      },
      {
        Sid    = "KMSForSNS"
        Effect = "Allow"
        Action = [
          "kms:GenerateDataKey",
          "kms:Decrypt",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "sns.${data.aws_region.current.name}.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "report_s3" {
  name = "FinOps-Zombie-Hunter-ReportS3"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WriteReports"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
        ]
        Resource = "${var.report_bucket_arn}/reports/*"
      }
    ]
  })
}

# Delete permissions are only attached when destroy mode is enabled, so a
# dry-run deployment cannot remove anything even if the code path changed.
# Resource is "*" because zombie resource IDs are dynamic and unknown at plan
# time; the runtime guards are the real safety net: dry-run by default, a
# keep/DoNotDelete tag exclusion on both types, plus a minimum-age threshold on
# EBS volumes (Elastic IPs expose no creation time, so they rely on tag + dry-run).
resource "aws_iam_role_policy" "destroy" {
  count = var.enable_destroy ? 1 : 0

  name = "FinOps-Zombie-Hunter-Destroy"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Targets are discovered at runtime (zombies are by definition
        # untagged/unowned), so ARN/tag scoping is not possible here.
        Sid    = "DeleteZombies"
        Effect = "Allow"
        Action = [
          "ec2:DeleteVolume",
          "ec2:ReleaseAddress",
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "logging" {
  name = "FinOps-Zombie-Hunter-Logging"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.function_name}:*"
      }
    ]
  })
}

output "lambda_exec_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_exec.arn
}
