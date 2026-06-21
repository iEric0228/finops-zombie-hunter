variable "function_name" {
  description = "The name of the Lambda function"
  type        = string
}

variable "iam_role_arn" {
  description = "The ARN of the IAM role for Lambda execution"
  type        = string
}

variable "env_vars" {
  description = "Environment variables for the Lambda function"
  type        = map(string)
  default     = {}
}

variable "sns_topic_arn" {
  description = "The ARN of the SNS topic for notifications"
  type        = string
}

variable "timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300
}

variable "memory_size" {
  description = "Lambda function memory in MB"
  type        = number
  default     = 256
}

variable "reserved_concurrency" {
  description = "Reserved concurrent executions. -1 leaves the function unreserved. Reserving any positive value requires the account to keep >= 10 unreserved executions, so accounts with a low concurrency limit must leave this at -1."
  type        = number
  default     = -1
}
