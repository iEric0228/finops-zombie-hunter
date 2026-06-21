variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "notification_email" {
  description = "Email address for SNS zombie scan notifications. Empty = deploy without an email subscription (reports still go to S3 + the run summary)."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.notification_email == "" || can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.notification_email))
    error_message = "notification_email must be a valid email address or empty."
  }
}

variable "lambda_reserved_concurrency" {
  description = "Reserved concurrent executions for the Lambda. -1 = unreserved (required on accounts with a low concurrency limit; reserving any value needs >= 10 unreserved to remain)."
  type        = number
  default     = -1
}

variable "schedule_expression" {
  description = "EventBridge schedule expression for zombie scans"
  type        = string
  default     = "cron(0 0 ? * SUN *)"
}

variable "dry_run" {
  description = "Enable dry-run mode (no deletions). Set to false to allow resource cleanup."
  type        = bool
  default     = true
}

variable "min_age_days" {
  description = "Minimum age in days before an unattached resource is eligible for deletion"
  type        = number
  default     = 7

  validation {
    condition     = var.min_age_days >= 0
    error_message = "min_age_days must be zero or greater."
  }
}

variable "report_retention_days" {
  description = "Days to retain scan reports in S3 before lifecycle expiration"
  type        = number
  default     = 90
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300

  validation {
    condition     = var.lambda_timeout >= 60 && var.lambda_timeout <= 900
    error_message = "Lambda timeout must be between 60 and 900 seconds."
  }
}

variable "lambda_memory_size" {
  description = "Lambda function memory in MB"
  type        = number
  default     = 256

  validation {
    condition     = var.lambda_memory_size >= 128 && var.lambda_memory_size <= 3008
    error_message = "Lambda memory must be between 128 and 3008 MB."
  }
}
