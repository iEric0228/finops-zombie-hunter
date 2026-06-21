data "aws_caller_identity" "current" {}

locals {
  bucket_name = "${var.name_prefix}-reports-${var.environment}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "reports" {
  bucket        = local.bucket_name
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "reports" {
  bucket = aws_s3_bucket.reports.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Reports are disposable artifacts; expire them to keep storage cost near zero.
resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "expire-old-reports"
    status = "Enabled"

    filter {}

    expiration {
      days = var.retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.retention_days
    }
  }
}

# Reject any non-TLS access to the report objects.
#
# Apply the policy LAST, after the other bucket sub-resources. On accounts where
# S3 is throttling (the lifecycle call can take ~a minute), running the policy
# in parallel with the others and S3's read-after-write consistency can make the
# policy read-back fail with "couldn't find resource". Serializing lets the new
# bucket settle first so the policy write + read-back succeed.
resource "aws_s3_bucket_policy" "reports" {
  depends_on = [
    aws_s3_bucket_public_access_block.reports,
    aws_s3_bucket_versioning.reports,
    aws_s3_bucket_server_side_encryption_configuration.reports,
    aws_s3_bucket_lifecycle_configuration.reports,
  ]

  bucket = aws_s3_bucket.reports.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.reports.arn,
          "${aws_s3_bucket.reports.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}
