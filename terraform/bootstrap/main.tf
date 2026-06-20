# One-time bootstrap of the Terraform remote-state backend.
#
# Chicken-and-egg: the rest of the project stores its state in an S3 bucket +
# DynamoDB lock table (see terraform/environments/dev/backend.tf), but those
# must exist before `terraform init` can use them. This config creates them
# using LOCAL state. Run it once, with AWS credentials:
#
#   terraform -chdir=terraform/bootstrap init
#   terraform -chdir=terraform/bootstrap apply
#
# After it applies, environments/dev can `terraform init` against the backend.
# The names/region here MUST match backend.tf.

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "FinOps-Zombie-Hunter"
      ManagedBy = "Terraform"
      Component = "tf-state-backend"
    }
  }
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "lock" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
