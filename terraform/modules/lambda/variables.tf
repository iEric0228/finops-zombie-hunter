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
